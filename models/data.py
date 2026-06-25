from dataclasses import dataclass, field, asdict
from typing import Optional


@dataclass
class VideoInfo:
    aweme_id: str = ""
    desc: str = ""
    author_nickname: str = ""
    author_uid: str = ""
    author_sec_uid: str = ""
    play_count: int = 0
    digg_count: int = 0
    comment_count: int = 0
    share_count: int = 0
    collect_count: int = 0
    create_time: str = ""
    duration: int = 0
    video_url: str = ""
    cover_url: str = ""
    image_urls: str = ""
    post_url: str = ""
    hashtags: str = ""

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class UserInfo:
    uid: str = ""
    sec_uid: str = ""
    nickname: str = ""
    signature: str = ""
    follower_count: int = 0
    following_count: int = 0
    total_favorited: int = 0
    aweme_count: int = 0
    avatar_url: str = ""
    homepage_url: str = ""

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class CommentInfo:
    comment_id: str = ""
    aweme_id: str = ""
    text: str = ""
    user_nickname: str = ""
    user_uid: str = ""
    digg_count: int = 0
    reply_count: int = 0
    create_time: str = ""

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class TrendingItem:
    rank: int = 0
    title: str = ""
    hot_value: int = 0
    label: str = ""
    video_count: int = 0

    def to_dict(self) -> dict:
        return asdict(self)
