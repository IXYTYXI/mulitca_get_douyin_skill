"""core/cookies.py 的单元测试 —— 纯字符串/字典处理，无需浏览器。

覆盖 Cookie 解析、登录态判定、诊断文本、以及未登录时的显式报错分支。
"""
import pytest

from core.cookies import (
    parse_cookie_string,
    cookies_list_to_map,
    is_logged_in,
    login_diagnosis,
    require_login,
    NotLoggedInError,
)


# ---------------------------------------------------------------- parse_cookie_string
class TestParseCookieString:
    def test_empty_string_returns_empty_map(self):
        assert parse_cookie_string("") == {}

    def test_none_like_empty(self):
        # 传入空/假值不应崩溃
        assert parse_cookie_string(None) == {}

    def test_basic_pairs(self):
        assert parse_cookie_string("a=1; b=2") == {"a": "1", "b": "2"}

    def test_trims_whitespace_around_name_and_value(self):
        assert parse_cookie_string("  a = 1 ;  b= 2 ") == {"a": "1", "b": "2"}

    def test_value_may_contain_equals_sign(self):
        # web_session 之类的值常含有 '='（base64 padding），只能按第一个 '=' 切分
        jar = parse_cookie_string("web_session=ab==cd; a1=xyz")
        assert jar["web_session"] == "ab==cd"
        assert jar["a1"] == "xyz"

    def test_skips_items_without_equals(self):
        # 形如 "HttpOnly" 这类无值片段应被忽略，而不是产生空 key
        jar = parse_cookie_string("a=1; garbage; b=2")
        assert jar == {"a": "1", "b": "2"}

    def test_skips_empty_name(self):
        jar = parse_cookie_string("=novalue; a=1")
        assert jar == {"a": "1"}

    def test_allows_empty_value(self):
        jar = parse_cookie_string("web_session=; a1=1")
        assert jar["web_session"] == ""
        assert jar["a1"] == "1"

    def test_trailing_semicolon(self):
        assert parse_cookie_string("a=1;") == {"a": "1"}


# ---------------------------------------------------------------- cookies_list_to_map
class TestCookiesListToMap:
    def test_basic_conversion(self):
        cookies = [
            {"name": "web_session", "value": "sess"},
            {"name": "a1", "value": "dev"},
        ]
        assert cookies_list_to_map(cookies) == {"web_session": "sess", "a1": "dev"}

    def test_extra_fields_ignored(self):
        cookies = [{"name": "a1", "value": "v", "domain": ".x.com", "path": "/"}]
        assert cookies_list_to_map(cookies) == {"a1": "v"}

    def test_skips_entries_without_name(self):
        cookies = [{"value": "orphan"}, {"name": "a1", "value": "v"}]
        assert cookies_list_to_map(cookies) == {"a1": "v"}

    def test_missing_value_defaults_to_empty_string(self):
        cookies = [{"name": "web_session"}]
        assert cookies_list_to_map(cookies) == {"web_session": ""}

    def test_empty_list(self):
        assert cookies_list_to_map([]) == {}


# ---------------------------------------------------------------- is_logged_in
class TestIsLoggedIn:
    def test_true_when_web_session_present(self):
        assert is_logged_in({"web_session": "abc"}) is True

    def test_false_when_web_session_missing(self):
        assert is_logged_in({"a1": "dev", "gid": "g"}) is False

    def test_false_when_web_session_empty(self):
        assert is_logged_in({"web_session": ""}) is False

    def test_false_on_empty_jar(self):
        assert is_logged_in({}) is False

    def test_extra_fields_do_not_matter(self):
        assert is_logged_in({"web_session": "x", "junk": ""}) is True


# ---------------------------------------------------------------- login_diagnosis
class TestLoginDiagnosis:
    def test_logged_in_shows_success_marker(self):
        text = login_diagnosis({"web_session": "s", "a1": "d"})
        assert "web_session" in text
        assert "✅" in text

    def test_not_logged_in_shows_missing_field(self):
        text = login_diagnosis({"a1": "d"})
        assert "❌" in text
        assert "web_session" in text

    def test_empty_jar_mentions_no_cookie_parsed(self):
        text = login_diagnosis({})
        assert "未解析到任何 Cookie" in text

    def test_reports_hint_fields_present_and_missing(self):
        text = login_diagnosis({"web_session": "s", "a1": "d"})
        # a1 存在、webId/gid 缺失，诊断里两类都应体现
        assert "a1" in text
        assert "webId" in text or "gid" in text

    def test_non_empty_jar_omits_no_cookie_line(self):
        text = login_diagnosis({"a1": "d"})
        assert "未解析到任何 Cookie" not in text


# ---------------------------------------------------------------- require_login
class TestRequireLogin:
    def test_no_raise_when_logged_in(self):
        # 不应抛出
        require_login({"web_session": "abc"})

    def test_raises_not_logged_in_error(self):
        with pytest.raises(NotLoggedInError):
            require_login({"a1": "dev"})

    def test_error_is_runtime_error_subclass(self):
        assert issubclass(NotLoggedInError, RuntimeError)

    def test_error_message_contains_guidance(self):
        with pytest.raises(NotLoggedInError) as exc_info:
            require_login({})
        msg = str(exc_info.value)
        # 报错必须带可操作指引，且点名关键字段，绝不静默
        assert "web_session" in msg
        assert "xiaohongshu.com" in msg

    def test_empty_web_session_still_raises(self):
        with pytest.raises(NotLoggedInError):
            require_login({"web_session": ""})
