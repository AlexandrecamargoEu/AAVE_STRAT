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


def test_per_leg_rates_exposed():
    paths = enumerate_multihop_paths(POOLS, WMAP, DMAP, COSTS, capital_class="USDC")
    best = [p for p in paths if p.hops == 2][0]
    assert len(best.supply_apys) == 2
    assert best.supply_apys[0] == pytest.approx(10.0)
    assert best.supply_apys[1] == pytest.approx(5.0)
    assert len(best.borrow_legs) == 1
    assert best.borrow_legs[0][0] == "WETH"
    assert best.borrow_legs[0][1] == pytest.approx(2.0)


def test_same_symbol_pools_collapse_to_best_supply():
    # duplicate ChainB aave-v3 WETH with much better supply -> it must win the node
    pools = POOLS + [_p("ChainB", "aave-v3", "WETH", base=50.0, borrow_base=9.0, ltv=0.80, tvl=1e6)]
    paths = enumerate_multihop_paths(pools, WMAP, DMAP, COSTS, capital_class="USDC")
    two = [p for p in paths if p.hops == 2]
    assert two[0].net_apy == pytest.approx(10 - 0.75 * 2 + 0.75 * 50)   # 46.0
    # exactly ONE route per node id (no duplicate-pool ghost routes)
    assert len([p for p in two if p.nodes[-1] == ("ChainB", "aave-v3", "WETH")]) == 1


def test_borrow_leg_uses_cheapest_pool():
    # second WETH@ChainA pool with cheaper borrow -> borrow leg must use 1.0 not 2.0
    pools = POOLS + [_p("ChainA", "aave-v3", "WETH", base=0.1, borrow_base=1.0, ltv=0.80)]
    paths = enumerate_multihop_paths(pools, WMAP, DMAP, COSTS, capital_class="USDC")
    best = [p for p in paths if p.hops == 2][0]
    assert best.borrow_legs[0][1] == pytest.approx(1.0)
    assert best.net_apy == pytest.approx(10 - 0.75 * 1 + 0.75 * 5)      # 13.0


def test_limit_reserves_slots_per_depth():
    # two 2-hop routes (13.0 via ChainC, 12.25 via ChainB) both beat the 10.0 root;
    # with limit=2 the old global top-N would return ONLY 2-hops — the per-depth
    # quota must still surface the best 1-hop.
    pools = POOLS + [_p("ChainC", "aave-v3", "WETH", base=6.0, borrow_base=3.0)]
    wmap = {"USDC": {"ChainA"}, "ETH": {"ChainB", "ChainC"}, "USDT": set(), "BTC": set()}
    paths = enumerate_multihop_paths(pools, wmap, DMAP, COSTS, capital_class="USDC", limit=2)
    assert len(paths) == 2
    assert {p.hops for p in paths} == {1, 2}
    assert paths[0].net_apy >= paths[1].net_apy        # still net-desc overall


def test_limit_is_a_hard_cap_even_across_depths():
    # 1-, 2- and 3-hop routes all exist; limit=2 must return EXACTLY 2 rows
    # (depth quota fills one per level, then the final cut enforces the cap).
    # 3-hop route: USDC@ChainA -> borrow WETH@ChainA -> ChainB -> supply WETH@ChainB
    #              -> borrow USDC@ChainB -> ChainC -> supply USDC@ChainC
    pools = POOLS + [
        _p("ChainB", "aave-v3", "USDC", base=0.5, borrow_base=2.5),  # enables hop 3 borrow leg
        _p("ChainC", "aave-v3", "USDC", base=8.0, borrow_base=3.0),  # hop 3 supply destination
    ]
    wmap = {"USDC": {"ChainA", "ChainC"}, "ETH": {"ChainB"}, "USDT": set(), "BTC": set()}
    dmap = {"USDC": {"ChainA", "ChainB"}, "ETH": {"ChainA"}, "USDT": set(), "BTC": set()}
    paths = enumerate_multihop_paths(pools, wmap, dmap, COSTS, capital_class="USDC")
    assert any(p.hops == 3 for p in paths), "fixture must produce a 3-hop route"
    capped = enumerate_multihop_paths(pools, wmap, dmap, COSTS, capital_class="USDC", limit=2)
    assert len(capped) == 2
