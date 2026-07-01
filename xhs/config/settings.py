import os
from pathlib import Path

from dotenv import load_dotenv

load_dotenv(Path(__file__).resolve().parent.parent / ".env")


# 小红书登录 Cookie（整条，从浏览器开发者工具复制）
XHS_COOKIE = os.getenv("XHS_COOKIE", "")
PROXY_URL = os.getenv("PROXY_URL", "")

MAX_PAGES = int(os.getenv("MAX_PAGES", "10"))
REQUEST_DELAY = float(os.getenv("REQUEST_DELAY", "2.5"))

XHS_BASE_URL = "https://www.xiaohongshu.com"

# 判定登录态所需的关键 Cookie 字段。
#   web_session : 登录后才会写入，是最主要的“已登录”标志
#   a1 / webId  : 设备指纹，未登录也会有，但缺失说明 Cookie 根本没带全
#   gid         : 会话相关，缺失通常意味着 Cookie 过期
# 只要 web_session 有值即视为已登录；a1/webId/gid 用于给出更精确的诊断。
LOGIN_REQUIRED_FIELDS = ["web_session"]
LOGIN_HINT_FIELDS = ["a1", "webId", "gid"]

DEFAULT_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/126.0.0.0 Safari/537.36"
    ),
    "Referer": "https://www.xiaohongshu.com/",
    "Accept": "application/json, text/plain, */*",
}
