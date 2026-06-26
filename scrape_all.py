"""Full pipeline: scrape ALL posts (video+image) and comments, write to Feishu."""
import sys
sys.stdout.reconfigure(errors='replace')
import builtins
_original_print = builtins.print
def print(*args, **kwargs):
    kwargs.setdefault('flush', True)
    _original_print(*args, **kwargs)

import asyncio
import os
import time
import zlib
from datetime import datetime
from urllib.parse import quote
from playwright.async_api import async_playwright
from core.client import DouyinClient
from core.datefilter import DateFilter
from core.throttle import fetch_json, polite_sleep, jittered_delay, backoff_delay
from config.settings import DOUYIN_COOKIE, DOUYIN_API_BASE, REQUEST_DELAY, EMPTY_RETRY
from storage.feishu import FeishuBitable, url_field
from storage.downloader import download_file, download_video_media, cleanup_downloads, DOWNLOAD_DIR

VIDEO_TABLE_ID = os.environ.get("VIDEO_TABLE_ID", "YOUR_VIDEO_TABLE_ID")
IMAGE_TABLE_ID = os.environ.get("IMAGE_TABLE_ID", "YOUR_IMAGE_TABLE_ID")
# First-level / second-level comment tables (COMMENT_TABLE_ID kept as L1 fallback)
COMMENT_L1_TABLE_ID = os.environ.get("COMMENT_L1_TABLE_ID") or os.environ.get("COMMENT_TABLE_ID", "YOUR_COMMENT_L1_TABLE_ID")
COMMENT_L2_TABLE_ID = os.environ.get("COMMENT_L2_TABLE_ID", "YOUR_COMMENT_L2_TABLE_ID")
KEYWORD = os.environ.get("DOUYIN_KEYWORD", "YOUR_KEYWORD")

# Date / time-range filter, configured via environment variables:
#   DOUYIN_PUBLISH_TIME  predefined server-side range (0/1/7/182), default 0
#   DOUYIN_START_DATE    custom client-side lower bound, YYYY-MM-DD (inclusive)
#   DOUYIN_END_DATE      custom client-side upper bound, YYYY-MM-DD (inclusive)
DATE_FILTER = DateFilter.from_inputs(
    os.environ.get("DOUYIN_PUBLISH_TIME", "0"),
    os.environ.get("DOUYIN_START_DATE") or None,
    os.environ.get("DOUYIN_END_DATE") or None,
)

# Set True (e.g. by main.py) to skip the comment scraping step.
SKIP_COMMENTS = os.environ.get("SKIP_COMMENTS", "").lower() in ("1", "true", "yes")

# Bitable app_token to write into (empty -> use FEISHU_APP_TOKEN from .env).
# main.py sets this when creating/targeting a specific bitable.
APP_TOKEN = os.environ.get("FEISHU_APP_TOKEN", "")

# Engagement filter: keep a post only if its like / collect / comment counts
# clear MIN_ENGAGEMENT (strictly greater). ENGAGEMENT_LOGIC 'or' = any metric
# passes; 'and' = all must pass. MIN_ENGAGEMENT <= 0 disables the filter.
MIN_ENGAGEMENT = int(os.environ.get("MIN_ENGAGEMENT", "0"))
ENGAGEMENT_LOGIC = os.environ.get("ENGAGEMENT_LOGIC", "or").lower()
# Cap on total posts kept (0 = no cap). Video/image are interleaved so both
# types are represented up to the cap.
MAX_POSTS = int(os.environ.get("MAX_POSTS_TOTAL", "0"))


def _passes_engagement(post):
    if MIN_ENGAGEMENT <= 0:
        return True
    checks = [
        post.get('digg_count', 0) > MIN_ENGAGEMENT,
        post.get('collect_count', 0) > MIN_ENGAGEMENT,
        post.get('comment_count', 0) > MIN_ENGAGEMENT,
    ]
    return all(checks) if ENGAGEMENT_LOGIC == 'and' else any(checks)


