import asyncio
import json
from pathlib import Path
from typing import Dict, List, Optional

from playwright.async_api import async_playwright, Browser, BrowserContext, Page

from config.settings import XHS_BASE_URL, XHS_COOKIE, PROXY_URL
from core.cookies import (
    parse_cookie_string,
    cookies_list_to_map,
    is_logged_in,
    login_diagnosis,
)

COOKIE_FILE = Path(__file__).resolve().parent.parent / "cookies.json"

# 与抖音爬虫一致的反自动化检测脚本，降低被风控/验证码拦截的概率。
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

USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/126.0.0.0 Safari/537.36"
)


class XhsBrowser:
    """基于 Playwright 的小红书浏览器管理器。

    采用“真实浏览器渲染”的抓取路径：登录 Cookie 注入后，直接导航到小红书
    页面，由页面自身完成 x-s / x-t 等签名与数据请求，我们再从渲染结果里读取
    数据。这样无需手写签名算法，稳定且验证码更少（见 README“签名机制”）。
    """

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
                "--disable-gpu",
            ],
        }
        if PROXY_URL:
            launch_args["proxy"] = {"server": PROXY_URL}
        self._browser = await self._playwright.chromium.launch(**launch_args)
        self._context = await self._browser.new_context(
            viewport={"width": 1920, "height": 1080},
            user_agent=USER_AGENT,
            locale="zh-CN",
            timezone_id="Asia/Shanghai",
        )
        await self._context.add_init_script(STEALTH_JS)

        # Cookie 优先级：cookies.json（login 命令保存）> .env 的 XHS_COOKIE
        if COOKIE_FILE.exists():
            await self._load_cookies_file()
        elif XHS_COOKIE:
            await self._set_cookies_from_string(XHS_COOKIE)

        self._page = await self._context.new_page()

    async def _set_cookies_from_string(self, cookie_str: str):
        cookies = []
        for name, value in parse_cookie_string(cookie_str).items():
            cookies.append({
                "name": name,
                "value": value,
                "domain": ".xiaohongshu.com",
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

    async def cookie_map(self) -> Dict[str, str]:
        cookies = await self._context.cookies()
        return cookies_list_to_map(cookies)

    async def verify_login(self) -> bool:
        """打印登录诊断，返回是否已登录。"""
        jar = await self.cookie_map()
        print(login_diagnosis(jar))
        return is_logged_in(jar)

    async def navigate(self, url: str, wait: float = 3.0):
        try:
            await self._page.goto(url, wait_until="domcontentloaded", timeout=60000)
        except Exception:
            pass
        await asyncio.sleep(wait)

    async def is_captcha(self) -> bool:
        try:
            content = await self._page.content()
        except Exception:
            return False
        markers = ["验证码", "captcha", "滑动验证", "点击验证", "verify"]
        low = content.lower()
        return any(m in content or m in low for m in markers)

    async def get_initial_state(self) -> dict:
        """读取小红书页面注入的 window.__INITIAL_STATE__（含搜索/详情数据）。"""
        try:
            return await self._page.evaluate(
                "() => window.__INITIAL_STATE__ || {}"
            )
        except Exception as e:
            print(f"[Browser] read __INITIAL_STATE__ failed: {e}")
            return {}

    async def scroll(self, times: int = 1, pause: float = 1.5):
        for _ in range(times):
            try:
                await self._page.mouse.wheel(0, 3000)
            except Exception:
                pass
            await asyncio.sleep(pause)

    @property
    def page(self) -> Page:
        return self._page

    async def close(self):
        if self._browser:
            await self._browser.close()
        if self._playwright:
            await self._playwright.stop()

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        await self.close()
