import pytest
from services.routes.analyzer import cross_chain_carry, CrossChainCarry


def _p(chain, project, symbol, base=0, reward=0, borrow_base=None, borrow_reward=None, tvl=10e6):
    return {
        "pool": f"{chain}-{project}-{symbol}",
        "chain": chain, "project": project, "symbol": symbol,
        "apyBase": base, "apyReward": reward,
        "apyBaseBorrow": borrow_base, "apyRewardBorrow": borrow_reward,
        "tvlUsd": tvl, "ltv": 0.75,
    }


def test_cross_chain_per_asset_best_supply_minus_cheapest_borrow():
    pools = [
        _p("Canto",    "canto-lending", "USDC", base=13.5, borrow_base=15.0),
        _p("Cronos",   "tectonic",      "USDC", base=2.0,  borrow_base=0.5,  borrow_reward=0.22),
        _p("Ethereum", "aave-v3",       "USDC", base=3.0,  borrow_base=4.0),
    ]
    rows = cross_chain_carry(pools)
    usdc = next(r for r in rows if r.symbol == "USDC")
    # best supply = Canto 13.5 ; cheapest net borrow = Cronos 0.5 - 0.22*(1-default_disc)
    # bucket B unknown default 12.5% discount -> 0.5 - 0.22*0.875 ≈ 0.3075
    assert usdc.supply_chain == "Canto"
    assert usdc.supply_apy == pytest.approx(13.5)
    assert usdc.borrow_chain == "Cronos"
    assert usdc.borrow_apr < 0.5
    assert usdc.spread > 12.0


def test_cross_chain_requires_different_chains():
    """If best supply and cheapest borrow are on the SAME chain, skip — that's a same-chain loop."""
    pools = [
        _p("Solana", "kamino-lend", "USDC", base=6.0, borrow_base=5.0),
    ]
    rows = cross_chain_carry(pools)
    # only one chain -> nothing
    assert rows == []


def test_cross_chain_skips_pools_missing_borrow_side():
    """Asset with no borrowable pool anywhere -> excluded."""
    pools = [
        _p("Ethereum", "yearn", "USDC", base=10.0, borrow_base=None),
        _p("Base",     "yearn", "USDC", base=8.0,  borrow_base=None),
    ]
    rows = cross_chain_carry(pools)
    assert rows == []
