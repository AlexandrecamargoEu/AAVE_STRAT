from services.rewards.merkl_match import build_rebate_lookup, overlay_rebates


SAMPLE_OPPS = [
    {
        "chain": {"name": "Mantle"},
        "protocol": {"id": "aave"},
        "tokens": [{"symbol": "USDC"}],
        "action": "BORROW",
        "apr": 1.37,
    },
    {
        "chain": {"name": "Ethereum"},
        "protocol": {"id": "aave"},
        "tokens": [{"symbol": "USDC"}],
        "action": "BORROW",
        "apr": 1.75,
    },
]


def test_build_rebate_lookup_keys_normalized():
    rebates = build_rebate_lookup(SAMPLE_OPPS)
    # chain lowercased, protocol id lowercased, asset uppercased
    assert rebates[("mantle", "aave", "USDC")] == 1.37
    assert rebates[("ethereum", "aave", "USDC")] == 1.75


def test_overlay_rebates_matches_protocol_prefix():
    """DefiLlama project 'aave-v3' must match Merkl protocol 'aave'."""
    pools = [
        {"chain": "Mantle", "project": "aave-v3", "symbol": "USDC",
         "apyBaseBorrow": 3.31, "apyRewardBorrow": None},
    ]
    rebates = build_rebate_lookup(SAMPLE_OPPS)
    overlaid = overlay_rebates(pools, rebates)
    assert overlaid[0]["apyRewardBorrow"] == 1.37
    assert overlaid[0]["reward_source_borrow"] == "merkl"


def test_overlay_preserves_existing_defillama_rebate_when_higher():
    """If DefiLlama already reports a borrow rebate, we don't downgrade it."""
    pools = [
        {"chain": "Mantle", "project": "aave-v3", "symbol": "USDC",
         "apyBaseBorrow": 3.31, "apyRewardBorrow": 2.50},
    ]
    rebates = build_rebate_lookup(SAMPLE_OPPS)
    overlaid = overlay_rebates(pools, rebates)
    # max(existing=2.50, merkl=1.37) = 2.50
    assert overlaid[0]["apyRewardBorrow"] == 2.50


def test_overlay_no_match_leaves_pool_alone():
    pools = [{"chain": "Solana", "project": "kamino-lend", "symbol": "USDC",
              "apyBaseBorrow": 5.0, "apyRewardBorrow": None}]
    rebates = build_rebate_lookup(SAMPLE_OPPS)
    overlaid = overlay_rebates(pools, rebates)
    assert overlaid[0]["apyRewardBorrow"] is None
