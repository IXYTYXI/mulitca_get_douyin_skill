"""小红书 Cookie 解析与登录态校验。

与浏览器无关，纯字符串/字典处理，方便单元测试与在真正打开浏览器之前
就给出明确的报错提示（而不是静默返回空结果）。
"""
from typing import Dict, List

from config.settings import LOGIN_REQUIRED_FIELDS, LOGIN_HINT_FIELDS


def parse_cookie_string(cookie_str: str) -> Dict[str, str]:
    """把浏览器复制出来的整条 Cookie 字符串解析成 {name: value}。"""
    jar: Dict[str, str] = {}
    if not cookie_str:
        return jar
    for item in cookie_str.split(";"):
        item = item.strip()
        if not item or "=" not in item:
            continue
        name, value = item.split("=", 1)
        name = name.strip()
        if name:
            jar[name] = value.strip()
    return jar


def cookies_list_to_map(cookies: List[dict]) -> Dict[str, str]:
    """把 Playwright / cookies.json 的 [{name,value,...}] 转成 {name: value}。"""
    return {c.get("name", ""): c.get("value", "") for c in cookies if c.get("name")}


def is_logged_in(jar: Dict[str, str]) -> bool:
    """只要所有必需字段（默认 web_session）都有非空值即视为已登录。"""
    return all(len(jar.get(f, "")) > 0 for f in LOGIN_REQUIRED_FIELDS)


def login_diagnosis(jar: Dict[str, str]) -> str:
    """返回一段人类可读的登录态诊断信息，用于报错提示。"""
    present = [f for f in LOGIN_REQUIRED_FIELDS if jar.get(f)]
    missing = [f for f in LOGIN_REQUIRED_FIELDS if not jar.get(f)]
    hint_present = [f for f in LOGIN_HINT_FIELDS if jar.get(f)]
    hint_missing = [f for f in LOGIN_HINT_FIELDS if not jar.get(f)]

    lines = []
    if is_logged_in(jar):
        lines.append(f"✅ 检测到登录态字段: {', '.join(present)}")
    else:
        lines.append(f"❌ 缺少登录态关键字段: {', '.join(missing) or '(无)'}")
    lines.append(
        f"   辅助字段 存在: {', '.join(hint_present) or '(无)'} | "
        f"缺失: {', '.join(hint_missing) or '(无)'}"
    )
    if not jar:
        lines.append("   当前未解析到任何 Cookie —— 请检查 XHS_COOKIE / cookies.json 是否为空。")
    return "\n".join(lines)


def require_login(jar: Dict[str, str]) -> None:
    """未登录时抛出带指引的异常，绝不静默继续。"""
    if is_logged_in(jar):
        return
    raise NotLoggedInError(
        "小红书未登录或 Cookie 已过期。\n"
        + login_diagnosis(jar)
        + "\n\n请按以下步骤重新获取整条 Cookie：\n"
        "  1. Chrome 打开 https://www.xiaohongshu.com 并扫码登录\n"
        "  2. F12 打开开发者工具 → Network(网络) 面板\n"
        "  3. 刷新页面，点任意一条 xiaohongshu.com 的请求\n"
        "  4. 在 Request Headers 里找到 Cookie:，复制整行的值\n"
        "  5. 粘贴到 .env 的 XHS_COOKIE=  （或运行 python main.py login 自动保存）\n"
        "关键字段必须包含 web_session（登录后才会写入）。"
    )


class NotLoggedInError(RuntimeError):
    """Cookie 缺失或过期、无法确认登录态时抛出。"""
