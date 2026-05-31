"""Binance signed client for /sapi/v1/capital/config/getall (withdraw networks per coin).
Credentials come from BI_API_KEY / BI_API_SECRET in the environment — the SAME vars
Volume_tracker uses. Codee does not import VT code; it only reads the shared env. With no
creds, fetch_capital_config() returns [] so the gate degrades gracefully."""
import hashlib
import hmac
import os
import time
from urllib.parse import urlencode

import aiohttp

BASE_URL = "https://api.binance.com"
CONFIG_PATH = "/sapi/v1/capital/config/getall"
DEFAULT_TIMEOUT = aiohttp.ClientTimeout(total=20)


class BinanceClient:
    def __init__(self, api_key: str | None = None, api_secret: str | None = None,
                 session: aiohttp.ClientSession | None = None):
        self.api_key = os.getenv("BI_API_KEY", "") if api_key is None else api_key
        self.api_secret = os.getenv("BI_API_SECRET", "") if api_secret is None else api_secret
        self._session = session
        self._owns_session = session is None

    async def __aenter__(self):
        if self._session is None:
            self._session = aiohttp.ClientSession(timeout=DEFAULT_TIMEOUT)
        return self

    async def __aexit__(self, exc_type, exc, tb):
        if self._owns_session and self._session is not None:
            await self._session.close()
            self._session = None

    def _sign(self, params: dict) -> str:
        qs = urlencode(params)
        sig = hmac.new(self.api_secret.encode(), qs.encode(), hashlib.sha256).hexdigest()
        return f"{qs}&signature={sig}"

    async def fetch_capital_config(self) -> list[dict]:
        """Raw coin list from capital/config/getall; [] if no creds or on error shape."""
        if not self.api_key or not self.api_secret:
            return []
        assert self._session is not None, "use as async context manager"
        query = self._sign({"timestamp": int(time.time() * 1000), "recvWindow": 5000})
        url = f"{BASE_URL}{CONFIG_PATH}?{query}"
        async with self._session.get(url, headers={"X-MBX-APIKEY": self.api_key}) as resp:
            resp.raise_for_status()
            data = await resp.json()
            return data if isinstance(data, list) else []
