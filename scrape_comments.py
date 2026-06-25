"""Scrape first-level comments for videos and write to Feishu comment table."""
import sys
sys.stdout.reconfigure(errors='replace')
import builtins
_original_print = builtins.print
def print(*args, **kwargs):
    kwargs.setdefault('flush', True)
    _original_print(*args, **kwargs)

import asyncio
import json
import time
from datetime import datetime
from playwright.async_api import async_playwright
from config.settings import DOUYIN_COOKIE, DOUYIN_API_BASE, REQUEST_DELAY
from core.client import DouyinClient
from storage.feishu import FeishuBitable

COMMENT_TABLE_ID = "tbl0U4TqhwWIuYDK"
KEYWORD = "拍照搜题"

STEALTH_JS = """
Object.defineProperty(navigator, 'webdriver', {get: () => undefined});
Object.defineProperty(navigator, 'plugins', {get: () => [1, 2, 3, 4, 5]});
Object.defineProperty(navigator, 'languages', {get: () => ['zh-CN', 'zh', 'en']});
window.chrome = {runtime: {}, loadTimes: function(){}, csi: function(){}};
Object.defineProperty(navigator, 'platform', {get: () => 'Win32'});
"""


async def fetch_comments_from_page(page, aweme_id, cursor=0, count=20):
    url = (
        f"{DOUYIN_API_BASE}/comment/list/"
        f"?aweme_id={aweme_id}"
        f"&cursor={cursor}&count={count}"
        f"&item_type=0"
        f"&device_platform=webapp&aid=6383"
        f"&cookie_enabled=true&platform=PC"
    )
    try:
        result = await asyncio.wait_for(
            page.evaluate(
                """async (url) => {
                    const resp = await fetch(url, {
                        headers: {'Accept': 'application/json', 'Referer': 'https://www.douyin.com/'},
                        credentials: 'include',
                    });
                    return await resp.json();
                }""",
                url,
            ),
            timeout=30,
        )
        return result
    except asyncio.TimeoutError:
        print(f"  Comment fetch timed out for cursor={cursor}")
        return {}
    except Exception as e:
        print(f"  Comment fetch error: {e}")
        return {}


def format_time(ts):
    if not ts:
        return ""
    return time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(ts))


def comment_to_record(c, aweme_id, video_desc):
    user = c.get("user", {})
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    reply_total = c.get("reply_comment_total", 0)
    record = {
        "评论内容": c.get("text", ""),
        "评论者昵称": user.get("nickname", ""),
        "评论者ID": user.get("uid", ""),
        "评论层级": "一级评论",
        "所属视频ID": aweme_id,
        "所属视频描述": (video_desc or "")[:100],
        "点赞数": c.get("digg_count", 0),
        "回复数": reply_total,
        "评论时间": format_time(c.get("create_time", 0)),
        "搜索关键词": KEYWORD,
        "爬取时间": now,
    }
    return record


async def get_video_list():
    async with DouyinClient(cookies=DOUYIN_COOKIE) as client:
        all_videos = []
        seen_ids = set()
        for offset in range(0, 60, 20):
            params = {
                "keyword": KEYWORD,
                "search_channel": "aweme_video_web",
                "sort_type": 0,
                "count": 20,
                "offset": offset,
                "search_source": "normal_search",
                "cookie_enabled": "true",
                "device_platform": "webapp",
                "aid": "6383",
                "platform": "PC",
            }
            data = await client.get(f"{DOUYIN_API_BASE}/search/item/", params=params)
            items = data.get("data", [])
            if not items:
                break
            for item in items:
                aweme = item.get("aweme_info", {})
                aid = aweme.get("aweme_id", "")
                if aid and aid not in seen_ids:
                    seen_ids.add(aid)
                    stats = aweme.get("statistics", {})
                    digg = stats.get("digg_count", 0)
                    comment_ct = stats.get("comment_count", 0)
                    collect = stats.get("collect_count", 0)
                    if digg > 50 or comment_ct > 50 or collect > 50:
                        all_videos.append({
                            "aweme_id": aid,
                            "desc": aweme.get("desc", ""),
                            "comment_count": comment_ct,
                        })
            await asyncio.sleep(REQUEST_DELAY)
        return all_videos


