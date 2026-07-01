"""scrapers/keyword.py 解析逻辑的单元测试 —— 脱离浏览器。

KeywordScraper 的取数是异步 + 浏览器相关的，但字段解析、计数归一、去重、
从 __INITIAL_STATE__ 兜底提取等纯逻辑都可以直接构造假数据来测。
这里用 KeywordScraper(browser=None)，因为被测方法都不触碰 self.browser。
"""
import pytest

from scrapers.keyword import KeywordScraper, _to_int


@pytest.fixture
def scraper():
    # 被测的解析方法不访问浏览器，传 None 即可。
    return KeywordScraper(browser=None)


# ---------------------------------------------------------------- _to_int
class TestToInt:
    def test_none_is_zero(self):
        assert _to_int(None) == 0

    def test_int_passthrough(self):
        assert _to_int(1200) == 1200

    def test_float_truncates(self):
        assert _to_int(3.9) == 3

    def test_wan_suffix(self):
        # “1.2万” = 12000
        assert _to_int("1.2万") == 12000

    def test_yi_suffix(self):
        # “2亿” = 200000000
        assert _to_int("2亿") == 200000000

    def test_plain_numeric_string(self):
        assert _to_int("3000") == 3000

    def test_strips_thousands_separator(self):
        assert _to_int("1,234") == 1234

    def test_empty_string_is_zero(self):
        assert _to_int("") == 0
        assert _to_int("   ") == 0

    def test_garbage_is_zero(self):
        assert _to_int("abc") == 0
        assert _to_int("赞") == 0

    def test_integer_wan(self):
        assert _to_int("3万") == 30000


# ---------------------------------------------------------------- _note_id
class TestNoteId:
    def test_id_field(self):
        assert KeywordScraper._note_id({"id": "n1"}) == "n1"

    def test_note_id_field(self):
        assert KeywordScraper._note_id({"note_id": "n2"}) == "n2"

    def test_nested_note_card(self):
        assert KeywordScraper._note_id({"noteCard": {"noteId": "n3"}}) == "n3"

    def test_prefers_top_level_id(self):
        item = {"id": "top", "noteCard": {"noteId": "nested"}}
        assert KeywordScraper._note_id(item) == "top"

    def test_missing_returns_empty(self):
        assert KeywordScraper._note_id({}) == ""


# ---------------------------------------------------------------- _items_from_initial_state
class TestItemsFromInitialState:
    def test_raw_value_list(self):
        state = {"search": {"feeds": {"_rawValue": [{"id": "a"}]}}}
        assert KeywordScraper._items_from_initial_state(state) == [{"id": "a"}]

    def test_value_list(self):
        state = {"search": {"feeds": {"value": [{"id": "b"}]}}}
        assert KeywordScraper._items_from_initial_state(state) == [{"id": "b"}]

    def test_feeds_already_a_list(self):
        state = {"search": {"feeds": [{"id": "c"}]}}
        assert KeywordScraper._items_from_initial_state(state) == [{"id": "c"}]

    def test_empty_state_returns_empty_list(self):
        assert KeywordScraper._items_from_initial_state({}) == []
        assert KeywordScraper._items_from_initial_state(None) == []

    def test_no_feeds_key_returns_empty(self):
        # search 存在但无 feeds/_rawValue/value 时应安全返回 []
        assert KeywordScraper._items_from_initial_state({"search": {}}) == []


# ---------------------------------------------------------------- _dedupe_parse
def _make_item(note_id, title="t", liked="0", card_key="noteCard"):
    return {
        "id": note_id,
        card_key: {
            "displayTitle": title,
            "user": {"nickName": "作者", "userId": "u1"},
            "interactInfo": {"likedCount": liked},
        },
    }


