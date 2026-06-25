import time
from typing import List

from core.client import DouyinClient
from core.datefilter import DateFilter
from config.settings import DOUYIN_API_BASE, MAX_PAGES, REQUEST_DELAY, DOUYIN_COOKIE
from models.data import VideoInfo, UserInfo


class KeywordScraper:
    """Scrape Douyin search results by keyword using direct HTTP API."""

    def __init__(self, client: DouyinClient = None):
        self.client = client

    async def search_videos(
        self,
        keyword: str,
        max_count: int = 50,
        sort_type: int = 0,
        publish_time=None,
        start_date: str = None,
        end_date: str = None,
    ) -> List[VideoInfo]:
        """Search videos by keyword with optional date/time filtering.

        ``publish_time`` selects a predefined server-side range (0/1/7/182);
        ``start_date`` / ``end_date`` (``YYYY-MM-DD``) apply a client-side
        custom window using each result's ``create_time`` (inclusive of the
        end day). Pagination advances by the raw discovered count, so a page
        whose results are all trimmed by the date filter does not stop the
        crawl — it keeps paging toward older posts.
        """
        date_filter = DateFilter.from_inputs(publish_time, start_date, end_date)
        if date_filter.is_active:
            print(f"[Search] Date filter active: {date_filter.describe()}")

        results: List[VideoInfo] = []
        offset = 0
        count_per_page = 20
        seen_ids = set()
        dropped = 0

        for page in range(MAX_PAGES):
            if len(results) >= max_count:
                break

            params = {
                "device_platform": "webapp",
                "aid": "6383",
                "channel": "channel_pc_web",
                "search_channel": "aweme_video_web",
                "keyword": keyword,
                "search_source": "normal_search",
                "query_correct_type": "1",
                "is_filter_search": "0",
                "from_group_id": "",
                "offset": str(offset),
                "count": str(count_per_page),
                "sort_type": str(sort_type),
                "cookie_enabled": "true",
                "platform": "PC",
                "pc_client_type": "1",
            }
            date_filter.apply_search_params(params)

            data = await self.client.get(
                f"{DOUYIN_API_BASE}/search/item/", params=params
            )
            if not data or data.get("status_code") != 0:
                print(f"[Search] API error on page {page}: status={data.get('status_code')}")
                break

            items = data.get("data", [])
            if not items:
                break

            for item in items:
                aweme = item.get("aweme_info", {})
                if not aweme:
                    continue
                aweme_id = aweme.get("aweme_id", "")
                if aweme_id in seen_ids:
                    continue
                seen_ids.add(aweme_id)
                if not date_filter.matches(aweme.get("create_time", 0)):
                    dropped += 1
                    continue
                results.append(self._parse_video(aweme))
                if len(results) >= max_count:
                    break

            has_more = data.get("has_more", 0)
            if not has_more:
                break
            offset += count_per_page

        if date_filter.has_custom_range:
            print(f"[Search] Dropped {dropped} videos outside the date range")
        print(f"[Search] Found {len(results)} videos for keyword '{keyword}'")
        return results[:max_count]

    async def search_users(
        self, keyword: str, max_count: int = 20
    ) -> List[UserInfo]:
        results: List[UserInfo] = []
        offset = 0
        count_per_page = 10

        for page in range(MAX_PAGES):
            if len(results) >= max_count:
                break

            params = {
                "device_platform": "webapp",
                "aid": "6383",
                "channel": "channel_pc_web",
                "search_channel": "aweme_user_web",
                "keyword": keyword,
                "search_source": "normal_search",
                "query_correct_type": "1",
                "is_filter_search": "0",
                "offset": str(offset),
                "count": str(count_per_page),
                "cookie_enabled": "true",
                "platform": "PC",
                "pc_client_type": "1",
            }

            data = await self.client.get(
                f"{DOUYIN_API_BASE}/search/item/", params=params
            )
            if not data or data.get("status_code") != 0:
                break

            user_list = data.get("user_list", data.get("data", []))
            if not user_list:
                break

            for item in user_list:
                user_info = item.get("user_info", item)
                results.append(self._parse_user(user_info))

            has_more = data.get("has_more", 0)
            if not has_more:
                break
            offset += count_per_page

        print(f"[Search] Found {len(results)} users for keyword '{keyword}'")
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

    def _parse_user(self, user_info: dict) -> UserInfo:
        return UserInfo(
            uid=user_info.get("uid", ""),
            sec_uid=user_info.get("sec_uid", ""),
            nickname=user_info.get("nickname", ""),
            signature=user_info.get("signature", ""),
            follower_count=user_info.get("follower_count", 0),
            following_count=user_info.get("following_count", 0),
            total_favorited=user_info.get("total_favorited", 0),
            aweme_count=user_info.get("aweme_count", 0),
            avatar_url=(
                user_info.get("avatar_thumb", {}).get("url_list", [""])[0]
                if isinstance(user_info.get("avatar_thumb"), dict)
                else ""
            ),
            homepage_url=f"https://www.douyin.com/user/{user_info.get('sec_uid', '')}",
        )