def _apply_engagement_and_cap(posts):
    """Filter by engagement, then interleave video/image up to MAX_POSTS."""
    kept = [p for p in posts if _passes_engagement(p)]
    if MIN_ENGAGEMENT > 0:
        print(f'[Engagement] kept {len(kept)}/{len(posts)} posts '
              f'({ENGAGEMENT_LOGIC.upper()} like/collect/comment > {MIN_ENGAGEMENT})')
    if not MAX_POSTS or len(kept) <= MAX_POSTS:
        return kept
    videos = [p for p in kept if p['type'] == 'video']
    images = [p for p in kept if p['type'] == 'image']
    out, i, j = [], 0, 0
    while len(out) < MAX_POSTS and (i < len(videos) or j < len(images)):
        if i < len(videos):
            out.append(videos[i]); i += 1
        if len(out) >= MAX_POSTS:
            break
        if j < len(images):
            out.append(images[j]); j += 1
    print(f'[Cap] limited to {len(out)} posts (max {MAX_POSTS}, video+image interleaved)')
    return out

STEALTH_JS = """
Object.defineProperty(navigator, 'webdriver', {get: () => undefined});
Object.defineProperty(navigator, 'plugins', {get: () => [1, 2, 3, 4, 5]});
Object.defineProperty(navigator, 'languages', {get: () => ['zh-CN', 'zh', 'en']});
window.chrome = {runtime: {}, loadTimes: function(){}, csi: function(){}};
Object.defineProperty(navigator, 'platform', {get: () => 'Win32'});
"""