class TestDedupeParse:
    def test_basic_parse(self, scraper):
        notes = scraper._dedupe_parse([_make_item("n1", "标题A", "1.2万")], 10)
        assert len(notes) == 1
        assert notes[0].note_id == "n1"
        assert notes[0].title == "标题A"
        assert notes[0].liked_count == 12000

    def test_deduplicates_by_note_id(self, scraper):
        items = [_make_item("dup"), _make_item("dup"), _make_item("n2")]
        notes = scraper._dedupe_parse(items, 10)
        assert [n.note_id for n in notes] == ["dup", "n2"]

    def test_skips_items_without_card(self, scraper):
        # 搜索页里夹带的热搜词/推荐词没有 noteCard，应被跳过
        items = [{"id": "n1"}, _make_item("n2")]
        notes = scraper._dedupe_parse(items, 10)
        assert [n.note_id for n in notes] == ["n2"]

    def test_skips_items_without_note_id(self, scraper):
        bad = {"noteCard": {"displayTitle": "无id"}}
        notes = scraper._dedupe_parse([bad, _make_item("n2")], 10)
        assert [n.note_id for n in notes] == ["n2"]

    def test_respects_max_count(self, scraper):
        items = [_make_item(f"n{i}") for i in range(5)]
        notes = scraper._dedupe_parse(items, 2)
        assert len(notes) == 2

    def test_accepts_snake_case_card_key(self, scraper):
        # note_card（下划线）也应被识别为笔记卡片
        items = [_make_item("n1", card_key="note_card")]
        notes = scraper._dedupe_parse(items, 10)
        assert len(notes) == 1
        assert notes[0].note_id == "n1"


# ---------------------------------------------------------------- _parse_note
class TestParseNote:
    def test_camel_case_fields(self, scraper):
        card = {
            "displayTitle": "护肤心得",
            "desc": "正文",
            "type": "normal",
            "user": {"nickName": "小美", "userId": "u123"},
            "interactInfo": {
                "likedCount": "1.2万",
                "collectedCount": "3000",
                "commentCount": "88",
                "shareCount": "12",
            },
            "cover": {"urlDefault": "http://img/cover.jpg"},
        }
        note = scraper._parse_note("nid", card, "tok")
        assert note.note_id == "nid"
        assert note.title == "护肤心得"
        assert note.author_nickname == "小美"
        assert note.author_user_id == "u123"
        assert note.liked_count == 12000
        assert note.collected_count == 3000
        assert note.comment_count == 88
        assert note.share_count == 12
        assert note.cover_url == "http://img/cover.jpg"

    def test_snake_case_fields(self, scraper):
        card = {
            "display_title": "标题",
            "user": {"nickname": "作者", "user_id": "u9"},
            "interact_info": {
                "liked_count": "500",
                "collected_count": "10",
                "comment_count": "2",
            },
        }
        note = scraper._parse_note("nid", card, "")
        assert note.title == "标题"
        assert note.author_nickname == "作者"
        assert note.author_user_id == "u9"
        assert note.liked_count == 500
        assert note.collected_count == 10
        assert note.comment_count == 2

    def test_note_url_includes_xsec_token(self, scraper):
        note = scraper._parse_note("abc", {}, "TOKEN")
        assert "/explore/abc" in note.note_url
        assert "xsec_token=TOKEN" in note.note_url
        assert note.xsec_token == "TOKEN"

    def test_note_url_without_token(self, scraper):
        note = scraper._parse_note("abc", {}, "")
        assert note.note_url.endswith("/explore/abc")
        assert "xsec_token" not in note.note_url

    def test_xsec_token_falls_back_to_card(self, scraper):
        # 顶层没给 token 时，从 card.xsecToken 兜底
        note = scraper._parse_note("abc", {"xsecToken": "FROM_CARD"}, "")
        assert note.xsec_token == "FROM_CARD"
        assert "xsec_token=FROM_CARD" in note.note_url

    def test_missing_counts_default_zero(self, scraper):
        note = scraper._parse_note("abc", {}, "")
        assert note.liked_count == 0
        assert note.collected_count == 0
        assert note.comment_count == 0
        assert note.share_count == 0

    def test_cover_url_plain_url_key(self, scraper):
        note = scraper._parse_note("abc", {"cover": {"url": "http://img/x.jpg"}}, "")
        assert note.cover_url == "http://img/x.jpg"
