import os
from pathlib import Path
from dotenv import load_dotenv

load_dotenv(Path(__file__).resolve().parent.parent / ".env")


FEISHU_APP_ID = os.getenv("FEISHU_APP_ID", "")
FEISHU_APP_SECRET = os.getenv("FEISHU_APP_SECRET", "")
FEISHU_APP_TOKEN = os.getenv("FEISHU_APP_TOKEN", "")
FEISHU_TABLE_ID = os.getenv("FEISHU_TABLE_ID", "")

DOUYIN_COOKIE = os.getenv("DOUYIN_COOKIE", "")
PROXY_URL = os.getenv("PROXY_URL", "")

MAX_PAGES = int(os.getenv("MAX_PAGES", "10"))
REQUEST_DELAY = float(os.getenv("REQUEST_DELAY", "2"))

DOUYIN_BASE_URL = "https://www.douyin.com"
DOUYIN_API_BASE = "https://www.douyin.com/aweme/v1/web"

DEFAULT_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/126.0.0.0 Safari/537.36"
    ),
    "Referer": "https://www.douyin.com/",
    "Accept": "application/json, text/plain, */*",
}

FEISHU_API_BASE = "https://open.feishu.cn/open-apis"