async def _browser_search_images(keyword, seen_ids, date_filter=None):
    """Search for image/note posts via browser context.

    The Douyin Web API only returns image posts through the
    /general/search/single/ endpoint when called from a browser with proper
    security context. We navigate to a known video page first (avoids captcha),
    then call the API from within that page.

    ``date_filter`` (a :class:`DateFilter`) adds the server-side
    ``filter_selected`` range to the request URL and trims results outside the
    custom ``start_date`` / ``end_date`` window client-side.
    """
    date_filter = date_filter or DateFilter()
    results = []
    dropped = 0
    encoded_kw = quote(keyword)
    base_url = 'https://www.douyin.com/aweme/v1/web/general/search/single/'

    # Server-side filter suffix (empty when publish_time == 0).
    filter_selected = date_filter.filter_selected
    if filter_selected is not None:
        filter_suffix = f'&is_filter_search=1&filter_selected={quote(filter_selected)}'
    else:
        filter_suffix = '&is_filter_search=0'

    for attempt in range(3):
        pw = br = page = None
        try:
            pw = await async_playwright().start()
            br = await pw.chromium.launch(
                headless=True,
                args=['--disable-blink-features=AutomationControlled', '--no-sandbox'],
            )
            ctx = await br.new_context(
                viewport={'width': 1920, 'height': 1080},
                user_agent='Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36',
                locale='zh-CN',
                timezone_id='Asia/Shanghai',
            )
            await ctx.add_init_script(STEALTH_JS)
            ck = []
            for c in DOUYIN_COOKIE.split(';'):
                c = c.strip()
                if '=' in c:
                    n, v = c.split('=', 1)
                    ck.append({'name': n.strip(), 'value': v.strip(), 'domain': '.douyin.com', 'path': '/'})
            await ctx.add_cookies(ck)
            page = await ctx.new_page()

            seed_url = 'https://www.douyin.com/video/7516474427211992377'
            print(f'  Browser attempt {attempt+1}: navigating to seed page...')
            try:
                await page.goto(seed_url, wait_until='domcontentloaded', timeout=30000)
            except Exception:
                pass
            await asyncio.sleep(6)

            # Make a warmup call first (the first API call from a fresh page
            # sometimes stalls; a quick throwaway fetch primes the connection)
            try:
                await asyncio.wait_for(page.evaluate(
                    """async () => {
                        try { await fetch('https://www.douyin.com/'); return true; }
                        catch { return false; }
                    }"""
                ), timeout=10)
            except Exception:
                pass
            await asyncio.sleep(2)

            # Now search with aweme_image_web channel
            detail_ids = []
            for offset in range(0, 200, 20):
                url = (
                    f'{base_url}?device_platform=webapp&aid=6383&channel=channel_pc_web'
                    f'&search_channel=aweme_image_web&keyword={encoded_kw}'
                    f'&search_source=tab_search&query_correct_type=1{filter_suffix}'
                    f'&offset={offset}&count=20&cookie_enabled=true&platform=PC'
                )
                # Fetch this page, retrying empty/blocked responses with backoff
                # (the browser API throttles the same way the HTTP one does).
                data = None
                for att in range(EMPTY_RETRY + 1):
                    data = await asyncio.wait_for(page.evaluate(
                        """async (url) => {
                            try {
                                const resp = await fetch(url, {
                                    headers: {'Accept': 'application/json', 'Referer': 'https://www.douyin.com/'},
                                    credentials: 'include',
                                });
                                return await resp.json();
                            } catch (e) {
                                return {status_code: -1, error: e.message};
                            }
                        }""", url
                    ), timeout=30)
                    if data and data.get('status_code') == 0 and data.get('data'):
                        break
                    if att < EMPTY_RETRY:
                        d = backoff_delay(att + 1)
                        sc = data.get('status_code') if data else None
                        print(f'  [throttle?] image off{offset} empty/blocked (status={sc}); '
                              f'backoff {d:.1f}s, retry {att + 1}/{EMPTY_RETRY}')
                        await asyncio.sleep(d)

                if not data or data.get('status_code') != 0:
                    break
                items = data.get('data', [])
                if not items:
                    break
                new_count = 0
                for item in items:
                    aweme = item.get('aweme_info', {})
                    if not aweme:
                        continue
                    aweme_id = aweme.get('aweme_id', '')
                    if not aweme_id or aweme_id in seen_ids:
                        continue
                    seen_ids.add(aweme_id)
                    new_count += 1  # raw discovery — drives pagination even if date-trimmed
                    if not date_filter.matches(aweme.get('create_time', 0)):
                        dropped += 1
                        continue
                    images = aweme.get('images') or []
                    media_type = aweme.get('media_type', -1)
                    aweme_type = aweme.get('aweme_type', 0)
                    is_image = len(images) > 0 or media_type == 2 or aweme_type in (68, 150)
                    if is_image and len(images) > 0:
                        results.append(parse_post(aweme))
                        print(f'    Image post: {aweme_id} ({len(images)} images)')
                    elif is_image:
                        detail_ids.append(aweme_id)
                    else:
                        results.append(parse_post(aweme))
                if new_count == 0 or not data.get('has_more', 0):
                    break
                await asyncio.sleep(jittered_delay(3))

            # Fetch details for image posts missing image URLs
            for aid in detail_ids:
                detail_url = (
                    f'{DOUYIN_API_BASE}/aweme/detail/'
                    f'?device_platform=webapp&aid=6383&aweme_id={aid}'
                    f'&cookie_enabled=true&platform=PC'
                )
                try:
                    data = await asyncio.wait_for(page.evaluate(
                        """async (url) => {
                            try {
                                const resp = await fetch(url, {
                                    headers: {'Accept': 'application/json', 'Referer': 'https://www.douyin.com/'},
                                    credentials: 'include',
                                });
                                return await resp.json();
                            } catch (e) { return null; }
                        }""", detail_url
                    ), timeout=20)
                    if data:
                        aweme = data.get('aweme_detail', {})
                        if aweme:
                            results.append(parse_post(aweme))
                            print(f'    Detail: {aid} ({len(aweme.get("images") or [])} images)')
                except Exception:
                    pass
                await asyncio.sleep(2)

            break  # success, exit retry loop

        except Exception as e:
            print(f'  Browser attempt {attempt+1} failed: {e}')
            if attempt < 2:
                await asyncio.sleep(5)
        finally:
            try:
                if br:
                    await br.close()
                if pw:
                    await pw.stop()
            except:
                pass

    image_count = sum(1 for p in results if p['type'] == 'image')
    video_count = len(results) - image_count
    if date_filter.has_custom_range:
        print(f'  Browser phase: dropped {dropped} posts outside the date range')
    print(f'  Browser phase: {video_count} videos, {image_count} images')
    return results


