from services.rewards.supply_incentives import overlay_supply_incentives
from services.rewards.merkl_match import build_rebate_lookup


def _pool(chain, project, symbol, apy_reward=None):
    return {"chain": chain, "project": project, "symbol": symbol,
            "apyBase": 1.0, "apyReward": apy_reward, "tvlUsd": 5e6}


def _lend_opp(chain, proto, symbol, apr):
    return {"chain": {"name": chain}, "protocol": {"id": proto},
            "tokens": [{"symbol": symbol}], "action": "LEND", "apr": apr}


def test_merkl_lend_raises_apy_reward():
    pools = [_pool("MegaETH", "aave-v3", "USDM")]
    lend = build_rebate_lookup([_lend_opp("MegaETH", "aave", "USDM", 4.88)])
    out = overlay_supply_incentives(pools, lend, {})
    assert out[0]["apyReward"] == 4.88
    assert out[0]["reward_source"] == "merkl_lend"


def test_aci_merit_plus_self_raises_apy_reward_and_flags_conditional():
    pools = [_pool("Celo", "aave-v3", "WETH")]
    aci = {("Celo", "WETH"): {"merit": 2.08, "self": 2.08}}
    out = overlay_supply_incentives(pools, {}, aci)
    assert out[0]["apyReward"] == 4.16            # merit + self summed within ACI
    assert out[0]["reward_source"] == "aci_merit"
    assert out[0]["incentive_conditional"] == 1   # self present -> gated


def test_overlap_takes_max_not_sum():
    pools = [_pool("Celo", "aave-v3", "WETH")]
    lend = build_rebate_lookup([_lend_opp("Celo", "aave", "WETH", 3.0)])
    aci = {("Celo", "WETH"): {"merit": 2.08, "self": 2.08}}   # 4.16 > 3.0
    out = overlay_supply_incentives(pools, lend, aci)
    assert out[0]["apyReward"] == 4.16            # max(3.0, 4.16), NOT 7.16


def test_existing_higher_defillama_reward_kept():
    pools = [_pool("Celo", "aave-v3", "WETH", apy_reward=9.0)]
    aci = {("Celo", "WETH"): {"merit": 2.08, "self": 2.08}}
    out = overlay_supply_incentives(pools, {}, aci)
    assert out[0]["apyReward"] == 9.0             # don't lower an existing reward
    assert out[0]["incentive_conditional"] == 1   # self still flags


def test_untouched_pool_unchanged():
    pools = [_pool("BSC", "venus-core-pool", "USDC")]
    out = overlay_supply_incentives(pools, {}, {})
    assert out[0]["apyReward"] is None
    assert "incentive_conditional" not in out[0]
