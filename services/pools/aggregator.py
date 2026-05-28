"""Compute 7d/30d rolling averages of effective rates per pool. Re-runs are safe
(UPSERT into rate_aggregates). Triggered by the ingestor right after a snapshot.

Effective rates are computed at aggregation time using the CURRENT LAV config,
not stored raw — so a LAV reclassification only needs the aggregator to re-run.
"""
import time

from db.sqlite_client import SqliteClient
from services.routes.analyzer import effective_supply_apy, effective_borrow_apr


_WINDOW_SECS = {"7d": 7 * 86400, "30d": 30 * 86400}

_FETCH_HISTORY = """
SELECT ph.pool_id, ph.supply_apy_base, ph.supply_apy_reward,
       ph.borrow_apr_base, ph.borrow_apr_reward,
       ph.utilization, ph.tvl_usd, ps.project
FROM pools_history ph
JOIN pools_snapshot ps ON ps.pool_id = ph.pool_id
WHERE ph.ts >= ?
"""

_UPSERT_AGG = """
INSERT INTO rate_aggregates (
  pool_id, window, supply_apy_effective_avg, borrow_apr_effective_avg,
  utilization_avg, tvl_avg, sample_count, computed_at
) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
ON CONFLICT(pool_id, window) DO UPDATE SET
  supply_apy_effective_avg=excluded.supply_apy_effective_avg,
  borrow_apr_effective_avg=excluded.borrow_apr_effective_avg,
  utilization_avg=excluded.utilization_avg,
  tvl_avg=excluded.tvl_avg,
  sample_count=excluded.sample_count,
  computed_at=excluded.computed_at
"""


async def compute_aggregates(db: SqliteClient, now_ts: int | None = None) -> int:
    """Compute 7d + 30d aggregates for every pool with history. Returns rows written."""
    now = now_ts or int(time.time())

    written = 0
    for window_name, span_secs in _WINDOW_SECS.items():
        since = now - span_secs
        rows = await db.fetch_all(_FETCH_HISTORY, (since,))
        # rows: (pool_id, sb, sr, bb, br, util, tvl, project)
        # group by pool_id
        groups: dict[str, list[tuple]] = {}
        for r in rows:
            groups.setdefault(r[0], []).append(r)
        for pool_id, samples in groups.items():
            sup_eff = []
            bor_eff = []
            utils = []
            tvls = []
            project = samples[0][7]
            for (_pid, sb, sr, bb, br, u, t, _proj) in samples:
                sup_eff.append(effective_supply_apy({"apyBase": sb, "apyReward": sr, "project": project}))
                if bb is not None:
                    bor_eff.append(effective_borrow_apr({"apyBaseBorrow": bb, "apyRewardBorrow": br, "project": project}))
                if u is not None:
                    utils.append(u)
                if t is not None:
                    tvls.append(t)
            await db.execute(_UPSERT_AGG, (
                pool_id, window_name,
                sum(sup_eff) / len(sup_eff) if sup_eff else None,
                sum(bor_eff) / len(bor_eff) if bor_eff else None,
                sum(utils) / len(utils) if utils else None,
                sum(tvls) / len(tvls) if tvls else None,
                len(samples), now,
            ))
            written += 1
    return written