async def search_all_posts():
    """Search for ALL posts (video + image/note) without engagement filter.

    Video posts: use HTTP API /search/item/ (fast, no browser needed).
    Image/note posts: use browser-based /general/search/single/ with aweme_image_web
    channel, then fetch full detail for each to get image URLs.
    """
    all_posts = []
    seen_ids = set()
    dropped = 0

    if DATE_FILTER.is_active:
        print(f'[Date filter] {DATE_FILTER.describe()}')

    # --- Phase 1: Video posts via HTTP API ---
    print('[Phase 1] Searching video posts via HTTP API...')
    async with DouyinClient(cookies=DOUYIN_COOKIE) as client:
        channels = ['aweme_video_web', 'aweme_general']
        for channel in channels:
            for offset in range(0, 100, 20):
                params = {
                    'keyword': KEYWORD,
                    'search_channel': channel,
                    'sort_type': 0,
                    'count': 20,
                    'offset': offset,
                    'search_source': 'normal_search',
                    'cookie_enabled': 'true',
                    'device_platform': 'webapp',
                    'aid': '6383',
                    'platform': 'PC',
                }
                DATE_FILTER.apply_search_params(params)
                data = await fetch_json(
                    client, f'{DOUYIN_API_BASE}/search/item/', params,
                    item_keys=('data',), label=f'{channel} off{offset}',
                )
                if not data or data.get('status_code') != 0:
                    break
                items = data.get('data', [])
                if not items:
                    break
                new_count = 0
                for item in items:
                    aweme = item.get('aweme_info', {})
                    if not aweme:
                        continue
                    aweme_id = aweme.get('aweme_id', '')
                    if aweme_id and aweme_id not in seen_ids:
                        seen_ids.add(aweme_id)
                        new_count += 1  # raw discovery — drives pagination even if date-trimmed
                        if not DATE_FILTER.matches(aweme.get('create_time', 0)):
                            dropped += 1
                            continue
                        all_posts.append(parse_post(aweme))
                if new_count == 0:
                    break
                if not data.get('has_more', 0):
                    break
                await polite_sleep()

    video_count = len(all_posts)
    if DATE_FILTER.has_custom_range:
        print(f'  Dropped {dropped} video posts outside the date range')
    print(f'  Found {video_count} video posts')

    # --- Phase 2: Image/note posts via browser-based general search API ---
    print('[Phase 2] Searching image/note posts via browser API...')
    image_posts_from_browser = await _browser_search_images(KEYWORD, seen_ids, DATE_FILTER)
    all_posts.extend(image_posts_from_browser)

    image_count = sum(1 for p in all_posts if p['type'] == 'image')
    print(f'Total unique posts found: {len(all_posts)}')
    print(f'  Video: {len(all_posts) - image_count}, Image/Note: {image_count}')

    # Apply engagement filter + total cap (interleave video/image).
    all_posts = _apply_engagement_and_cap(all_posts)
    kept_img = sum(1 for p in all_posts if p['type'] == 'image')
    print(f'After filter/cap: {len(all_posts)} posts (video {len(all_posts) - kept_img}, image {kept_img})')
    return all_posts


