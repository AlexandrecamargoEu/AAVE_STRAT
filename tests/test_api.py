import pytest
from fastapi import FastAPI
from httpx import AsyncClient, ASGITransport

from db.sqlite_client import SqliteClient
from services.api.router import router, set_db


@pytest.fixture
async def app(tmp_path):
    db = SqliteClient(db_path=str(tmp_path / "api.db"))
    await db.connect()
    await db.apply_migrations()
    set_db(db)
    app_ = FastAPI()
    app_.include_router(router)
    yield app_, db
    await db.close()


async def test_health_warming_up_when_empty(app):
    app_, _db = app
    transport = ASGITransport(app=app_)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        resp = await ac.get("/api/codee/health")
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "warming_up"
    assert body["last_snapshot_at"] is None


async def test_health_ok_after_insertion(app):
    app_, db = app
    import time
    await db.execute(
        """INSERT INTO pools_snapshot (pool_id, chain, project, symbol, tvl_usd, updated_at)
           VALUES (?, 'BSC', 'aave-v3', 'USDC', 1e7, ?)""",
        ("u1", int(time.time())),
    )
    transport = ASGITransport(app=app_)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        resp = await ac.get("/api/codee/health")
    body = resp.json()
    assert body["status"] == "ok"
    assert body["pool_count_in_scope"] == 1
    assert body["stale"] is False


async def test_passive_endpoint_returns_ranked(app):
    app_, db = app
    import time
    now = int(time.time())
    await db.execute(
        """INSERT INTO pools_snapshot (pool_id, chain, project, symbol, tvl_usd,
           supply_apy_base, supply_apy_reward, updated_at)
           VALUES (?, 'BSC', 'aave-v3', 'USDC', 1e7, 5.0, 0.0, ?)""",
        ("u1", now),
    )
    await db.execute(
        """INSERT INTO pools_snapshot (pool_id, chain, project, symbol, tvl_usd,
           supply_apy_base, supply_apy_reward, updated_at)
           VALUES (?, 'Base', 'yearn', 'USDC', 1e7, 15.0, 0.0, ?)""",
        ("u2", now),
    )
    transport = ASGITransport(app=app_)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        resp = await ac.get("/api/codee/routes/passive")
    body = resp.json()
    assert body[0]["symbol"] == "USDC"
    assert body[0]["project"] == "yearn"
    assert body[0]["effective_apy"] == 15.0


async def test_invalid_query_param_returns_422(app):
    app_, _ = app
    transport = ASGITransport(app=app_)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        resp = await ac.get("/api/codee/routes/passive?limit=invalid")
    assert resp.status_code == 422


async def test_health_includes_new_fields(app):
    """Gap 5: HealthResponse now includes pool_count_total, lav_coverage_pct, last_error."""
    app_, db = app
    import time
    now = int(time.time())
    await db.execute(
        """INSERT INTO pools_snapshot (pool_id, chain, project, symbol, tvl_usd, lav_uncertain, updated_at)
           VALUES (?, 'BSC', 'aave-v3', 'USDC', 1e7, 0, ?)""",
        ("u1", now),
    )
    await db.execute(
        """INSERT INTO pools_snapshot (pool_id, chain, project, symbol, tvl_usd, lav_uncertain, updated_at, status)
           VALUES (?, 'BSC', 'unknown', 'USDT', 1e7, 1, ?, 'inactive')""",
        ("u2", now),
    )
    transport = ASGITransport(app=app_)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        resp = await ac.get("/api/codee/health")
    body = resp.json()
    assert body["pool_count_total"] == 2          # active + inactive
    assert body["pool_count_in_scope"] == 1        # only active
    # 1 active pool, lav_uncertain=0 -> 100% coverage
    assert body["lav_coverage_pct"] == 1.0
    assert body["last_error"] is None


async def test_pools_snapshot_endpoint_paginates(app):
    app_, db = app
    import time
    now = int(time.time())
    for i in range(5):
        await db.execute(
            """INSERT INTO pools_snapshot (pool_id, chain, project, symbol, tvl_usd, updated_at)
               VALUES (?, 'BSC', 'aave-v3', 'USDC', ?, ?)""",
            (f"p{i}", (5 - i) * 1e6, now),
        )
    transport = ASGITransport(app=app_)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        resp = await ac.get("/api/codee/pools/snapshot?limit=3&offset=1")
    body = resp.json()
    assert body["total"] == 5
    assert body["offset"] == 1
    assert body["limit"] == 3
    assert len(body["items"]) == 3
    # Sorted by TVL desc — first page item is p1 (2nd-highest TVL)
    assert body["items"][0]["pool_id"] == "p1"


