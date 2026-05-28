"""Persist a snapshot batch: UPSERT pools_snapshot + INSERT pools_history.

Idempotent for re-running the same ts (UPSERT on snapshot, history PK includes ts+source).
Marks pools missing from the current batch as status='inactive' — never DELETE.
"""
import json

from db.sqlite_client import SqliteClient


_SNAPSHOT_UPSERT = """
INSERT INTO pools_snapshot (
  pool_id, chain, project, symbol, pool_meta,
  tvl_usd, total_supply_usd, total_borrow_usd, available_liquidity,
  debt_ceiling_usd, utilization,
  supply_apy_base, supply_apy_reward, reward_source,
  borrow_apr_base, borrow_apr_reward,
  ltv, borrow_factor, borrowable,
  reward_tokens, underlying_tokens,
  lav_uncertain, quality_flag, status, updated_at
) VALUES (
  :pool_id, :chain, :project, :symbol, :pool_meta,
  :tvl_usd, :total_supply_usd, :total_borrow_usd, :available_liquidity,
  :debt_ceiling_usd, :utilization,
  :supply_apy_base, :supply_apy_reward, :reward_source,
  :borrow_apr_base, :borrow_apr_reward,
  :ltv, :borrow_factor, :borrowable,
  :reward_tokens, :underlying_tokens,
  :lav_uncertain, :quality_flag, 'active', :updated_at
)
ON CONFLICT(pool_id) DO UPDATE SET
  chain=excluded.chain, project=excluded.project, symbol=excluded.symbol,
  pool_meta=excluded.pool_meta,
  tvl_usd=excluded.tvl_usd, total_supply_usd=excluded.total_supply_usd,
  total_borrow_usd=excluded.total_borrow_usd, available_liquidity=excluded.available_liquidity,
  debt_ceiling_usd=excluded.debt_ceiling_usd, utilization=excluded.utilization,
  supply_apy_base=excluded.supply_apy_base, supply_apy_reward=excluded.supply_apy_reward,
  reward_source=excluded.reward_source,
  borrow_apr_base=excluded.borrow_apr_base, borrow_apr_reward=excluded.borrow_apr_reward,
  ltv=excluded.ltv, borrow_factor=excluded.borrow_factor, borrowable=excluded.borrowable,
  reward_tokens=excluded.reward_tokens, underlying_tokens=excluded.underlying_tokens,
  lav_uncertain=excluded.lav_uncertain, quality_flag=excluded.quality_flag,
  status='active',
  updated_at=excluded.updated_at
"""

_HISTORY_INSERT = """
INSERT OR REPLACE INTO pools_history (
  pool_id, ts, source,
  tvl_usd, total_supply_usd, total_borrow_usd, available_liquidity, debt_ceiling_usd,
  supply_apy_base, supply_apy_reward, reward_source,
  borrow_apr_base, borrow_apr_reward, utilization, quality_flag
) VALUES (
  :pool_id, :ts, :source,
  :tvl_usd, :total_supply_usd, :total_borrow_usd, :available_liquidity, :debt_ceiling_usd,
  :supply_apy_base, :supply_apy_reward, :reward_source,
  :borrow_apr_base, :borrow_apr_reward, :utilization, :quality_flag
)
"""


def _to_db_params(row: dict, ts: int) -> dict:
    tvl = row.get("tvlUsd")
    tsu = row.get("totalSupplyUsd")
    tbu = row.get("totalBorrowUsd")
    util = (tbu / tsu) if (tsu and tbu and tsu > 0) else None
    available = (tsu - tbu) if (tsu is not None and tbu is not None) else None
    return {
        "pool_id": row["pool"],
        "chain": row["chain"],
        "project": row["project"],
        "symbol": row["symbol"],
        "pool_meta": row.get("poolMeta"),
        "tvl_usd": tvl,
        "total_supply_usd": tsu,
        "total_borrow_usd": tbu,
        "available_liquidity": available,
        "debt_ceiling_usd": row.get("debtCeilingUsd"),
        "utilization": util,
        "supply_apy_base": row.get("apyBase") or 0.0,
        "supply_apy_reward": row.get("apyReward") or 0.0,
        "reward_source": row.get("reward_source", "defillama"),
        "borrow_apr_base": row.get("apyBaseBorrow"),
        "borrow_apr_reward": row.get("apyRewardBorrow"),
        "ltv": row.get("ltv"),
        "borrow_factor": row.get("borrowFactor"),
        "borrowable": int(row["borrowable"]) if row.get("borrowable") is not None else None,
        "reward_tokens": json.dumps(row.get("rewardTokens")) if row.get("rewardTokens") else None,
        "underlying_tokens": json.dumps(row.get("underlyingTokens")) if row.get("underlyingTokens") else None,
        "lav_uncertain": int(row.get("lav_uncertain", 0)),
        "quality_flag": row.get("quality_flag", "ok"),
        "updated_at": ts,
        "ts": ts,
        "source": "live",
    }


async def apply_snapshot(db: SqliteClient, rows: list[dict], ts: int) -> int:
    """UPSERT pools_snapshot + INSERT pools_history. Mark missing pools inactive."""
    params = [_to_db_params(r, ts) for r in rows]
    if not params:
        return 0
    seen_ids = {p["pool_id"] for p in params}

    # 1. Upsert + history (one transaction effectively, sqlite_client commits per call)
    for p in params:
        await db.execute(_SNAPSHOT_UPSERT, p)
        await db.execute(_HISTORY_INSERT, p)

    # 2. Mark pools missing from this batch as inactive
    placeholders = ",".join("?" * len(seen_ids))
    await db.execute(
        f"UPDATE pools_snapshot SET status='inactive' WHERE pool_id NOT IN ({placeholders})",
        tuple(seen_ids),
    )
    return len(params)