def parse_post(aweme):
    """Parse a post (video or image/note) from the API response."""
    stats = aweme.get('statistics') or {}
    author = aweme.get('author') or {}
    video = aweme.get('video') or {}
    images = aweme.get('images') or []
    create_ts = aweme.get('create_time', 0)
    create_str = time.strftime('%Y-%m-%d %H:%M:%S', time.localtime(create_ts)) if create_ts else ''
    aweme_id = aweme.get('aweme_id', '')

    # Determine type
    has_images = len(images) > 0
    aweme_type = aweme.get('aweme_type', 0)
    media_type = aweme.get('media_type', -1)
    post_type = 'image' if has_images or aweme_type in (68, 150) or media_type == 2 else 'video'

    # Cover
    cover_url = ''
    if video:
        cover_obj = video.get('cover') or {}
        cover_list = cover_obj.get('url_list') or []
        cover_url = cover_list[0] if cover_list else ''

    # Video URL
    video_url = ''
    play_addr = video.get('play_addr') or {}
    if play_addr:
        url_list = play_addr.get('url_list') or []
        video_url = url_list[0] if url_list else ''

    # Image URLs
    image_urls = []
    for img in images:
        if img:
            url_list = img.get('url_list') or []
            if url_list:
                image_urls.append(url_list[0])

    # Hashtags
    hashtags = []
    for tag in (aweme.get('text_extra') or []):
        if tag and tag.get('hashtag_name'):
            hashtags.append(tag['hashtag_name'])

    # Post URL (note format for image posts)
    if post_type == 'image':
        post_url = f'https://www.douyin.com/note/{aweme_id}'
    else:
        post_url = f'https://www.douyin.com/video/{aweme_id}'

    sec_uid = author.get('sec_uid', '')

    return {
        'aweme_id': aweme_id,
        'type': post_type,
        'desc': aweme.get('desc', ''),
        'author_nickname': author.get('nickname', ''),
        'author_sec_uid': sec_uid,
        'digg_count': stats.get('digg_count', 0),
        'comment_count': stats.get('comment_count', 0),
        'collect_count': stats.get('collect_count', 0),
        'share_count': stats.get('share_count', 0),
        'create_time': create_str,
        'cover_url': cover_url,
        'video_url': video_url,
        'image_urls': image_urls,
        'post_url': post_url,
        'author_homepage': f'https://www.douyin.com/user/{sec_uid}' if sec_uid else '',
        'hashtags': ', '.join(hashtags),
    }


def download_and_upload_media(post, feishu):
    """Download media and upload to Feishu. Returns file tokens dict."""
    aweme_id = post['aweme_id']
    tokens = {'cover': '', 'video': '', 'images': []}
    os.makedirs(DOWNLOAD_DIR, exist_ok=True)

    # Download and upload cover
    if post['cover_url']:
        path = download_file(post['cover_url'], f'{aweme_id}_cover.jpg')
        if path:
            token = feishu.upload_file(path, 'bitable_image')
            if token:
                tokens['cover'] = token

    # Download and upload video (for video posts)
    if post['type'] == 'video' and post['video_url']:
        path = download_file(post['video_url'], f'{aweme_id}_video.mp4', timeout=180)
        if path:
            token = feishu.upload_file(path, 'bitable_file')
            if token:
                tokens['video'] = token

    # Download and upload images (for image posts or any post with images)
    for i, url in enumerate(post['image_urls']):
        path = download_file(url, f'{aweme_id}_img_{i}.jpg')
        if path:
            token = feishu.upload_file(path, 'bitable_image')
            if token:
                tokens['images'].append(token)

    return tokens


def build_record(post, tokens):
    """Build a Feishu record from post data and uploaded file tokens."""
    now = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    record = {
        '作者': post['author_nickname'],
        '作品正文': post['desc'],
        '作品链接': url_field(post['post_url']),
        '作者主页': url_field(post['author_homepage']),
        '点赞数': post['digg_count'],
        '评论数': post['comment_count'],
        '收藏数': post['collect_count'],
        '分享数': post['share_count'],
        '发布时间': post['create_time'],
        '话题标签': post['hashtags'],
        '搜索关键词': KEYWORD,
        '爬取时间': now,
    }

    # Add file attachments (only if token exists)
    if tokens['cover']:
        record['作品封面'] = [{'file_token': tokens['cover']}]
    if tokens['video']:
        record['作品视频'] = [{'file_token': tokens['video']}]
    if tokens['images']:
        record['作品图片'] = [{'file_token': t} for t in tokens['images']]

    return record


async def _browser_get_json(page, url, timeout=30):
    """Run a credentialed fetch inside the browser page and return parsed JSON."""
    try:
        return await asyncio.wait_for(page.evaluate(
            """async (url) => {
                try {
                    const resp = await fetch(url, {
                        headers: {'Accept': 'application/json', 'Referer': 'https://www.douyin.com/'},
                        credentials: 'include',
                    });
                    return await resp.json();
                } catch (e) { return {status_code: -1, error: e.message}; }
            }""", url
        ), timeout=timeout)
    except Exception:
        return {}


