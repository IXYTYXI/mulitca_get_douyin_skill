import asyncio
import json
import os
import re
from pathlib import Path
from typing import Optional
from playwright.async_api import async_playwright, Browser, BrowserContext, Page
from config.settings import DOUYIN_BASE_URL, DOUYIN_COOKIE, PROXY_URL


COOKIE_FILE = Path(__file__).resolve().parent.parent / "cookies.json"

STEALTH_JS = """
Object.defineProperty(navigator, 'webdriver', {get: () => undefined});
Object.defineProperty(navigator, 'plugins', {get: () => [1, 2, 3, 4, 5]});
Object.defineProperty(navigator, 'languages', {get: () => ['zh-CN', 'zh', 'en']});
window.chrome = {runtime: {}, loadTimes: function(){}, csi: function(){}};
Object.defineProperty(navigator, 'platform', {get: () => 'Win32'});
const originalQuery = window.navigator.permissions.query;
window.navigator.permissions.query = (parameters) =>
    parameters.name === 'notifications'
        ? Promise.resolve({state: Notification.permission})
        : originalQuery(parameters);
Object.defineProperty(navigator, 'maxTouchPoints', {get: () => 0});
Object.defineProperty(navigator, 'hardwareConcurrency', {get: () => 8});
Object.defineProperty(navigator, 'deviceMemory', {get: () => 8});
const getParameter = WebGLRenderingContext.prototype.getParameter;
WebGLRenderingContext.prototype.getParameter = function(parameter) {
    if (parameter === 37445) return 'Intel Inc.';
    if (parameter === 37446) return 'Intel Iris OpenGL Engine';
    return getParameter.call(this, parameter);
};
"""


class DouyinBrowser:
    """Playwright-based browser manager for Douyin scraping."""

    def __init__(self):
        self._playwright = None
        self._browser: Optional[Browser] = None
        self._context: Optional[BrowserContext] = None
        self._page: Optional[Page] = None

    async def start(self, headless: bool = True):
        self._playwright = await async_playwright().start()
        launch_args = {
            "headless": headless,
            "args": [
                "--disable-blink-features=AutomationControlled",
                "--disable-features=IsolateOrigins,site-per-process",
                "--disable-dev-shm-usage",
                "--no-sandbox",
                "--disable-setuid-sandbox",
                "--disable-accelerated-2d-canvas",
                "--disable-gpu",
            ],
        }
        if PROXY_URL:
            launch_args["proxy"] = {"server": PROXY_URL}
        self._browser = await self._playwright.chromium.launch(**launch_args)
        self._context = await self._browser.new_context(
            viewport={"width": 1920, "height": 1080},
            user_agent=(
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/126.0.0.0 Safari/537.36"
            ),
            locale="zh-CN",
            timezone_id="Asia/Shanghai",
        )
        await self._context.add_init_script(STEALTH_JS)

        # Load saved cookies first (from login command)
        if COOKIE_FILE.exists():
            await self._load_cookies_file()
        elif DOUYIN_COOKIE:
            await self._set_cookies_from_string(DOUYIN_COOKIE)

        self._page = await self._context.new_page()

    async def _set_cookies_from_string(self, cookie_str: str):
        cookies = []
        for item in cookie_str.split(";"):
            item = item.strip()
            if "=" in item:
                name, value = item.split("=", 1)
                cookies.append({
                    "name": name.strip(),
                    "value": value.strip(),
                    "domain": ".douyin.com",
                    "path": "/",
                })
        if cookies:
            await self._context.add_cookies(cookies)

    async def _load_cookies_file(self):
        try:
            with open(COOKIE_FILE, "r", encoding="utf-8") as f:
                cookies = json.load(f)
            await self._context.add_cookies(cookies)
            print(f"[Browser] Loaded {len(cookies)} cookies from {COOKIE_FILE}")
        except Exception as e:
            print(f"[Browser] Failed to load cookies file: {e}")

    async def save_cookies(self):
        cookies = await self._context.cookies()
        with open(COOKIE_FILE, "w", encoding="utf-8") as f:
            json.dump(cookies, f, ensure_ascii=False, indent=2)
        print(f"[Browser] Saved {len(cookies)} cookies to {COOKIE_FILE}")

    async def navigate(self, url: str):
        try:
            await self._page.goto(url, wait_until="domcontentloaded", timeout=60000)
        except Exception:
            pass
        await asyncio.sleep(3)

    async def wait_for_non_captcha(self, timeout: int = 60):
        """Wait until captcha is resolved (for non-headless mode)."""
        for _ in range(timeout):
            content = await self._page.content()
            if "验证" not in content and "captcha" not in content.lower():
                return True
            await asyncio.sleep(1)
        return False

    async def get_cookies_string(self) -> str:
        cookies = await self._context.cookies()
        return "; ".join(f"{c['name']}={c['value']}" for c in cookies)

    async def get_ms_token(self) -> str:
        cookies = await self._context.cookies()
        for c in cookies:
            if c["name"] == "msToken":
                return c["value"]
        return ""

    async def fetch_api(self, url: str) -> dict:
        try:
            response = await self._page.evaluate(
                """async (url) => {
                    const resp = await fetch(url, {
                        headers: {
                            'Accept': 'application/json',
                            'Referer': 'https://www.douyin.com/',
                        },
                        credentials: 'include',
                    });
                    return await resp.json();
                }""",
                url,
            )
            return response
        except Exception as e:
            print(f"[Browser fetch error] {e}")
            return {}

    async def get_page_content(self) -> str:
        return await self._page.content()

    @property
    def page(self) -> Page:
        return self._page

    async def close(self):
        if self._browser:
            await self._browser.close()
        if self._playwright:
            await self._playwright.stop()

    async def __aenter__(self):
        await self.start()
        return self

    async def __aexit__(self, *args):
        await self.close()