async def scrape_all_comments(videos):
    pw = await async_playwright().start()
    browser = await pw.chromium.launch(
        headless=True,
        args=["--disable-blink-features=AutomationControlled", "--no-sandbox"],
    )
    context = await browser.new_context(
        viewport={"width": 1920, "height": 1080},
        user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36",
        locale="zh-CN",
        timezone_id="Asia/Shanghai",
    )
    await context.add_init_script(STEALTH_JS)

    cookies = []
    for item in DOUYIN_COOKIE.split(";"):
        item = item.strip()
        if "=" in item:
            name, value = item.split("=", 1)
            cookies.append({"name": name.strip(), "value": value.strip(), "domain": ".douyin.com", "path": "/"})
    await context.add_cookies(cookies)

    page = await context.new_page()
    all_records = []

    for vi, video in enumerate(videos):
        aweme_id = video["aweme_id"]
        desc = video["desc"]
        comment_count = video["comment_count"]
        print(f"\n[{vi+1}/{len(videos)}] Video {aweme_id} (expected comments: {comment_count})")

        try:
            await page.goto(
                f"https://www.douyin.com/video/{aweme_id}",
                wait_until="domcontentloaded",
                timeout=30000,
            )
        except Exception:
            pass
        await asyncio.sleep(4)

        cursor = 0
        video_comments = 0
        max_comments = min(comment_count, 100)

        while video_comments < max_comments:
            data = await fetch_comments_from_page(page, aweme_id, cursor=cursor, count=20)
            if not data or data.get("status_code") != 0:
                break

            comments = data.get("comments", [])
            if not comments:
                break

            for c in comments:
                record = comment_to_record(c, aweme_id, desc)
                all_records.append(record)
                video_comments += 1
                if video_comments >= max_comments:
                    break

            if not data.get("has_more", 0):
                break
            cursor = data.get("cursor", 0)
            await asyncio.sleep(REQUEST_DELAY)

        print(f"  Collected {video_comments} comments (total: {len(all_records)})")

    await browser.close()
    await pw.stop()
    return all_records


async def main():
    print("=== Step 1: Getting video list ===")
    videos = await get_video_list()
    print(f"Found {len(videos)} videos with >50 likes/comments/bookmarks")

    if not videos:
        print("No videos found!")
        return 0

    print(f"\n=== Step 2: Scraping comments for {len(videos)} videos ===")
    records = await scrape_all_comments(videos)
    print(f"\nTotal comment records: {len(records)}")

    written = 0
    if records:
        print("\n=== Step 3: Writing to Feishu ===")
        feishu = FeishuBitable()
        feishu.delete_all_records(COMMENT_TABLE_ID)
        written = feishu.write_records(records, COMMENT_TABLE_ID)
        print(f"Written {written} comment records to Feishu")
        feishu.close()

    print("\n=== Step 4: Deleting unused tables ===")
    feishu = FeishuBitable()
    tables_to_delete = ["tblkhsmPGDuWCKXo", "tblkR0Fb2XCqFXvR", "tblQiOhERrNQSSem", "tblj81gSa4kyXBLJ"]
    for tid in tables_to_delete:
        url = f"https://open.feishu.cn/open-apis/bitable/v1/apps/{feishu.app_token}/tables/{tid}"
        resp = feishu._client.delete(url, headers=feishu._headers())
        data = resp.json()
        if data.get("code") == 0:
            print(f"  Deleted table {tid}")
        else:
            print(f"  Delete {tid}: {data.get('msg', 'error')}")
    feishu.close()

    print("\n=== Done ===")
    return written


if __name__ == "__main__":
    result = asyncio.run(main())