async def _fetch_replies(page, aweme_id, comment_id, parent_text_user, max_replies=50):
    """Fetch second-level (reply) comments for one first-level comment."""
    out = []
    cursor = 0
    now = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    while len(out) < max_replies:
        url = (
            f'{DOUYIN_API_BASE}/comment/list/reply/'
            f'?item_id={aweme_id}&comment_id={comment_id}'
            f'&cursor={cursor}&count=20&item_type=0'
            f'&device_platform=webapp&aid=6383&cookie_enabled=true&platform=PC'
        )
        data = await _browser_get_json(page, url)
        if not data or data.get('status_code') != 0:
            break
        replies = data.get('comments') or []
        if not replies:
            break
        for r in replies:
            user = r.get('user', {})
            ct = r.get('create_time', 0)
            # reply target: explicit reply_to user if present, else the L1 author
            reply_to = ''
            rt = r.get('reply_to_username') or (r.get('reply_to_reply') or {}).get('user', {}).get('nickname', '')
            reply_to = rt or parent_text_user
            out.append({
                '评论ID': r.get('cid', ''),
                '评论内容': r.get('text', ''),
                '评论者昵称': user.get('nickname', ''),
                '评论者ID': user.get('uid', ''),
                '父评论ID': comment_id,
                '回复对象': reply_to,
                '所属作品ID': aweme_id,
                '点赞数': r.get('digg_count', 0),
                '评论时间': time.strftime('%Y-%m-%d %H:%M:%S', time.localtime(ct)) if ct else '',
                '搜索关键词': KEYWORD,
                '爬取时间': now,
            })
            if len(out) >= max_replies:
                break
        if not data.get('has_more', 0):
            break
        cursor = data.get('cursor', 0)
        await polite_sleep()
    return out


async def fetch_comments_for_posts(posts):
    """Fetch first- AND second-level comments for all posts using the browser.

    Returns (l1_records, l2_records) — written to separate tables per the data
    model agreement (一级评论 / 二级评论).
    """
    pw = await async_playwright().start()
    browser = await pw.chromium.launch(
        headless=True,
        args=['--disable-blink-features=AutomationControlled', '--no-sandbox'],
    )
    context = await browser.new_context(
        viewport={'width': 1920, 'height': 1080},
        user_agent='Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36',
        locale='zh-CN',
        timezone_id='Asia/Shanghai',
    )
    await context.add_init_script(STEALTH_JS)

    cookies = []
    for item in DOUYIN_COOKIE.split(';'):
        item = item.strip()
        if '=' in item:
            n, v = item.split('=', 1)
            cookies.append({'name': n.strip(), 'value': v.strip(), 'domain': '.douyin.com', 'path': '/'})
    await context.add_cookies(cookies)

    page = await context.new_page()
    l1_records = []
    l2_records = []

    for vi, post in enumerate(posts):
        aweme_id = post['aweme_id']
        comment_count = post['comment_count']
        if comment_count == 0:
            print(f'  [{vi+1}/{len(posts)}] Skip {aweme_id} (0 comments)')
            continue

        print(f'  [{vi+1}/{len(posts)}] {aweme_id} (comments: {comment_count})')

        # Navigate to video page (comments work from video URL even for note posts)
        try:
            await page.goto(
                f'https://www.douyin.com/video/{aweme_id}',
                wait_until='domcontentloaded', timeout=30000
            )
        except:
            pass
        await asyncio.sleep(4)

        cursor = 0
        video_comments = 0
        video_replies = 0
        max_comments = min(comment_count, 100)

        while video_comments < max_comments:
            url = (
                f'{DOUYIN_API_BASE}/comment/list/'
                f'?aweme_id={aweme_id}'
                f'&cursor={cursor}&count=20'
                f'&item_type=0'
                f'&device_platform=webapp&aid=6383'
                f'&cookie_enabled=true&platform=PC'
            )
            data = await _browser_get_json(page, url)
            if not data or data.get('status_code') != 0:
                break
            comments = data.get('comments', [])
            if not comments:
                break

            now = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
            for c in comments:
                user = c.get('user', {})
                ct = c.get('create_time', 0)
                cid = c.get('cid', '')
                reply_total = c.get('reply_comment_total', 0)
                l1_records.append({
                    '评论ID': cid,
                    '评论内容': c.get('text', ''),
                    '评论者昵称': user.get('nickname', ''),
                    '评论者ID': user.get('uid', ''),
                    '所属作品ID': aweme_id,
                    '所属作品描述': (post['desc'] or '')[:100],
                    '点赞数': c.get('digg_count', 0),
                    '回复数': reply_total,
                    '评论时间': time.strftime('%Y-%m-%d %H:%M:%S', time.localtime(ct)) if ct else '',
                    '搜索关键词': KEYWORD,
                    '爬取时间': now,
                })
                video_comments += 1
                # Fetch second-level replies for this comment (if any)
                if reply_total and cid:
                    replies = await _fetch_replies(page, aweme_id, cid, user.get('nickname', ''))
                    l2_records.extend(replies)
                    video_replies += len(replies)
                if video_comments >= max_comments:
                    break

            if not data.get('has_more', 0):
                break
            cursor = data.get('cursor', 0)
            await polite_sleep()

        print(f'    Got {video_comments} L1 comments, {video_replies} L2 replies')

    await browser.close()
    await pw.stop()
    return l1_records, l2_records