async def test_rewards_coverage_endpoint(app):
    app_, db = app
    import time
    now = int(time.time())
    await db.execute(
        """INSERT INTO pools_snapshot (pool_id, chain, project, symbol, tvl_usd, lav_uncertain, supply_apy_reward, reward_source, updated_at)
           VALUES (?, 'BSC', 'aave-v3', 'USDC', 1e7, 0, 1.5, 'defillama', ?)""",
        ("a", now),
    )
    await db.execute(
        """INSERT INTO pools_snapshot (pool_id, chain, project, symbol, tvl_usd, lav_uncertain, supply_apy_reward, reward_source, updated_at)
           VALUES (?, 'Mantle', 'aave-v3', 'USDC', 1e7, 0, 0, 'merkl', ?)""",
        ("b", now),
    )
    await db.execute(
        """INSERT INTO pools_snapshot (pool_id, chain, project, symbol, tvl_usd, lav_uncertain, supply_apy_reward, reward_source, updated_at)
           VALUES (?, 'Sui', 'unknown', 'USDT', 1e7, 1, 0, 'defillama', ?)""",
        ("c", now),
    )
    transport = ASGITransport(app=app_)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        resp = await ac.get("/api/codee/rewards/coverage")
    body = resp.json()
    assert body["pools_in_scope"] == 3
    assert body["pools_with_classified_reward"] == 2   # a and b have lav_uncertain=0
    assert body["pools_with_merkl_borrow_rebate"] == 1 # only b
    assert body["reward_active_pools"] == 1            # only a has supply_apy_reward > 0
    assert body["lav_coverage_pct"] == pytest.approx(2 / 3)


async def test_crosschain_endpoint_includes_available_liquidity(app):
    """GET /routes/crosschain exposes available_liquidity_usd = min(supply tvl, borrow tvl)."""
    app_, db = app
    import time
    now = int(time.time())
    # Canto: high supply rate, has borrow side; tvl_usd 2e6
    await db.execute(
        """INSERT INTO pools_snapshot
           (pool_id, chain, project, symbol, tvl_usd,
            supply_apy_base, supply_apy_reward,
            borrow_apr_base, borrow_apr_reward,
            updated_at)
           VALUES (?, 'Canto', 'canto-lending', 'USDC', 2000000,
                   13.5, 0.0, 15.0, NULL, ?)""",
        ("canto-usdc", now),
    )
    # Cronos: cheap borrow; tvl_usd 3e5
    await db.execute(
        """INSERT INTO pools_snapshot
           (pool_id, chain, project, symbol, tvl_usd,
            supply_apy_base, supply_apy_reward,
            borrow_apr_base, borrow_apr_reward,
            updated_at)
           VALUES (?, 'Cronos', 'tectonic', 'USDC', 300000,
                   2.0, 0.0, 0.5, NULL, ?)""",
        ("cronos-usdc", now),
    )
    transport = ASGITransport(app=app_)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        resp = await ac.get("/api/codee/routes/crosschain")
    assert resp.status_code == 200
    body = resp.json()
    usdc = next(r for r in body if r["symbol"] == "USDC")
    assert usdc["available_liquidity_usd"] == pytest.approx(3e5)


async def test_passive_route_includes_entry_asset_classes(app):
    app_, db = app
    import time
    now = int(time.time())
    await db.execute(
        """INSERT INTO pools_snapshot (pool_id, chain, project, symbol, tvl_usd,
           supply_apy_base, updated_at) VALUES (?, 'Arbitrum', 'aave-v3', 'WETH', 5e6, 2.0, ?)""",
        ("e1", now))
    await db.execute(
        """INSERT INTO pools_snapshot (pool_id, chain, project, symbol, tvl_usd,
           supply_apy_base, updated_at) VALUES (?, 'BSC', 'aave-v3', 'DAI', 5e6, 3.0, ?)""",
        ("d1", now))
    transport = ASGITransport(app=app_)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        resp = await ac.get("/api/codee/routes/passive")
    body = resp.json()
    weth = next(r for r in body if r["symbol"] == "WETH")
    dai = next(r for r in body if r["symbol"] == "DAI")
    assert weth["entry_asset_classes"] == ["ETH"]
    assert dai["entry_asset_classes"] == []   # DAI is not a starting-capital class


