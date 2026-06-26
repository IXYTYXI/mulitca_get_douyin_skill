"""UI (simulated-click) comment scraper for Douyin video pages.

The raw reply API (`/comment/list/reply/`) is guarded by `bd-ticket-guard` and
returns empty to hand-built requests. But when a logged-in user *clicks*
"展开N条回复", Douyin's own JS issues the request with valid signatures and the
replies render into the DOM. This module drives that flow with Playwright:
scroll to load first-level comments, click every reply expander, then read both
levels straight from the rendered comment-items.

Requires a headed/real browser session with login cookies (see scrape_all).

Stable hooks used (Douyin `data-e2e`):
  [data-e2e="comment-list"]        the comment panel
  [data-e2e="comment-item"]        every comment AND every reply (replies nest
                                   inside their parent comment-item)
  [data-e2e="video-comment-more"]  the "展开N条回复" / "展开更多" expander
"""
import asyncio
import re
from datetime import datetime


def _parse_count(v):
    """Turn a DOM count string ('1', '1.2万', '3w', '') into an int."""
    if isinstance(v, (int, float)):
        return int(v)
    s = str(v).strip()
    m = re.match(r'^([\d.]+)\s*([wW万])?$', s)
    if not m:
        return 0
    num = float(m.group(1))
    if m.group(2):
        num *= 10000
    return int(num)


# JS: parse one comment-item's OWN fields (author / text / time / likes).
# innerText only yields line breaks for ATTACHED nodes, so we read the live
# element's innerText and subtract each nested reply's innerText to isolate the
# item's own content (instead of cloning, which detaches and collapses newlines).
_PARSE_JS = r"""
() => {
  const isReply = (it) => !!(it.parentElement && it.parentElement.closest('[data-e2e="comment-item"]'));
  const ownText = (it) => {
    let full = it.innerText || '';
    it.querySelectorAll('[data-e2e="comment-item"]').forEach(r => {
      const rt = r.innerText || '';
      if (rt && full.includes(rt)) full = full.replace(rt, '');
    });
    return full;
  };
  const authorLink = (it) => {
    for (const a of it.querySelectorAll('a[href*="/user/"]')) {
      if (a.closest('[data-e2e="comment-item"]') !== it) continue;   // skip nested
      if ((a.innerText || '').trim()) return a;                      // the nickname link (not avatar)
    }
    return null;
  };
  const fields = (it) => {
    const a = authorLink(it);
    const author = a ? a.innerText.trim() : '';
    const uhref = a ? (a.getAttribute('href') || '') : '';
    let lines = ownText(it).split('\n').map(s => s.trim()).filter(Boolean);
    lines = lines.filter(l => l !== '...' && !/^展开/.test(l) && l !== '收起');
    const ti = lines.findIndex(l => /(分钟|小时|天|周|月|年)前|·/.test(l));
    let text = '';
    if (ti > 0) {
      const start = (author && lines[0] === author) ? 1 : 0;
      text = lines.slice(start, ti).join(' ');
    } else {
      text = lines.filter(l => l !== author && !['分享','回复'].includes(l)).join(' ');
    }
    const time = ti >= 0 ? lines[ti] : '';
    let likes = 0;
    if (ti >= 0) for (let k = ti + 1; k < lines.length; k++) {
      if (/^\d[\d.]*[wW万]?$/.test(lines[k])) { likes = lines[k]; break; }
    }
    return { author, text, time, likes, uhref };
  };
  const items = [...document.querySelectorAll('[data-e2e="comment-item"]')];
  const out = [];
  let l1 = null;
  for (const it of items) {
    const f = fields(it);
    if (!isReply(it)) { l1 = f; out.push({ level: 1, parent: '', ...f }); }
    else { out.push({ level: 2, parent: l1 ? l1.author : '', ...f }); }
  }
  return out;
};
"""


