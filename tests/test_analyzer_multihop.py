import pytest
from services.routes.analyzer import enumerate_multihop_paths, MultiHopPath


def _p(chain, project, symbol, base=0.0, borrow_base=None, ltv=0.80, tvl=5e6):
    return {"pool": f"{chain}-{project}-{symbol}", "chain": chain, "project": project,
            "symbol": symbol, "apyBase": base, "apyReward": 0.0,
            "apyBaseBorrow": borrow_base, "apyRewardBorrow": None,
            "ltv": ltv, "tvlUsd": tvl}


# Fixture graph: USDC@A earns 10%, can borrow ETH@A at 2% (ltv .80 -> per-iter .75),
# ETH supplies at 5% on chain B. Bridge maps allow it. Expected best 2-hop:
#   net = 1*10  - 0.75*2 + 0.75*5 = 12.25
POOLS = [
    _p("ChainA", "aave-v3", "USDC", base=10.0, borrow_base=4.0, ltv=0.80, tvl=4e6),
    _p("ChainA", "aave-v3", "WETH", base=0.5, borrow_base=2.0, ltv=0.80, tvl=3e6),
    _p("ChainB", "aave-v3", "WETH", base=5.0, borrow_base=3.0, ltv=0.80, tvl=2e6),
]
WMAP = {"USDC": {"ChainA"}, "ETH": {"ChainB"}, "USDT": set(), "BTC": set()}
DMAP = {"USDC": {"ChainA"}, "ETH": {"ChainA"}, "USDT": set(), "BTC": set()}
COSTS = {"ChainA": 0.10, "ChainB": 0.20}


def test_two_hop_path_found_with_hand_computed_metric():
    paths = enumerate_multihop_paths(POOLS, WMAP, DMAP, COSTS, capital_class="USDC")
    two = [p for p in paths if p.hops == 2]
    assert two, "expected a 2-hop path"
    best = two[0]
    assert best.nodes == (("ChainA", "aave-v3", "USDC"), ("ChainB", "aave-v3", "WETH"))
    assert best.net_apy == pytest.approx(12.25)      # 10 - .75*2 + .75*5
    assert best.bridge_cost_usd == pytest.approx(0.20)  # dest chain cost
    assert best.min_liquidity_usd == pytest.approx(2e6) # thinnest pool on the path
    assert best.entry_asset_class == "USDC"


def test_one_hop_root_is_emitted():
    paths = enumerate_multihop_paths(POOLS, WMAP, DMAP, COSTS, capital_class="USDC")
    ones = [p for p in paths if p.hops == 1]
    assert ones and ones[0].net_apy == pytest.approx(10.0)


def test_blocked_bridge_kills_the_hop():
    dmap = {"USDC": {"ChainA"}, "ETH": set(), "USDT": set(), "BTC": set()}  # can't deposit ETH
    paths = enumerate_multihop_paths(POOLS, WMAP, dmap, COSTS, capital_class="USDC")
    assert all(p.hops == 1 for p in paths)


def test_root_requires_binance_withdrawable_chain():
    wmap = {"USDC": set(), "ETH": {"ChainB"}, "USDT": set(), "BTC": set()}  # can't withdraw USDC anywhere
    paths = enumerate_multihop_paths(POOLS, wmap, DMAP, COSTS, capital_class="USDC")
    assert paths == []


def test_max_hops_respected_and_same_chain_dest_excluded():
    paths = enumerate_multihop_paths(POOLS, WMAP, DMAP, COSTS, capital_class="USDC", max_hops=1)
    assert all(p.hops == 1 for p in paths)
    # dest == source chain is never allowed (must actually move chains)
    full = enumerate_multihop_paths(POOLS, WMAP, DMAP, COSTS, capital_class="USDC")
    for p in full:
        chains = [n[0] for n in p.nodes]
        assert all(chains[i] != chains[i+1] for i in range(len(chains)-1))


def test_empty_maps_no_paths():
    assert enumerate_multihop_paths(POOLS, {}, {}, COSTS, capital_class="USDC") == []
