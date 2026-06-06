"""DefiLlama HTTP client.

Two endpoints — supply side (apyBase/apyReward) and borrow side (apyBaseBorrow,
ltv, totalSupplyUsd, etc.). JOIN by pool UUID. See spec 2b.A.

Reward APY here is what DefiLlama reports — accurate for supply side, generally
NOT populated for borrow rebates (Merkl fills that gap — see sources/merkl).
"""
import aiohttp


SUPPLY_URL = "https://yields.llama.fi/pools"
BORROW_URL = "https://yields.llama.fi/lendBorrow"
CHART_URL_TMPL = "https://yields.llama.fi/chart/{pool_uuid}"
PROTOCOLS_URL = "https://api.llama.fi/protocols"

DEFAULT_TIMEOUT = aiohttp.ClientTimeout(total=40)
USER_AGENT = "codee/0.1"


class DefiLlamaClient:
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

    async def _get_json(self, url: str):
        assert self._session is not None, "use as async context manager"
        async with self._session.get(url) as resp:
            resp.raise_for_status()
            return await resp.json()

    async def fetch_pools_supply(self) -> list[dict]:
        return (await self._get_json(SUPPLY_URL))["data"]

    async def fetch_pools_borrow(self) -> list[dict]:
        raw = await self._get_json(BORROW_URL)
        return raw if isinstance(raw, list) else raw.get("data", [])

    async def fetch_pool_history(self, pool_uuid: str) -> list[dict]:
        url = CHART_URL_TMPL.format(pool_uuid=pool_uuid)
        payload = await self._get_json(url)
        return payload.get("data", []) if isinstance(payload, dict) else payload

    async def fetch_protocol_categories(self) -> dict[str, str]:
        """{project slug: category} from api.llama.fi/protocols (T2 actionable filter).
        'Lending' category = plain lending platform. Entries lacking slug/category
        are skipped; non-list payloads yield {}."""
        data = await self._get_json(PROTOCOLS_URL)
        if not isinstance(data, list):
            return {}
        return {p["slug"]: p["category"] for p in data
                if isinstance(p, dict) and p.get("slug") and p.get("category")}


def join_supply_borrow(supply: list[dict], borrow: list[dict]) -> list[dict]:
    """Attach borrow-side fields to each supply pool by pool UUID.

    Pools without a borrow record get apyBaseBorrow=None (supply-only, not loopable).
    Borrow records without a supply record are dropped — they have no metadata
    (chain, symbol) and can't be ranked alone.
    """
    borrow_by_pool = {b["pool"]: b for b in borrow if b.get("pool")}
    merged: list[dict] = []
    for p in supply:
        b = borrow_by_pool.get(p.get("pool"))
        merged_pool = dict(p)
        if b is not None:
            merged_pool["apyBaseBorrow"]   = b.get("apyBaseBorrow")
            merged_pool["apyRewardBorrow"] = b.get("apyRewardBorrow")
            merged_pool["ltv"]             = b.get("ltv")
            merged_pool["totalSupplyUsd"]  = b.get("totalSupplyUsd")
            merged_pool["totalBorrowUsd"]  = b.get("totalBorrowUsd")
            merged_pool["debtCeilingUsd"]  = b.get("debtCeilingUsd")
            merged_pool["borrowable"]      = b.get("borrowable")
            merged_pool["borrowFactor"]    = b.get("borrowFactor")
            merged_pool["underlyingTokens"] = b.get("underlyingTokens")
        else:
            merged_pool.setdefault("apyBaseBorrow", None)
            merged_pool.setdefault("apyRewardBorrow", None)
            merged_pool.setdefault("ltv", None)
            merged_pool.setdefault("totalSupplyUsd", None)
            merged_pool.setdefault("totalBorrowUsd", None)
            merged_pool.setdefault("debtCeilingUsd", None)
            merged_pool.setdefault("borrowable", None)
            merged_pool.setdefault("borrowFactor", None)
            merged_pool.setdefault("underlyingTokens", None)
        merged.append(merged_pool)
    return merged
