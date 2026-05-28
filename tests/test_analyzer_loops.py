import pytest
from services.routes.analyzer import (
    enumerate_same_chain_loops,
    rank_passive_supply,
    Route,
)


def _pool(chain, project, symbol, base=0.0, reward=0.0,
          borrow_base=None, borrow_reward=None, ltv=0.75, tvl=10_000_000):
    return {
        "pool": f"{chain}-{project}-{symbol}",
        "chain": chain, "project": project, "symbol": symbol,
        "apyBase": base, "apyReward": reward,
        "apyBaseBorrow": borrow_base, "apyRewardBorrow": borrow_reward,
        "ltv": ltv, "tvlUsd": tvl,
    }


def test_passive_ranking_sorts_by_effective_apy_desc():
    pools = [
        _pool("Base", "aave-v3", "USDC", base=3.0, reward=0.0),
        _pool("Base", "yearn-finance", "USDC", base=15.0, reward=0.0),
        _pool("Base", "compound-v3", "USDC", base=5.0, reward=0.0),
    ]
    ranked = rank_passive_supply(pools)
    assert ranked[0].symbol == "USDC" and ranked[0].project == "yearn-finance"
    assert ranked[0].effective_apy == pytest.approx(15.0)
    assert ranked[-1].project == "aave-v3"


def test_passive_skips_zero_apy():
    pools = [
        _pool("Base", "aave-v3", "USDC", base=0.0),
        _pool("Base", "compound-v3", "USDC", base=5.0),
    ]
    ranked = rank_passive_supply(pools)
    assert len(ranked) == 1
    assert ranked[0].project == "compound-v3"


def test_enumerate_loops_requires_two_platforms_two_assets():
    """Loop needs supply X on A, borrow Y on A, supply Y on B, borrow X on B."""
    pools = [
        _pool("BSC", "venus-core-pool", "USDT", base=2.0, borrow_base=4.0, ltv=0.80),
        _pool("BSC", "venus-core-pool", "USDC", base=2.0, borrow_base=4.0, ltv=0.80),
        _pool("BSC", "aave-v3",         "USDT", base=2.5, borrow_base=3.5, ltv=0.75),
        _pool("BSC", "aave-v3",         "USDC", base=2.5, borrow_base=3.5, ltv=0.75),
    ]
    loops = enumerate_same_chain_loops(pools)
    assert len(loops) >= 1
    # binding LTV = min(0.80, 0.75) - 0.05 = 0.70 -> leverage ~3.24
    sample = loops[0]
    assert sample.leverage == pytest.approx(3.2392, abs=0.01)


def test_enumerate_loops_includes_negative_spread_routes():
    """Per design: don't hide negative-spread loops, rank them (helps explain why)."""
    pools = [
        _pool("BSC", "venus-core-pool", "USDT", base=2.0, borrow_base=5.0, ltv=0.80),
        _pool("BSC", "venus-core-pool", "USDC", base=2.0, borrow_base=5.0, ltv=0.80),
        _pool("BSC", "aave-v3",         "USDT", base=2.0, borrow_base=5.0, ltv=0.75),
        _pool("BSC", "aave-v3",         "USDC", base=2.0, borrow_base=5.0, ltv=0.75),
    ]
    loops = enumerate_same_chain_loops(pools)
    assert any(l.spread < 0 for l in loops)


def test_enumerate_skips_pools_without_borrow_data():
    pools = [
        _pool("Base", "aave-v3", "USDC", base=3.0, borrow_base=None),
        _pool("Base", "aave-v3", "USDT", base=3.0, borrow_base=None),
    ]
    assert enumerate_same_chain_loops(pools) == []
