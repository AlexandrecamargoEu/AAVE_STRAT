"""ACI (Aave Chan Initiative) Merit feed — Aave's OFF-protocol supply incentives
(Merit + Self) that DefiLlama, Merkl and the on-chain RewardsController all miss.
Free public endpoint, no key. Example: Celo WETH = Merit 2.08% + Self 2.08%
(+ protocol 0.02% = the 4.22% the Aave UI shows)."""
import aiohttp

MERIT_URL = "https://apps.aavechan.com/api/merit/aprs"
DEFAULT_TIMEOUT = aiohttp.ClientTimeout(total=20)
USER_AGENT = "codee/0.1"


class AciClient:
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

    async def fetch_merit_aprs(self) -> dict:
        """Raw payload from /api/merit/aprs; {} on non-dict response."""
        assert self._session is not None, "use as async context manager"
        async with self._session.get(MERIT_URL) as resp:
            resp.raise_for_status()
            data = await resp.json()
            return data if isinstance(data, dict) else {}