async def test_passive_route_binance_withdrawable_flag(app, tmp_path, monkeypatch):
    app_, db = app
    import time, json as _json
    from config.config import settings
    cache = tmp_path / "bw.json"
    cache.write_text(_json.dumps({"ETH": ["Arbitrum"], "USDC": [], "USDT": [], "BTC": []}))
    monkeypatch.setattr(settings, "BINANCE_WITHDRAW_CACHE", str(cache), raising=False)
    now = int(time.time())
    await db.execute("""INSERT INTO pools_snapshot (pool_id,chain,project,symbol,tvl_usd,supply_apy_base,updated_at)
                        VALUES ('e1','Arbitrum','aave-v3','WETH',5e6,2.0,?)""", (now,))
    await db.execute("""INSERT INTO pools_snapshot (pool_id,chain,project,symbol,tvl_usd,supply_apy_base,updated_at)
                        VALUES ('e2','Sonic','aave-v3','WETH',5e6,2.0,?)""", (now,))
    await db.execute("""INSERT INTO pools_snapshot (pool_id,chain,project,symbol,tvl_usd,supply_apy_base,updated_at)
                        VALUES ('d1','BSC','aave-v3','DAI',5e6,3.0,?)""", (now,))
    transport = ASGITransport(app=app_)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        body = (await ac.get("/api/codee/routes/passive")).json()
    eth_arb = next(r for r in body if r["chain"] == "Arbitrum" and r["symbol"] == "WETH")
    eth_sonic = next(r for r in body if r["chain"] == "Sonic" and r["symbol"] == "WETH")
    dai = next(r for r in body if r["symbol"] == "DAI")
    assert eth_arb["binance_withdrawable"] is True     # ETH withdrawable to Arbitrum
    assert eth_sonic["binance_withdrawable"] is False  # ETH not withdrawable to Sonic
    assert dai["binance_withdrawable"] is None         # DAI is not a class


async def test_binance_withdrawable_none_when_map_all_empty(app, tmp_path, monkeypatch):
    """No-creds degrade: an all-empty cache must yield None (not False) — nothing hidden."""
    app_, db = app
    import time, json as _json
    from config.config import settings
    cache = tmp_path / "bw_empty.json"
    cache.write_text(_json.dumps({"USDC": [], "USDT": [], "ETH": [], "BTC": []}))
    monkeypatch.setattr(settings, "BINANCE_WITHDRAW_CACHE", str(cache), raising=False)
    now = int(time.time())
    await db.execute("""INSERT INTO pools_snapshot (pool_id,chain,project,symbol,tvl_usd,supply_apy_base,updated_at)
                        VALUES ('e1','Arbitrum','aave-v3','WETH',5e6,2.0,?)""", (now,))
    transport = ASGITransport(app=app_)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        body = (await ac.get("/api/codee/routes/passive")).json()
    weth = next(r for r in body if r["symbol"] == "WETH")
    assert weth["binance_withdrawable"] is None


async def test_chains_summary_endpoint(app):
    app_, db = app
    import time
    now = int(time.time())
    # Seed: 2 pools with a 30d aggregate each
    await db.execute(
        """INSERT INTO pools_snapshot (pool_id, chain, project, symbol, tvl_usd, updated_at)
           VALUES (?, 'BSC', 'aave-v3', 'USDC', 1e7, ?)""",
        ("a", now),
    )
    await db.execute(
        """INSERT INTO pools_snapshot (pool_id, chain, project, symbol, tvl_usd, updated_at)
           VALUES (?, 'BSC', 'venus', 'USDT', 1e7, ?)""",
        ("b", now),
    )
    await db.execute(
        """INSERT INTO rate_aggregates (pool_id, window, supply_apy_effective_avg, borrow_apr_effective_avg, sample_count, computed_at)
           VALUES (?, '30d', 5.0, 3.0, 30, ?)""",
        ("a", now),
    )
    await db.execute(
        """INSERT INTO rate_aggregates (pool_id, window, supply_apy_effective_avg, borrow_apr_effective_avg, sample_count, computed_at)
           VALUES (?, '30d', 7.0, 4.0, 30, ?)""",
        ("b", now),
    )
    transport = ASGITransport(app=app_)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        resp = await ac.get("/api/codee/chains/summary")
    body = resp.json()
    assert len(body) == 1
    bsc = body[0]
    assert bsc["chain"] == "BSC"
    assert bsc["pool_count"] == 2
    assert bsc["avg_supply_apy_effective"] == pytest.approx(6.0)
    assert bsc["avg_borrow_apr_effective"] == pytest.approx(3.5)
    assert bsc["avg_spread"] == pytest.approx(2.5)


