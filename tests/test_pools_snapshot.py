import json
import pytest

from db.sqlite_client import SqliteClient
from services.pools.snapshot import apply_snapshot


@pytest.fixture
async def db(tmp_path):
    c = SqliteClient(db_path=str(tmp_path / "snap.db"))
    await c.connect()
    await c.apply_migrations()
    yield c
    await c.close()


def _row(pool_id, chain="BSC", project="venus-core-pool", symbol="USDT",
         tvl=1e7, base=2.0, reward=0.0, bb=4.0, br=None, util=0.5, q="ok"):
    return {
        "pool": pool_id, "chain": chain, "project": project, "symbol": symbol,
        "tvlUsd": tvl, "totalSupplyUsd": tvl, "totalBorrowUsd": tvl * util,
        "apyBase": base, "apyReward": reward,
        "apyBaseBorrow": bb, "apyRewardBorrow": br,
        "ltv": 0.80, "quality_flag": q, "reward_source": "defillama",
    }


async def test_first_snapshot_inserts_pools_and_history(db):
    rows = [_row("uuid-1"), _row("uuid-2", chain="Base")]
    ts = 1716800000
    n = await apply_snapshot(db, rows, ts=ts)
    assert n == 2
    snap = await db.fetch_all("SELECT pool_id, chain FROM pools_snapshot ORDER BY pool_id")
    hist = await db.fetch_all("SELECT pool_id, ts, source FROM pools_history ORDER BY pool_id")
    assert snap == [("uuid-1", "BSC"), ("uuid-2", "Base")]
    assert hist == [("uuid-1", ts, "live"), ("uuid-2", ts, "live")]


async def test_second_snapshot_upserts_and_appends_history(db):
    ts1, ts2 = 1716800000, 1716803600
    await apply_snapshot(db, [_row("uuid-1", tvl=1e7)], ts=ts1)
    await apply_snapshot(db, [_row("uuid-1", tvl=1.1e7)], ts=ts2)
    # snapshot row updated, NOT duplicated
    snaps = await db.fetch_all("SELECT pool_id, tvl_usd FROM pools_snapshot")
    assert snaps == [("uuid-1", 1.1e7)]
    # history has BOTH timestamps
    hist = await db.fetch_all("SELECT ts, tvl_usd FROM pools_history WHERE pool_id = ? ORDER BY ts", ("uuid-1",))
    assert hist == [(ts1, 1e7), (ts2, 1.1e7)]


async def test_pool_disappears_from_feed_marked_inactive(db):
    """Per spec 2b error handling: don't DELETE — preserve history, set status=inactive."""
    ts1, ts2 = 1716800000, 1716803600
    await apply_snapshot(db, [_row("uuid-keep"), _row("uuid-gone")], ts=ts1)
    await apply_snapshot(db, [_row("uuid-keep")], ts=ts2)
    rows = await db.fetch_all("SELECT pool_id, status FROM pools_snapshot ORDER BY pool_id")
    assert rows == [("uuid-gone", "inactive"), ("uuid-keep", "active")]
