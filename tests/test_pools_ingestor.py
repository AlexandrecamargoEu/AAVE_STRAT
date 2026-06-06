import pytest

from db.sqlite_client import SqliteClient
from services.pools.ingestor import PoolsIngestor


class StubDefiLlama:
    categories: dict = {}
    def __init__(self, supply, borrow):
        self.supply, self.borrow = supply, borrow
    async def __aenter__(self): return self
    async def __aexit__(self, *a): pass
    async def fetch_pools_supply(self): return self.supply
    async def fetch_pools_borrow(self): return self.borrow
    async def fetch_protocol_categories(self): return self.categories


class StubMerkl:
    def __init__(self, opps): self.opps = opps
    async def __aenter__(self): return self
    async def __aexit__(self, *a): pass
    async def fetch_borrow_opportunities(self, max_pages=5): return self.opps
    async def fetch_supply_opportunities(self, max_pages=5): return []


@pytest.fixture
async def db(tmp_path):
    c = SqliteClient(db_path=str(tmp_path / "ing.db"))
    await c.connect()
    await c.apply_migrations()
    yield c
    await c.close()


def _supply_pool(uuid, chain, project, symbol, base=3.0, reward=0.0, tvl=10e6):
    return {
        "pool": uuid, "chain": chain, "project": project, "symbol": symbol,
        "apyBase": base, "apyReward": reward, "tvlUsd": tvl,
    }


def _borrow_pool(uuid, base=4.0, rebate=None, ltv=0.75, tsu=10e6, tbu=5e6):
    return {
        "pool": uuid, "apyBaseBorrow": base, "apyRewardBorrow": rebate,
        "ltv": ltv, "totalSupplyUsd": tsu, "totalBorrowUsd": tbu,
    }


def _merkl_opp(chain, proto, symbol, apr):
    return {
        "chain": {"name": chain}, "protocol": {"id": proto},
        "tokens": [{"symbol": symbol}], "action": "BORROW", "apr": apr,
    }


async def test_ingestor_full_pipeline_persists_filtered_pools(db):
    supply = [
        _supply_pool("u1", "BSC", "aave-v3", "USDC", base=2.6),
        _supply_pool("u2", "BSC", "aave-v3", "USDT", base=2.4),
        # $500k — above the new $10k dust floor, now KEPT
        _supply_pool("u3", "BSC", "aave-v3", "DAI", tvl=500_000),
        # non-stable -> filtered
        _supply_pool("u4", "BSC", "aave-v3", "WBNB"),
        # sub-$10k dust pool -> filtered
        _supply_pool("u5", "BSC", "aave-v3", "TUSD", tvl=5_000),
    ]
    borrow = [
        _borrow_pool("u1"), _borrow_pool("u2"), _borrow_pool("u3"),
        _borrow_pool("u4"), _borrow_pool("u5"),
    ]
    merkl = [_merkl_opp("Mantle", "aave", "USDC", 1.37)]  # won't match BSC pools

    ing = PoolsIngestor(db, StubDefiLlama(supply, borrow), StubMerkl(merkl))
    n = await ing.run_once(ts=1716800000)

    assert n == 3  # u1 + u2 + u3; u4 (not stable) and u5 (TVL < $10k dust) filtered
    rows = await db.fetch_all("SELECT pool_id, symbol FROM pools_snapshot ORDER BY pool_id")
    assert rows == [("u1", "USDC"), ("u2", "USDT"), ("u3", "DAI")]


async def test_ingestor_overlays_merkl_borrow_rebate(db):
    supply = [_supply_pool("m1", "Mantle", "aave-v3", "USDC", base=2.2)]
    borrow = [_borrow_pool("m1", base=3.31, rebate=None)]
    merkl = [_merkl_opp("Mantle", "aave", "USDC", 1.37)]

    ing = PoolsIngestor(db, StubDefiLlama(supply, borrow), StubMerkl(merkl))
    await ing.run_once(ts=1716800000)
    row = await db.fetch_one(
        "SELECT borrow_apr_base, borrow_apr_reward, reward_source FROM pools_snapshot WHERE pool_id=?",
        ("m1",),
    )
    base, rebate, src = row
    assert base == pytest.approx(3.31)
    assert rebate == pytest.approx(1.37)
    # Merkl provided the rebate -> reward_source records 'merkl' (not the defillama default)
    assert src == "merkl"


