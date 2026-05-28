"""Pool sanity validation (spec Section 8 #1, 2b.J, 2b.B).

Returns a QualityFlag enum value, never drops a pool. The dashboard surfaces
flagged pools — they're not hidden, only highlighted.

Severity (most severe wins when multiple trip):
  IMPOSSIBLE > TVL_CRASH > HIGH_UTILIZATION > NEEDS_REVIEW > OK
"""
from enum import Enum


class QualityFlag(str, Enum):
    OK               = "ok"
    NEEDS_REVIEW     = "needs_review"      # APY > 50% — Paul: don't filter, surface
    HIGH_UTILIZATION = "high_utilization"  # UR > 92% — no-entry signal (spec 2b.B)
    TVL_CRASH        = "tvl_crash"          # inter-snapshot drop > X% (handled by snapshot.py)
    IMPOSSIBLE       = "impossible"        # clear nonsense: >10,000% APY, UR > 100%, negative


_NEEDS_REVIEW_APY = 50.0
_IMPOSSIBLE_APY = 10_000.0
_HIGH_UTILIZATION = 0.92


def _utilization(pool: dict) -> float | None:
    ts = pool.get("totalSupplyUsd")
    tb = pool.get("totalBorrowUsd")
    if ts is None or tb is None or ts <= 0:
        return None
    return tb / ts


def classify_pool(pool: dict) -> QualityFlag:
    """Return the most-severe quality flag for this pool."""
    apy_base = float(pool.get("apyBase") or 0)
    apy_reward = float(pool.get("apyReward") or 0)
    total_apy = apy_base + apy_reward

    # IMPOSSIBLE checks first (severity)
    if apy_base < 0 or apy_reward < 0:
        return QualityFlag.IMPOSSIBLE
    if total_apy > _IMPOSSIBLE_APY:
        return QualityFlag.IMPOSSIBLE
    util = _utilization(pool)
    if util is not None and util > 1.0:
        return QualityFlag.IMPOSSIBLE

    # HIGH_UTILIZATION (real safety signal — Paul)
    if util is not None and util > _HIGH_UTILIZATION:
        return QualityFlag.HIGH_UTILIZATION

    # NEEDS_REVIEW (surface, don't filter)
    if total_apy > _NEEDS_REVIEW_APY:
        return QualityFlag.NEEDS_REVIEW

    return QualityFlag.OK