async def test_passive_route_incentive_conditional_from_aci_cache(app, tmp_path, monkeypatch):
    app_, db = app
    import time, json as _json
    from config.config import settings
    cache = tmp_path / "aci.json"
    cache.write_text(_json.dumps({"Celo|WETH": {"merit": 2.08, "self": 2.08},
                                  "Celo|USDC": {"merit": 1.0, "self": 0.0}}))
    monkeypatch.setattr(settings, "ACI_INCENTIVES_CACHE", str(cache), raising=False)
    now = int(time.time())
    await db.execute("""INSERT INTO pools_snapshot (pool_id,chain,project,symbol,tvl_usd,supply_apy_base,updated_at)
                        VALUES ('w1','Celo','aave-v3','WETH',5e6,4.2,?)""", (now,))
    await db.execute("""INSERT INTO pools_snapshot (pool_id,chain,project,symbol,tvl_usd,supply_apy_base,updated_at)
                        VALUES ('u1','Celo','aave-v3','USDC',5e6,2.6,?)""", (now,))
    transport = ASGITransport(app=app_)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        body = (await ac.get("/api/codee/routes/passive")).json()
    weth = next(r for r in body if r["symbol"] == "WETH")
    usdc = next(r for r in body if r["symbol"] == "USDC")
    assert weth["incentive_conditional"] is True    # self > 0
    assert usdc["incentive_conditional"] is False   # merit only, no self


async def test_multihop_endpoint_returns_paths(app, tmp_path, monkeypatch):
    app_, db = app
    import time, json as _json
    from config.config import settings
    bw = tmp_path / "bw.json"
    bw.write_text(_json.dumps({"withdraw": {"USDC": ["ChainA"], "ETH": ["ChainB"]},
                               "deposit":  {"USDC": ["ChainA"], "ETH": ["ChainA"]}}))
    monkeypatch.setattr(settings, "BINANCE_WITHDRAW_CACHE", str(bw), raising=False)
    monkeypatch.setattr(settings, "ACI_INCENTIVES_CACHE", str(tmp_path / "none.json"), raising=False)
    now = int(time.time())
    rows = [("a1", "ChainA", "aave-v3", "USDC", 4e6, 10.0, 4.0, 0.80),
            ("a2", "ChainA", "aave-v3", "WETH", 3e6, 0.5, 2.0, 0.80),
            ("b1", "ChainB", "aave-v3", "WETH", 2e6, 5.0, 3.0, 0.80)]
    for pid, ch, pr, sym, tvl, sup, bor, ltv in rows:
        await db.execute("""INSERT INTO pools_snapshot
            (pool_id,chain,project,symbol,tvl_usd,supply_apy_base,borrow_apr_base,ltv,updated_at)
            VALUES (?,?,?,?,?,?,?,?,?)""", (pid, ch, pr, sym, tvl, sup, bor, ltv, now))
    transport = ASGITransport(app=app_)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        resp = await ac.get("/api/codee/routes/multihop?capital=USDC")
    assert resp.status_code == 200
    body = resp.json()
    two = [r for r in body if r["hops"] == 2]
    assert two
    best = two[0]
    assert [n["chain"] for n in best["path"]] == ["ChainA", "ChainB"]
    assert best["net_apy"] == pytest.approx(12.25)
    assert best["entry_asset_classes"] == ["USDC"]
    assert best["incentive_conditional"] is False
    # v1.1: per-leg rates exposed
    assert best["path"][0]["supply_apy"] == pytest.approx(10.0)
    assert best["path"][1]["supply_apy"] == pytest.approx(5.0)
    assert len(best["borrows"]) == 1
    assert best["borrows"][0]["symbol"] == "WETH"
    assert best["borrows"][0]["borrow_apr"] == pytest.approx(2.0)