async def test_ingestor_flags_high_utilization(db):
    """spec 2b.B + 2b.J: util > 92% -> quality_flag = high_utilization."""
    supply = [_supply_pool("hu", "BSC", "aave-v3", "USDC")]
    borrow = [_borrow_pool("hu", tsu=10e6, tbu=9.5e6)]  # 95% util
    ing = PoolsIngestor(db, StubDefiLlama(supply, borrow), StubMerkl([]))
    await ing.run_once(ts=1716800000)
    flag = await db.fetch_one("SELECT quality_flag FROM pools_snapshot WHERE pool_id=?", ("hu",))
    assert flag == ("high_utilization",)


async def test_ingestor_keeps_tether_glyph_symbol(db):
    """USD₮ (Tether's ₮ glyph, U+20AE) normalizes to USDT and must be ingested, not dropped.
    The original symbol is preserved in storage for display."""
    supply = [_supply_pool("g1", "Celo", "aave-v3", "USD₮", base=0.64, tvl=2_000_000)]
    borrow = [_borrow_pool("g1", base=1.89)]
    ing = PoolsIngestor(db, StubDefiLlama(supply, borrow), StubMerkl([]))
    n = await ing.run_once(ts=1716800000)
    assert n == 1
    row = await db.fetch_one("SELECT symbol FROM pools_snapshot WHERE pool_id='g1'")
    assert row == ("USD₮",)   # original ticker kept for display, not rewritten to USDT


async def test_ingestor_flags_lav_uncertain_for_unknown_token_project(db):
    """A pool from an unknown project (no primary_reward in config/projects.json)
    or whose primary_reward isn't in lav_buckets.json should be flagged lav_uncertain=1."""
    supply = [
        _supply_pool("known", "BSC", "aave-v3", "USDC"),       # AAVE -> bucket A -> KNOWN
        _supply_pool("unknown", "Sui", "some-new-protocol", "USDC"),  # unknown project -> UNKNOWN
    ]
    borrow = [_borrow_pool("known"), _borrow_pool("unknown")]
    ing = PoolsIngestor(db, StubDefiLlama(supply, borrow), StubMerkl([]))
    await ing.run_once(ts=1716800000)

    known_flag = await db.fetch_one("SELECT lav_uncertain FROM pools_snapshot WHERE pool_id=?", ("known",))
    unknown_flag = await db.fetch_one("SELECT lav_uncertain FROM pools_snapshot WHERE pool_id=?", ("unknown",))
    assert known_flag == (0,)
    assert unknown_flag == (1,)


async def test_ingestor_keeps_eth_and_btc_class_pools(db):
    """ETH/BTC starting-capital classes are now in scope, alongside stablecoins."""
    supply = [
        _supply_pool("e1", "Arbitrum", "aave-v3", "WETH", base=2.0, tvl=5_000_000),
        _supply_pool("b1", "Avalanche", "aave-v3", "BTC.B", base=0.5, tvl=5_000_000),
        _supply_pool("x1", "BSC", "pancake", "CAKE", base=9.0, tvl=5_000_000),  # not a class -> dropped
    ]
    borrow = [_borrow_pool("e1"), _borrow_pool("b1"), _borrow_pool("x1")]
    ing = PoolsIngestor(db, StubDefiLlama(supply, borrow), StubMerkl([]))
    n = await ing.run_once(ts=1716800000)
    assert n == 2  # WETH + BTC.B kept; CAKE dropped
    rows = await db.fetch_all("SELECT symbol FROM pools_snapshot ORDER BY pool_id")
    assert rows == [("BTC.B",), ("WETH",)]


class StubBinance:
    def __init__(self, coins): self.coins = coins
    async def __aenter__(self): return self
    async def __aexit__(self, *a): pass
    async def fetch_capital_config(self): return self.coins


async def test_ingestor_writes_binance_withdraw_cache(db, tmp_path, monkeypatch):
    """Each tick fetches capital/config and writes data/binance_withdraw.json (class->chains)."""
    import json as _json
    from config.config import settings
    cache = tmp_path / "binance_withdraw.json"
    monkeypatch.setattr(settings, "BINANCE_WITHDRAW_CACHE", str(cache), raising=False)
    supply = [_supply_pool("e1", "Arbitrum", "aave-v3", "WETH", tvl=5_000_000)]
    borrow = [_borrow_pool("e1")]
    coins = [{"coin": "ETH", "networkList": [
        {"network": "ARBITRUM", "withdrawEnable": True, "depositEnable": True}]}]
    ing = PoolsIngestor(db, StubDefiLlama(supply, borrow), StubMerkl([]), binance=StubBinance(coins))
    await ing.run_once(ts=1716800000)
    saved = _json.loads(cache.read_text())
    assert "Arbitrum" in saved["withdraw"]["ETH"]
    assert "Arbitrum" in saved["deposit"]["ETH"]


