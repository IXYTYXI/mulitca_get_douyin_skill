import time
from typing import List, Optional

from core.client import DouyinClient
from config.settings import DOUYIN_API_BASE, MAX_PAGES, REQUEST_DELAY
from models.data import VideoInfo, UserInfo


class UserScraper:
    """Scrape user profile and videos from author homepage using direct HTTP API."""

    def __init__(self, client: DouyinClient = None):
        self.client = client

    def _extract_sec_uid(self, url: str) -> str:
        import re
        match = re.search(r"/user/([A-Za-z0-9_-]+)", url)
        return match.group(1) if match else ""

    async def get_user_info(self, homepage_url: str) -> Optional[UserInfo]:
        sec_uid = self._extract_sec_uid(homepage_url)
        if not sec_uid:
            print(f"[User] Cannot extract sec_uid from {homepage_url}")
            return None

        params = {
            "sec_user_id": sec_uid,
            "device_platform": "webapp",
            "aid": "6383",
            "cookie_enabled": "true",
            "platform": "PC",
        }

        data = await self.client.get(
            f"{DOUYIN_API_BASE}/user/profile/other/", params=params
        )
        if not data or data.get("status_code") != 0:
            print(f"[User] Failed to get profile for {sec_uid}, status={data.get('status_code')}")
            return None

        user = data.get("user") or {}
        return UserInfo(
            uid=user.get("uid", ""),
            sec_uid=user.get("sec_uid", sec_uid),
            nickname=user.get("nickname", ""),
            signature=user.get("signature", ""),
            follower_count=user.get("follower_count", 0),
            following_count=user.get("following_count", 0),
            total_favorited=user.get("total_favorited", 0),
            aweme_count=user.get("aweme_count", 0),
            avatar_url=(
                user.get("avatar_larger", {}).get("url_list", [""])[0]
                if isinstance(user.get("avatar_larger"), dict)
                else ""
            ),
            homepage_url=f"https://www.douyin.com/user/{sec_uid}",
        )

    async def get_user_videos(
        self, homepage_url: str, max_count: int = 50
    ) -> List[VideoInfo]:
        sec_uid = self._extract_sec_uid(homepage_url)
        if not sec_uid:
            print(f"[User] Cannot extract sec_uid from {homepage_url}")
            return []

        results: List[VideoInfo] = []
        max_cursor = 0
        count_per_page = 20

        for page in range(MAX_PAGES):
            if len(results) >= max_count:
                break

            params = {
                "sec_user_id": sec_uid,
                "count": str(count_per_page),
                "max_cursor": str(max_cursor),
                "device_platform": "webapp",
                "aid": "6383",
                "cookie_enabled": "true",
                "platform": "PC",
            }

            data = await self.client.get(
                f"{DOUYIN_API_BASE}/aweme/post/", params=params
            )
            if not data or data.get("status_code") != 0:
                print(f"[User] API error on page {page}: status={data.get('status_code')}")
                break

            aweme_list = data.get("aweme_list") or []
            if not aweme_list:
                break

            for aweme in aweme_list:
                results.append(self._parse_video(aweme))
                if len(results) >= max_count:
                    break

            has_more = data.get("has_more", 0)
            max_cursor = data.get("max_cursor", 0)
            if not has_more:
                break

        print(f"[User] Collected {len(results)} videos from {homepage_url}")
        return results[:max_count]

    def _parse_video(self, aweme: dict) -> VideoInfo:
        stats = aweme.get("statistics") or {}
        author = aweme.get("author") or {}
        video = aweme.get("video") or {}
        create_ts = aweme.get("create_time", 0)
        create_str = (
            time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(create_ts))
            if create_ts
            else ""
        )

        cover = ""
        if video:
            cover_obj = video.get("cover") or {}
            cover_list = cover_obj.get("url_list") or []
            cover = cover_list[0] if cover_list else ""

        play_url = ""
        play_addr = video.get("play_addr") or {}
        if play_addr:
            url_list = play_addr.get("url_list") or []
            play_url = url_list[0] if url_list else ""

        image_urls = []
        for img in (aweme.get("images") or []):
            if img:
                url_list = img.get("url_list") or []
                if url_list:
                    image_urls.append(url_list[0])

        hashtags = []
        for tag in (aweme.get("text_extra") or []):
            if tag and tag.get("hashtag_name"):
                hashtags.append(tag["hashtag_name"])

        aweme_id = aweme.get("aweme_id", "")

        return VideoInfo(
            aweme_id=aweme_id,
            desc=aweme.get("desc", ""),
            author_nickname=author.get("nickname", ""),
            author_uid=author.get("uid", ""),
            author_sec_uid=author.get("sec_uid", ""),
            play_count=stats.get("play_count", 0),
            digg_count=stats.get("digg_count", 0),
            comment_count=stats.get("comment_count", 0),
            share_count=stats.get("share_count", 0),
            collect_count=stats.get("collect_count", 0),
            create_time=create_str,
            duration=video.get("duration", 0) if video else 0,
            video_url=play_url,
            cover_url=cover,
            image_urls=", ".join(image_urls),
            post_url=f"https://www.douyin.com/video/{aweme_id}" if aweme_id else "",
            hashtags=", ".join(hashtags),
        )
