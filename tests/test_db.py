import pytest
from db.sqlite_client import SqliteClient


@pytest.fixture
async def db(tmp_path):
    client = SqliteClient(db_path=str(tmp_path / "test.db"))
    await client.connect()
    await client.apply_migrations()
    yield client
    await client.close()


async def test_migrations_idempotent(db):
    # second apply must not raise
    await db.apply_migrations()


async def test_pools_snapshot_insert_and_read(db):
    await db.execute(
        "INSERT INTO pools_snapshot (pool_id, chain, project, symbol, tvl_usd, updated_at) VALUES (?, ?, ?, ?, ?, ?)",
        ("uuid-1", "BSC", "venus-core-pool", "USDT", 90_000_000, 1716800000),
    )
    row = await db.fetch_one("SELECT chain, symbol, quality_flag, status FROM pools_snapshot WHERE pool_id = ?", ("uuid-1",))
    assert row == ("BSC", "USDT", "ok", "active")


async def test_pools_history_composite_pk(db):
    """Same pool, same ts, different source => two rows allowed."""
    args = ("uuid-1", 1716800000)
    await db.execute(
        "INSERT INTO pools_history (pool_id, ts, source, tvl_usd) VALUES (?, ?, ?, ?)",
        (*args, "live", 100.0),
    )
    await db.execute(
        "INSERT INTO pools_history (pool_id, ts, source, tvl_usd) VALUES (?, ?, ?, ?)",
        (*args, "chart_daily", 101.0),
    )
    rows = await db.fetch_all("SELECT source, tvl_usd FROM pools_history WHERE pool_id = ?", ("uuid-1",))
    assert sorted(rows) == [("chart_daily", 101.0), ("live", 100.0)]
