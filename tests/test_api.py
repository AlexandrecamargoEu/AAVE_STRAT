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
