"""Merkl HTTP client — borrow-side incentives DefiLlama misses (spec 2b.A).

Endpoint: api.merkl.xyz/v4/opportunities
Match key (for joining to DefiLlama pools): (chain.name normalized, protocol.id, token.symbol).
"""
import aiohttp


BASE_URL = "https://api.merkl.xyz/v4/opportunities"
DEFAULT_TIMEOUT = aiohttp.ClientTimeout(total=40)
USER_AGENT = "codee/0.1"


class MerklClient:
    def __init__(self, session: aiohttp.ClientSession | None = None):
        self._session = session
        self._owns_session = session is None

    async def __aenter__(self):
        if self._session is None:
            self._session = aiohttp.ClientSession(timeout=DEFAULT_TIMEOUT, headers={"User-Agent": USER_AGENT})
        return self

    async def __aexit__(self, exc_type, exc, tb):
        if self._owns_session and self._session is not None:
            await self._session.close()
            self._session = None

    async def fetch_borrow_opportunities(self, max_pages: int = 5) -> list[dict]:
        """Paginates LIVE BORROW opportunities. items=100 per page."""
        assert self._session is not None
        out: list[dict] = []
        for page in range(max_pages):
            url = f"{BASE_URL}?action=BORROW&status=LIVE&items=100&page={page}"
            async with self._session.get(url) as resp:
                resp.raise_for_status()
                batch = await resp.json()
            if not batch:
                break
            out.extend(batch)
            if len(batch) < 100:
                break
        return out
