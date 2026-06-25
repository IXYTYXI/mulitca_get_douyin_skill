import asyncio
import httpx
from typing import Optional
from config.settings import DEFAULT_HEADERS, PROXY_URL, REQUEST_DELAY


class DouyinClient:
    """HTTP client wrapper with rate limiting and retry."""

    def __init__(self, cookies: str = ""):
        self._cookies = cookies
        kwargs = {
            "headers": {**DEFAULT_HEADERS, "Cookie": cookies} if cookies else DEFAULT_HEADERS,
            "timeout": 30.0,
            "follow_redirects": True,
        }
        if PROXY_URL:
            kwargs["proxy"] = PROXY_URL
        self._client = httpx.AsyncClient(**kwargs)
        self._delay = REQUEST_DELAY

    def update_cookies(self, cookies: str):
        self._cookies = cookies
        self._client.headers["Cookie"] = cookies

    async def get(self, url: str, params: Optional[dict] = None, retries: int = 3) -> dict:
        for attempt in range(retries):
            try:
                await asyncio.sleep(self._delay)
                resp = await self._client.get(url, params=params)
                resp.raise_for_status()
                return resp.json()
            except (httpx.HTTPError, Exception) as e:
                print(f"[Request error] attempt {attempt + 1}/{retries}: {e}")
                if attempt < retries - 1:
                    await asyncio.sleep(self._delay * (attempt + 1))
        return {}

    async def close(self):
        await self._client.aclose()

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        await self.close()
