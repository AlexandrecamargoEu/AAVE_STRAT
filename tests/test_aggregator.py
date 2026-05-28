import pytest
from db.sqlite_client import SqliteClient
from services.pools.aggregator import compute_aggregates


@pytest.fixture
async def db(tmp_path):
    c = SqliteClient(db_path=str(tmp_path / "agg.db"))
    await c.connect()
    await c.apply_migrations()
    yield c
    await c.close()


async def _seed_history(db, pool_id, samples):
    """samples = [(ts, supply_base, supply_reward, borrow_base, borrow_reward, util, tvl), ...]"""
    for ts, sb, sr, bb, br, u, t in samples:
        await db.execute(
            """INSERT INTO pools_history
               (pool_id, ts, source, supply_apy_base, supply_apy_reward,
                borrow_apr_base, borrow_apr_reward, utilization, tvl_usd)
               VALUES (?, ?, 'live', ?, ?, ?, ?, ?, ?)""",
            (pool_id, ts, sb, sr, bb, br, u, t),
        )
    # also snapshot row (aggregator may look at project/chain)
    await db.execute(
        """INSERT OR IGNORE INTO pools_snapshot
           (pool_id, chain, project, symbol, tvl_usd, updated_at)
           VALUES (?, 'BSC', 'aave-v3', 'USDC', 1, ?)""",
        (pool_id, samples[-1][0]),
    )


async def test_7d_aggregate_computed(db):
    now = 1716800000
    day = 86400
    samples = [(now - i * day, 3.0 + i * 0.1, 0.0, 4.0, 0.0, 0.5, 1e7) for i in range(7)]
    await _seed_history(db, "uuid-1", samples)
    n = await compute_aggregates(db, now_ts=now)
    assert n > 0
    row = await db.fetch_one(
        "SELECT supply_apy_effective_avg, sample_count FROM rate_aggregates WHERE pool_id=? AND window='7d'",
        ("uuid-1",),
    )
    assert row is not None
    # Mean of [3.0..3.6] = 3.3 (project aave-v3 -> AAVE -> bucket A, no discount)
    assert row[0] == pytest.approx(3.3, abs=0.001)
    assert row[1] == 7


async def test_30d_aggregate_includes_older_samples(db):
    now = 1716800000
    day = 86400
    samples = [(now - i * day, 5.0, 0.0, 3.0, 0.0, 0.5, 1e7) for i in range(30)]
    await _seed_history(db, "uuid-30", samples)
    await compute_aggregates(db, now_ts=now)
    row = await db.fetch_one(
        "SELECT supply_apy_effective_avg, sample_count FROM rate_aggregates WHERE pool_id=? AND window='30d'",
        ("uuid-30",),
    )
    assert row is not None
    assert row[1] == 30


async def test_aggregate_recompute_on_lav_change_is_just_rerun(db):
    """Aggregates store effective rates — if LAV config changes, re-run handles it."""
    now = 1716800000
    samples = [(now - i * 86400, 4.0, 2.0, 3.0, 0.0, 0.5, 1e7) for i in range(7)]
    await _seed_history(db, "uuid-r", samples)
    await compute_aggregates(db, now_ts=now)
    first = await db.fetch_one(
        "SELECT supply_apy_effective_avg FROM rate_aggregates WHERE pool_id=? AND window='7d'",
        ("uuid-r",),
    )
    # Same data + same config = same result on re-run
    await compute_aggregates(db, now_ts=now)
    second = await db.fetch_one(
        "SELECT supply_apy_effective_avg FROM rate_aggregates WHERE pool_id=? AND window='7d'",
        ("uuid-r",),
    )
    assert first == second