async def main():
    print('=== Step 1: Search ALL posts (video + image) ===')
    posts = await search_all_posts()
    if not posts:
        print('No posts found!')
        return

    video_posts = [p for p in posts if p['type'] == 'video']
    image_posts = [p for p in posts if p['type'] == 'image']
    print(f'Video posts: {len(video_posts)}, Image posts: {len(image_posts)}')

    print(f'\n=== Step 2: Download media and upload to Feishu ({len(posts)} posts) ===')
    feishu = FeishuBitable(app_token=APP_TOKEN)

    # Clear old records in both tables
    feishu.delete_all_records(VIDEO_TABLE_ID)
    feishu.delete_all_records(IMAGE_TABLE_ID)

    video_records = []
    image_records = []
    for i, post in enumerate(posts):
        print(f'  [{i+1}/{len(posts)}] {post["type"]} - {post["aweme_id"]}')
        tokens = download_and_upload_media(post, feishu)
        record = build_record(post, tokens)
        if post['type'] == 'video':
            video_records.append(record)
        else:
            image_records.append(record)
        cleanup_downloads()

    if video_records:
        written = feishu.write_records(video_records, VIDEO_TABLE_ID)
        print(f'Written {written}/{len(video_records)} video records')
    if image_records:
        written = feishu.write_records(image_records, IMAGE_TABLE_ID)
        print(f'Written {written}/{len(image_records)} image records')
    feishu.close()

    if SKIP_COMMENTS:
        print('\n=== Skipping comments (SKIP_COMMENTS set) ===')
        print('\n=== Done ===')
        print(f'Video records: {len(video_records)}, Image records: {len(image_records)}')
        return

    print(f'\n=== Step 3: Fetch L1 + L2 comments for all {len(posts)} posts ===')
    l1_records, l2_records = await fetch_comments_for_posts(posts)
    print(f'L1 comments: {len(l1_records)}, L2 replies: {len(l2_records)}')

    if l1_records or l2_records:
        print('\n=== Step 4: Write comments to Feishu (separate tables) ===')
        feishu = FeishuBitable(app_token=APP_TOKEN)
        if l1_records:
            feishu.delete_all_records(COMMENT_L1_TABLE_ID)
            w1 = feishu.write_records(l1_records, COMMENT_L1_TABLE_ID)
            print(f'Written {w1} 一级评论 records')
        if l2_records:
            feishu.delete_all_records(COMMENT_L2_TABLE_ID)
            w2 = feishu.write_records(l2_records, COMMENT_L2_TABLE_ID)
            print(f'Written {w2} 二级评论 records')
        feishu.close()

    print('\n=== Done ===')
    print(f'Video records: {len(video_records)}, Image records: {len(image_records)}')
    print(f'L1 comments: {len(l1_records)}, L2 replies: {len(l2_records)}')


if __name__ == '__main__':
    asyncio.run(main())