async def _scroll_comments(page, rounds=20, pause=1.1):
    """Scroll the comment panel's scroll container to load first-level comments."""
    await page.evaluate(r"""() => {
        const item = document.querySelector('[data-e2e="comment-item"]');
        if (!item) return;
        let el = item.parentElement;
        while (el) {
            const s = getComputedStyle(el);
            if ((s.overflowY === 'auto' || s.overflowY === 'scroll') && el.scrollHeight > el.clientHeight + 50) {
                el.setAttribute('data-scrollme', '1'); break;
            }
            el = el.parentElement;
        }
    }""")
    last = 0
    for _ in range(rounds):
        n = await page.evaluate("""() => document.querySelectorAll('[data-e2e="comment-item"]').length""")
        await page.evaluate("""() => { const el = document.querySelector('[data-scrollme]'); if (el) el.scrollTop = el.scrollHeight; }""")
        await asyncio.sleep(pause)
        if n == last:
            # one more nudge; stop if still no growth
            await asyncio.sleep(pause)
            n2 = await page.evaluate("""() => document.querySelectorAll('[data-e2e="comment-item"]').length""")
            if n2 == n:
                break
        last = n


async def _expand_replies(page, max_clicks=150, pause=1.1):
    """Click every '展开N条回复' / '展开更多回复' control to load replies.

    Clicks the exact text element (the handler bubbles); after a click the text
    flips to '收起', so it won't re-match. New '展开更多回复' controls that appear
    for long threads are picked up on subsequent iterations.
    """
    clicks = 0
    while clicks < max_clicks:
        handle = await page.evaluate_handle(r"""() => {
            const els = [...document.querySelectorAll('span,div,a,p')];
            for (const el of els) {
                if (el.getAttribute && el.getAttribute('data-exp-done')) continue;
                const t = (el.innerText || '').trim();
                if ((/^展开\s*\d+\s*条回复$/.test(t) || /^展开更多回复$/.test(t)) && el.offsetParent !== null) {
                    el.setAttribute('data-exp-done', '1');
                    return el;
                }
            }
            return null;
        }""")
        el = handle.as_element()
        if not el:
            break
        try:
            await el.scroll_into_view_if_needed(timeout=4000)
            await el.click(timeout=5000)
            clicks += 1
            await asyncio.sleep(pause)
        except Exception:
            pass
    return clicks


def _to_record(f, aweme_id, keyword, now, level):
    base = {
        '评论内容': f.get('text', ''),
        '评论者昵称': f.get('author', ''),
        '评论者ID': (f.get('uhref', '') or '').rstrip('/').split('/')[-1],
        '评论时间': f.get('time', ''),
        '点赞数': _parse_count(f.get('likes', 0)),
        '所属作品ID': aweme_id,
        '搜索关键词': keyword,
        '爬取时间': now,
    }
    if level == 2:
        # reply target: "@name ..." prefix if present, else the root (L1) author
        txt = f.get('text', '')
        target = f.get('parent', '')
        if txt.startswith('@'):
            target = txt[1:].split(' ')[0].split('：')[0].split(':')[0] or target
        base['父评论ID'] = ''          # DOM does not expose the numeric id
        base['回复对象'] = target       # who this reply is directed at
        base['所属一级评论作者'] = f.get('parent', '')  # the thread's root author
    return base


async def scrape_comments_ui(page, aweme_id, keyword='', desc='',
                             max_l1=60, scroll_rounds=18, expand_clicks=120):
    """Scrape L1 + L2 comments for one video via simulated clicks.

    Returns (l1_records, l2_records). `page` must already be a logged-in page;
    this navigates it to the video and drives the UI.
    """
    await page.goto(f'https://www.douyin.com/video/{aweme_id}',
                    wait_until='domcontentloaded', timeout=40000)
    await asyncio.sleep(6)
    await _scroll_comments(page, rounds=scroll_rounds)
    clicks = await _expand_replies(page, max_clicks=expand_clicks)
    parsed = await page.evaluate(_PARSE_JS)

    now = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    l1, l2 = [], []
    for f in parsed:
        if f['level'] == 1:
            if len(l1) >= max_l1:
                continue
            rec = _to_record(f, aweme_id, keyword, now, 1)
            if desc:
                rec['所属作品描述'] = (desc or '')[:100]
            l1.append(rec)
        else:
            l2.append(_to_record(f, aweme_id, keyword, now, 2))
    print(f'    [UI] {aweme_id}: {len(l1)} L1, {len(l2)} L2 (expander clicks: {clicks})')
    return l1, l2
