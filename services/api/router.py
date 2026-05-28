"""FastAPI endpoints. Reads from DB (and analyzer for derived rankings).
No business logic here — orchestrates DB reads + analyzer calls + serialization.
"""
import time
from collections import Counter

from fastapi import APIRouter, Depends, HTTPException, Query

from config.config import settings
from db.sqlite_client import SqliteClient
from services.api.models import (
    HealthResponse, PassiveRoute, LoopRoute, CrossChainRoute, PoolHistoryPoint,
)
from services.routes.analyzer import (
    enumerate_same_chain_loops, rank_passive_supply, cross_chain_carry,
)


router = APIRouter(prefix="/api/codee")


# Wire the DB instance at app startup (see main.py)
_db: SqliteClient | None = None
def set_db(db: SqliteClient) -> None:
    global _db
    _db = db
def get_db() -> SqliteClient:
    if _db is None:
        raise HTTPException(503, "database not initialized")
    return _db


async def _load_pools(db: SqliteClient) -> list[dict]:
    """Snapshot rows as dicts the analyzer expects (DefiLlama-shaped)."""
    rows = await db.fetch_all("""
        SELECT pool_id, chain, project, symbol, tvl_usd,
               supply_apy_base, supply_apy_reward,
               borrow_apr_base, borrow_apr_reward,
               ltv, utilization, total_supply_usd, total_borrow_usd,
               quality_flag, status
        FROM pools_snapshot
        WHERE status = 'active'
    """)
    pools = []
    for (pid, chain, project, symbol, tvl,
         sb, sr, bb, br, ltv, util, tsu, tbu, qf, _st) in rows:
        pools.append({
            "pool": pid, "chain": chain, "project": project, "symbol": symbol,
            "tvlUsd": tvl,
            "apyBase": sb, "apyReward": sr,
            "apyBaseBorrow": bb, "apyRewardBorrow": br,
            "ltv": ltv, "utilization": util,
            "totalSupplyUsd": tsu, "totalBorrowUsd": tbu,
            "quality_flag": qf,
        })
    return pools


@router.get("/health", response_model=HealthResponse)
async def health(db: SqliteClient = Depends(get_db)):
    now = int(time.time())
    row = await db.fetch_one("SELECT MAX(updated_at) FROM pools_snapshot")
    last = row[0] if row else None
    age = (now - last) if last else None
    stale = (age is not None and age > settings.STALENESS_BANNER_HOURS * 3600)

    rows = await db.fetch_all(
        "SELECT quality_flag FROM pools_snapshot WHERE status='active'"
    )
    qf_count = Counter(r[0] for r in rows)
    n_active = len(rows)

    n_reward = (await db.fetch_one(
        "SELECT COUNT(*) FROM pools_snapshot WHERE status='active' AND supply_apy_reward > 0"
    ))[0]
    n_borrow = (await db.fetch_one(
        "SELECT COUNT(*) FROM pools_snapshot WHERE status='active' AND borrow_apr_base IS NOT NULL"
    ))[0]
    join_rate = (n_borrow / n_active) if n_active else None

    if last is None:
        status_str = "warming_up"
    elif stale:
        status_str = "degraded"
    else:
        status_str = "ok"

    return HealthResponse(
        status=status_str,
        last_snapshot_at=last, snapshot_age_s=age, stale=stale,
        pool_count_in_scope=n_active,
        join_rate=join_rate,
        quality_flags=dict(qf_count),
        reward_active_pools=n_reward,
    )


@router.get("/routes/passive", response_model=list[PassiveRoute])
async def routes_passive(db: SqliteClient = Depends(get_db), limit: int = Query(50, le=500)):
    pools = await _load_pools(db)
    ranked = rank_passive_supply(pools)
    out = []
    by_id = {(p["chain"], p["project"], p["symbol"]): p for p in pools}
    for r in ranked[:limit]:
        p = by_id.get((r.chain, r.project, r.symbol))
        out.append(PassiveRoute(
            chain=r.chain, project=r.project, symbol=r.symbol,
            effective_apy=r.effective_apy, tvl_usd=r.min_tvl_usd,
            quality_flag=p["quality_flag"] if p else "ok",
        ))
    return out


@router.get("/routes/loops", response_model=list[LoopRoute])
async def routes_loops(db: SqliteClient = Depends(get_db), limit: int = Query(50, le=500),
                       positive_only: bool = True):
    pools = await _load_pools(db)
    loops = enumerate_same_chain_loops(pools)
    out = []
    for r in loops:
        if positive_only and r.spread <= 0:
            continue
        out.append(LoopRoute(
            chain=r.chain, plat_a=r.plat_a or "", asset_x=r.asset_x or "",
            plat_b=r.plat_b or "", asset_y=r.asset_y or "",
            avg_supply=r.avg_supply, avg_borrow=r.avg_borrow,
            spread=r.spread, leverage=r.leverage, gross_apy=r.effective_apy,
            min_tvl_usd=r.min_tvl_usd,
        ))
        if len(out) >= limit:
            break
    return out


@router.get("/routes/crosschain", response_model=list[CrossChainRoute])
async def routes_crosschain(db: SqliteClient = Depends(get_db), limit: int = Query(50, le=500)):
    pools = await _load_pools(db)
    rows = cross_chain_carry(pools)
    return [CrossChainRoute(
        symbol=r.symbol,
        supply_chain=r.supply_chain, supply_project=r.supply_project, supply_apy=r.supply_apy,
        borrow_chain=r.borrow_chain, borrow_project=r.borrow_project, borrow_apr=r.borrow_apr,
        spread=r.spread, pre_bridge_ceiling=r.pre_bridge_ceiling,
    ) for r in rows[:limit]]


@router.get("/pools/{pool_id}/history", response_model=list[PoolHistoryPoint])
async def pool_history(pool_id: str, db: SqliteClient = Depends(get_db),
                       d: int = Query(30, ge=1, le=365)):
    since = int(time.time()) - d * 86400
    rows = await db.fetch_all("""
        SELECT ts, source, supply_apy_base, supply_apy_reward,
               borrow_apr_base, borrow_apr_reward, tvl_usd, utilization
        FROM pools_history
        WHERE pool_id = ? AND ts >= ?
        ORDER BY ts
    """, (pool_id, since))
    return [PoolHistoryPoint(
        ts=r[0], source=r[1],
        supply_apy_base=r[2], supply_apy_reward=r[3],
        borrow_apr_base=r[4], borrow_apr_reward=r[5],
        tvl_usd=r[6], utilization=r[7],
    ) for r in rows]
