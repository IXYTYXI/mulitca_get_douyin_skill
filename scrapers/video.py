import asyncio
import time
from typing import List

from core.browser import DouyinBrowser
from config.settings import DOUYIN_API_BASE, MAX_PAGES, REQUEST_DELAY
from models.data import VideoInfo, CommentInfo


class VideoScraper:
    """Scrape video details and comments."""

    def __init__(self, browser: DouyinBrowser):
        self.browser = browser

    async def get_video_detail(self, aweme_id: str) -> dict:
        """Get full details for a single video."""
        url = (
            f"{DOUYIN_API_BASE}/aweme/detail/"
            f"?aweme_id={aweme_id}"
            f"&device_platform=webapp"
            f"&aid=6383"
            f"&cookie_enabled=true"
            f"&platform=PC"
        )

        await self.browser.navigate(f"https://www.douyin.com/video/{aweme_id}")
        await asyncio.sleep(3)

        data = await self.browser.fetch_api(url)
        if not data or data.get("status_code") != 0:
            print(f"[Video] Failed to get detail for {aweme_id}")
            return {}

        return data.get("aweme_detail", {})

    async def get_comments(
        self, aweme_id: str, max_count: int = 100
    ) -> List[CommentInfo]:
        """Get comments for a video."""
        results: List[CommentInfo] = []
        cursor = 0
        count_per_page = 20
        page_num = 0

        if not self.browser.page.url.endswith(f"/video/{aweme_id}"):
            await self.browser.navigate(f"https://www.douyin.com/video/{aweme_id}")
            await asyncio.sleep(3)

        while len(results) < max_count and page_num < MAX_PAGES:
            url = (
                f"{DOUYIN_API_BASE}/comment/list/"
                f"?aweme_id={aweme_id}"
                f"&cursor={cursor}"
                f"&count={count_per_page}"
                f"&device_platform=webapp"
                f"&aid=6383"
                f"&cookie_enabled=true"
                f"&platform=PC"
            )

            data = await self.browser.fetch_api(url)
            if not data or data.get("status_code") != 0:
                break

            comments = data.get("comments", [])
            if not comments:
                break

            for c in comments:
                comment = self._parse_comment(c, aweme_id)
                results.append(comment)
                if len(results) >= max_count:
                    break

            has_more = data.get("has_more", 0)
            cursor = data.get("cursor", 0)
            if not has_more:
                break

            page_num += 1
            await asyncio.sleep(REQUEST_DELAY)

        print(f"[Video] Collected {len(results)} comments for video {aweme_id}")
        return results

    def _parse_comment(self, c: dict, aweme_id: str) -> CommentInfo:
        user = c.get("user", {})
        create_ts = c.get("create_time", 0)
        create_str = (
            time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(create_ts))
            if create_ts
            else ""
        )
        return CommentInfo(
            comment_id=c.get("cid", ""),
            aweme_id=aweme_id,
            text=c.get("text", ""),
            user_nickname=user.get("nickname", ""),
            user_uid=user.get("uid", ""),
            digg_count=c.get("digg_count", 0),
            reply_count=c.get("reply_comment_total", 0),
            create_time=create_str,
        )
