import asyncio
from typing import Dict, List
from urllib.parse import quote

from config.settings import MAX_PAGES, XHS_BASE_URL
from core.browser import XhsBrowser
from core.cookies import require_login
from models.data import NoteInfo


def _to_int(value) -> int:
    """小红书的计数常见形如 '1.2万' / '3000' / 1200，统一转成整数。"""
    if value is None:
        return 0
    if isinstance(value, (int, float)):
        return int(value)
    s = str(value).strip().replace(",", "")
    if not s:
        return 0
    try:
        if s.endswith("万"):
            return int(float(s[:-1]) * 10000)
        if s.endswith("亿"):
            return int(float(s[:-1]) * 100000000)
        return int(float(s))
    except ValueError:
        return 0


class KeywordScraper:
    """按关键词搜索小红书笔记。

    走真实浏览器渲染 + 拦截官方搜索接口响应的方式取数，无需手写签名。
    """

    SEARCH_API_MARK = "/api/sns/web/v1/search/notes"

    def __init__(self, browser: XhsBrowser):
        self.browser = browser
        self._captured: List[dict] = []

    async def _on_response(self, response):
        if self.SEARCH_API_MARK not in response.url:
            return
        try:
            data = await response.json()
        except Exception:
            return
        items = (data or {}).get("data", {}).get("items", [])
        if items:
            self._captured.extend(items)

    async def search_notes(self, keyword: str, max_count: int = 50) -> List[NoteInfo]:
        # 取数前先确认登录态；未登录直接抛带指引的异常，绝不静默返回空。
        require_login(await self.browser.cookie_map())

        page = self.browser.page
        page.on("response", self._on_response)

        url = (
            f"{XHS_BASE_URL}/search_result?keyword={quote(keyword)}"
            f"&source=web_explore_feed&type=51"
        )
        await self.browser.navigate(url, wait=4.0)

        if await self.browser.is_captcha():
            print("[Search] 命中验证码/风控页。请用 --no-headless 打开可见浏览器手动过验证，"
                  "或稍后重试、降低频率(增大 REQUEST_DELAY)。")

        # 滚动翻页加载更多；每页由官方 XHR 返回，_on_response 负责收集。
        for _ in range(MAX_PAGES):
            if self._unique_count() >= max_count:
                break
            before = len(self._captured)
            await self.browser.scroll(times=1, pause=2.0)
            if len(self._captured) == before:
                # 连续一次滚动没有新数据，认为到底了。
                break

        # 兜底：接口一条都没拦到时，从页面初始状态里捞。
        raw_items = self._captured
        if not raw_items:
            raw_items = self._items_from_initial_state(await self.browser.get_initial_state())

        notes = self._dedupe_parse(raw_items, max_count)
        print(f"[Search] Found {len(notes)} notes for keyword '{keyword}'")
        if not notes:
            print("[Search] 未取到任何笔记。常见原因：Cookie 过期 / 命中验证码 / 关键词无结果。"
                  "先运行 `python main.py check` 确认登录态。")
        return notes

    def _unique_count(self) -> int:
        return len({self._note_id(i) for i in self._captured if self._note_id(i)})

    @staticmethod
    def _items_from_initial_state(state: dict) -> List[dict]:
        search = (state or {}).get("search", {})
        feeds = search.get("feeds", search)
        if isinstance(feeds, dict):
            feeds = feeds.get("_rawValue") or feeds.get("value") or []
        return feeds if isinstance(feeds, list) else []

    @staticmethod
    def _note_id(item: dict) -> str:
        return item.get("id") or item.get("note_id") or (item.get("noteCard") or {}).get("noteId", "")

    def _dedupe_parse(self, items: List[dict], max_count: int) -> List[NoteInfo]:
        results: List[NoteInfo] = []
        seen = set()
        for item in items:
            note_id = self._note_id(item)
            card = item.get("noteCard") or item.get("note_card") or {}
            # 只要笔记卡片（跳过搜索页里的推荐词/热搜等非笔记 item）
            if not card or not note_id or note_id in seen:
                continue
            seen.add(note_id)
            results.append(self._parse_note(note_id, card, item.get("xsecToken", "")))
            if len(results) >= max_count:
                break
        return results

    def _parse_note(self, note_id: str, card: dict, xsec_token: str) -> NoteInfo:
        user = card.get("user") or {}
        interact = card.get("interactInfo") or card.get("interact_info") or {}
        cover = card.get("cover") or {}
        cover_url = ""
        if isinstance(cover, dict):
            cover_url = cover.get("urlDefault") or cover.get("url") or ""
        xsec_token = xsec_token or card.get("xsecToken", "")

        note_url = f"{XHS_BASE_URL}/explore/{note_id}"
        if xsec_token:
            note_url += f"?xsec_token={xsec_token}&xsec_source=pc_search"

        return NoteInfo(
            note_id=note_id,
            title=card.get("displayTitle") or card.get("display_title") or "",
            desc=card.get("desc", ""),
            note_type=card.get("type", ""),
            author_nickname=user.get("nickName") or user.get("nickname", ""),
            author_user_id=user.get("userId") or user.get("user_id", ""),
            liked_count=_to_int(interact.get("likedCount") or interact.get("liked_count")),
            collected_count=_to_int(interact.get("collectedCount") or interact.get("collected_count")),
            comment_count=_to_int(interact.get("commentCount") or interact.get("comment_count")),
            share_count=_to_int(interact.get("shareCount") or interact.get("share_count")),
            cover_url=cover_url,
            note_url=note_url,
            xsec_token=xsec_token,
        )
