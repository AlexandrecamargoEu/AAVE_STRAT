"""Pure ranking math. NO I/O. NO state. Testable without network or DB.

Built around the spec's central design choice (Section 7): store raw rates,
compute effective on read. LAV reclassification recomputes everything for free.

Effective formulas (spec 2b.A):
  effective_supply_apy = base + reward * (1 - LAV_discount)
  effective_borrow_apr = max(0, base - rebate * (1 - LAV_discount))

Leverage (spec 2b.H):
  per_iter_ltv  = platform_ltv - 5% buffer (clamped >= 0)
  leverage      = sum(per_iter_ltv^i for i in 0..n_iter-1)
  In a same-chain loop, the binding LTV is the lower of the two legs.
"""
from functools import lru_cache

from config.config import load_projects
from services.rewards.lav import discount_for_token


BUFFER_PCT = 0.05
N_ITER_DEFAULT = 10


@lru_cache(maxsize=1)
def _projects_index() -> dict:
    return load_projects()


def _primary_reward_token(project: str | None) -> str | None:
    if not project:
        return None
    proj = _projects_index().get(project)
    return proj.get("primary_reward") if proj else None


def effective_supply_apy(pool: dict) -> float:
    """base + reward*(1 - LAV_discount). Reward token inferred from project."""
    base = float(pool.get("apyBase") or 0)
    reward = float(pool.get("apyReward") or 0)
    token = _primary_reward_token(pool.get("project"))
    disc = discount_for_token(token)
    return base + reward * (1 - disc)


def effective_borrow_apr(pool: dict) -> float:
    """max(0, base - rebate*(1 - LAV_discount)). Floored at 0."""
    base = float(pool.get("apyBaseBorrow") or 0)
    rebate = float(pool.get("apyRewardBorrow") or 0)
    token = _primary_reward_token(pool.get("project"))
    disc = discount_for_token(token)
    return max(0.0, base - rebate * (1 - disc))


def per_iter_ltv(platform_ltv: float | None) -> float:
    """Apply 5% safety buffer to the platform's LTV. Clamp at 0."""
    if platform_ltv is None:
        return 0.0
    return max(0.0, float(platform_ltv) - BUFFER_PCT)


def compute_leverage(per_iter_ltv_value: float, n_iter: int = N_ITER_DEFAULT) -> float:
    """Sum of geometric series: 1 + r + r^2 + ... + r^(n-1)."""
    r = per_iter_ltv_value
    if r <= 0:
        return 1.0
    total = 0.0
    p = 1.0
    for _ in range(n_iter):
        total += p
        p *= r
    return total
