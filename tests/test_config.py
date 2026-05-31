from config.config import (
    settings, load_stable_symbols, load_lav_buckets,
    load_chains, load_projects,
)


def test_settings_defaults_load():
    assert settings.MIN_TVL_USD == 10_000
    assert settings.SNAPSHOT_INTERVAL_MIN == 60
    assert settings.STALENESS_BANNER_HOURS == 3


def test_stable_symbols_contains_majors():
    s = load_stable_symbols()
    for sym in ("USDT", "USDC", "DAI", "USD1", "USDE", "GHO"):
        assert sym in s


def test_lav_buckets_well_formed():
    lav = load_lav_buckets()
    assert lav["default_bucket"] == "B"
    assert lav["buckets"]["A"]["discount_pct"] == 0.0
    assert "AAVE" in lav["buckets"]["A"]["tokens"]
    assert "XVS" in lav["buckets"]["B"]["tokens"]


def test_chains_eth_and_tron_not_excluded():
    """Per spec 2b.I (Paul 28-mai)."""
    chains = load_chains()["chains"]
    assert chains["Ethereum"]["excluded"] is False
    assert chains["Tron"]["excluded"] is False
    assert chains["BSC"]["bridge_cost_usd"] == 0.29


def test_projects_has_aave_and_venus():
    p = load_projects()
    assert p["aave-v3"]["primary_reward"] == "AAVE"
    assert p["venus-core-pool"]["primary_reward"] == "XVS"


def test_normalize_symbol_maps_tether_glyph_and_uppercases():
    from config.config import normalize_symbol
    # Tether's stylized ₮ (U+20AE) -> T, so DefiLlama's USD₮ / USD₮0 match our stable list
    assert normalize_symbol("USD₮") == "USDT"
    assert normalize_symbol("USD₮0") == "USDT0"
    assert normalize_symbol("usdc") == "USDC"
    # punctuation in legit tickers must be preserved (USDC.E / BTC.B are real symbols)
    assert normalize_symbol("USDC.E") == "USDC.E"
    assert normalize_symbol("BTC.B") == "BTC.B"
    assert normalize_symbol(None) == ""
    assert normalize_symbol("") == ""
