import asyncio
from typing import List

from core.browser import DouyinBrowser
from config.settings import DOUYIN_API_BASE, REQUEST_DELAY
from models.data import TrendingItem


class TrendingScraper:
    """Scrape Douyin trending/hot search list."""

    def __init__(self, browser: DouyinBrowser):
        self.browser = browser

    async def get_hot_search(self) -> List[TrendingItem]:
        """Get current Douyin hot search list."""
        await self.browser.navigate("https://www.douyin.com")
        await asyncio.sleep(3)

        url = (
            f"{DOUYIN_API_BASE}/hot/search/list/"
            f"?device_platform=webapp"
            f"&aid=6383"
            f"&cookie_enabled=true"
            f"&platform=PC"
        )

        data = await self.browser.fetch_api(url)
        if not data or data.get("status_code") != 0:
            print("[Trending] Failed to get hot search list")
            return []

        results: List[TrendingItem] = []
        word_list = data.get("data", {}).get("word_list", [])

        for i, item in enumerate(word_list):
            trending = TrendingItem(
                rank=i + 1,
                title=item.get("word", ""),
                hot_value=item.get("hot_value", 0),
                label=item.get("label", {}).get("text", "") if isinstance(item.get("label"), dict) else str(item.get("label", "")),
                video_count=item.get("video_count", 0),
            )
            results.append(trending)

        print(f"[Trending] Found {len(results)} hot search items")
        return results
