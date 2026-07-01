from dataclasses import dataclass, asdict


@dataclass
class NoteInfo:
    """一条小红书笔记的基本字段。"""
    note_id: str = ""
    title: str = ""
    desc: str = ""
    note_type: str = ""          # normal(图文) / video
    author_nickname: str = ""
    author_user_id: str = ""
    liked_count: int = 0
    collected_count: int = 0
    comment_count: int = 0
    share_count: int = 0
    cover_url: str = ""
    note_url: str = ""
    xsec_token: str = ""

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class UserInfo:
    user_id: str = ""
    nickname: str = ""
    desc: str = ""
    red_id: str = ""
    fans: int = 0
    follows: int = 0
    note_count: int = 0
    avatar_url: str = ""
    homepage_url: str = ""

    def to_dict(self) -> dict:
        return asdict(self)