class StubMerklFull:
    """Stub with BOTH borrow and supply (LEND) opportunity lists."""
    def __init__(self, borrow_opps, supply_opps):
        self.borrow_opps, self.supply_opps = borrow_opps, supply_opps
    async def __aenter__(self): return self
    async def __aexit__(self, *a): pass
    async def fetch_borrow_opportunities(self, max_pages=5): return self.borrow_opps
    async def fetch_supply_opportunities(self, max_pages=5): return self.supply_opps


class StubAci:
    def __init__(self, payload): self.payload = payload
    async def __aenter__(self): return self
    async def __aexit__(self, *a): pass
    async def fetch_merit_aprs(self): return self.payload


async def test_ingestor_applies_supply_incentives_and_writes_aci_cache(db, tmp_path, monkeypatch):
    import json as _json
    from config.config import settings
    aci_cache = tmp_path / "aci.json"
    monkeypatch.setattr(settings, "ACI_INCENTIVES_CACHE", str(aci_cache), raising=False)
    monkeypatch.setattr(settings, "BINANCE_WITHDRAW_CACHE", str(tmp_path / "bw.json"), raising=False)

    supply = [_supply_pool("w1", "Celo", "aave-v3", "WETH", base=0.02, tvl=2_000_000)]
    borrow = [_borrow_pool("w1")]
    aci_payload = {"currentAPR": {"actionsAPR": {
        "celo-supply-weth": 2.08, "self-celo-supply-weth": 2.08}}}
    ing = PoolsIngestor(db, StubDefiLlama(supply, borrow), StubMerklFull([], []),
                        binance=StubBinance([]), aci=StubAci(aci_payload))
    await ing.run_once(ts=1716800000)

    row = await db.fetch_one(
        "SELECT supply_apy_reward, reward_source FROM pools_snapshot WHERE pool_id='w1'")
    assert row[0] == pytest.approx(4.16)       # merit+self landed in the stored reward
    assert row[1] == "aci_merit"
    saved = _json.loads(aci_cache.read_text())
    assert saved["Celo|WETH"] == {"merit": 2.08, "self": 2.08}


async def test_ingestor_writes_protocol_categories_cache(db, tmp_path, monkeypatch):
    import json as _json
    from config.config import settings
    cache = tmp_path / "cats.json"
    monkeypatch.setattr(settings, "PROTOCOL_CATEGORIES_CACHE", str(cache), raising=False)
    monkeypatch.setattr(settings, "BINANCE_WITHDRAW_CACHE", str(tmp_path / "bw.json"), raising=False)
    monkeypatch.setattr(settings, "ACI_INCENTIVES_CACHE", str(tmp_path / "aci.json"), raising=False)

    supply = [_supply_pool("p1", "Ethereum", "aave-v3", "USDC", base=3.0, tvl=5_000_000)]
    borrow = [_borrow_pool("p1")]
    dl = StubDefiLlama(supply, borrow)
    dl.categories = {"aave-v3": "Lending", "peapods-finance": "Yield"}
    ing = PoolsIngestor(db, dl, StubMerkl([]), binance=StubBinance([]))
    await ing.run_once(ts=1716800000)

    saved = _json.loads(cache.read_text())
    assert saved == {"aave-v3": "Lending", "peapods-finance": "Yield"}


async def test_ingestor_keeps_stale_categories_cache_on_empty_fetch(db, tmp_path, monkeypatch):
    import json as _json
    from config.config import settings
    cache = tmp_path / "cats.json"
    cache.write_text(_json.dumps({"aave-v3": "Lending"}))      # pre-existing cache
    monkeypatch.setattr(settings, "PROTOCOL_CATEGORIES_CACHE", str(cache), raising=False)
    monkeypatch.setattr(settings, "BINANCE_WITHDRAW_CACHE", str(tmp_path / "bw.json"), raising=False)
    monkeypatch.setattr(settings, "ACI_INCENTIVES_CACHE", str(tmp_path / "aci.json"), raising=False)

    supply = [_supply_pool("p1", "Ethereum", "aave-v3", "USDC", base=3.0, tvl=5_000_000)]
    borrow = [_borrow_pool("p1")]
    dl = StubDefiLlama(supply, borrow)
    dl.categories = {}                                          # fetch failed / empty
    ing = PoolsIngestor(db, dl, StubMerkl([]), binance=StubBinance([]))
    await ing.run_once(ts=1716800000)

    saved = _json.loads(cache.read_text())
    assert saved == {"aave-v3": "Lending"}                     # stale kept, NOT clobbered
