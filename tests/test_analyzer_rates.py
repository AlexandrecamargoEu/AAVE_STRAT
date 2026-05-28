import pytest
from services.routes.analyzer import (
    effective_supply_apy,
    effective_borrow_apr,
    per_iter_ltv,
    compute_leverage,
)


def test_effective_supply_no_reward_equals_base():
    p = {"apyBase": 5.0, "apyReward": 0.0, "project": "aave-v3"}
    assert effective_supply_apy(p) == pytest.approx(5.0)


def test_effective_supply_with_a_bucket_reward_no_discount():
    """AAVE reward token is bucket A (0% discount)."""
    p = {"apyBase": 5.0, "apyReward": 4.0, "project": "aave-v3"}
    # primary_reward AAVE -> bucket A -> 0% discount -> effective reward = 4.0
    assert effective_supply_apy(p) == pytest.approx(9.0)


def test_effective_supply_with_b_bucket_reward_discounted():
    """Venus's primary reward is XVS (bucket B, 12.5% discount)."""
    p = {"apyBase": 5.0, "apyReward": 4.0, "project": "venus-core-pool"}
    # effective reward = 4.0 * (1 - 0.125) = 3.5
    assert effective_supply_apy(p) == pytest.approx(5.0 + 3.5)


def test_effective_borrow_floors_at_zero():
    """Per spec 2b.A: max(0, base - rebate * (1 - discount))."""
    p = {"apyBaseBorrow": 1.5, "apyRewardBorrow": 5.0, "project": "aave-v3"}
    # 1.5 - 5.0*(1-0) = -3.5 -> floored at 0
    assert effective_borrow_apr(p) == 0.0


def test_effective_borrow_normal_subtract():
    p = {"apyBaseBorrow": 4.0, "apyRewardBorrow": 1.4, "project": "aave-v3"}
    # bucket A, no discount; 4.0 - 1.4 = 2.6
    assert effective_borrow_apr(p) == pytest.approx(2.6)


def test_per_iter_ltv_subtracts_5pct_buffer():
    """Paul (2b.H): platform LTV minus 5% safety buffer."""
    # Aave USDC LTV 0.75 -> per-iter 0.70
    assert per_iter_ltv(0.75) == pytest.approx(0.70)
    assert per_iter_ltv(0.80) == pytest.approx(0.75)


def test_per_iter_ltv_clamps_at_zero():
    assert per_iter_ltv(0.04) == 0.0
    assert per_iter_ltv(None) == 0.0


def test_compute_leverage_geometric_sum():
    """L = sum(ltv^i, i=0..n-1)."""
    # 0.855/10 -> ~5.46
    assert compute_leverage(0.855, 10) == pytest.approx(5.4566, abs=0.001)
    # 0.70/10 -> ~3.24 (geometric sum: (1 - 0.7^10)/(1 - 0.7))
    assert compute_leverage(0.70, 10) == pytest.approx(3.2392, abs=0.001)
    # zero LTV -> 1 (no leverage, you only ever have your principal)
    assert compute_leverage(0.0, 10) == 1.0
