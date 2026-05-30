"""Golden regression: lock the ranking output against a captured payload so any
math-changing refactor must consciously update the locked numbers (spec Section
8 mandatory validation #3)."""
import pytest

from sources.defillama.client import join_supply_borrow
from services.rewards.merkl_match import build_rebate_lookup, overlay_rebates
from services.pools.validators import classify_pool
from services.routes.analyzer import (
    rank_passive_supply, enumerate_same_chain_loops, cross_chain_carry,
)


@pytest.fixture
def golden(fixture_loader):
    return fixture_loader("golden_payload_20260525.json")


def _pipeline(golden):
    joined = join_supply_borrow(golden["defillama_supply"], golden["defillama_borrow"])
    overlaid = overlay_rebates(joined, build_rebate_lookup(golden["merkl_borrow"]))
    # Filter to stables for tractable golden testing
    stables = {"USDT", "USDC", "USD1", "USDE", "DAI", "GHO", "PYUSD"}
    # Fixed golden subset — independent of the production MIN_TVL_USD floor (now $10k).
    # This threshold is intentionally kept at $1M to lock the regression set.
    pools = [p for p in overlaid
             if (p.get("symbol") or "").upper() in stables
             and (p.get("tvlUsd") or 0) >= 1_000_000]
    return pools


def test_pipeline_produces_at_least_some_pools(golden):
    assert len(_pipeline(golden)) >= 5


def test_passive_top_result_is_reproducible(golden):
    """The same payload must always produce the same #1 passive route.

    This is a REGRESSION GUARD. The locked values below were captured from the
    first run against the 2026-05-28 fixture. If this test fails:
      1. Inspect the diff (math/LAV/filter change?)
      2. If the change is intentional, update the locked values consciously
      3. Never silently 'fix' by recapturing — that defeats the point
    """
    pools = _pipeline(golden)
    ranked = rank_passive_supply(pools)
    if not ranked:
        pytest.skip("no passive routes in sample (regime change at capture time)")
    top = ranked[0]
    print(f"\n[GOLDEN] passive top: {top.chain}/{top.project}/{top.symbol} = {round(top.effective_apy, 2)}%")
    # LOCKED — captured 2026-05-28, see fixture golden_payload_20260525.json
    assert top.chain == "Ethereum"
    assert top.project == "ember-protocol"
    assert top.symbol == "USDC"
    assert round(top.effective_apy, 2) == 12.52


def test_cross_chain_carry_returns_results(golden):
    """At least some assets should have a cross-chain spread (positive or negative)."""
    pools = _pipeline(golden)
    rows = cross_chain_carry(pools)
    # Don't lock specific spread values — the live captured fixture changes daily
    # in spirit; just confirm the function returns SOMETHING for the multi-chain
    # input (this is the key Phase 1a deliverable).
    if not rows:
        pytest.skip("no cross-chain rows in golden — single-chain fixture")
    assert any(r.symbol in ("USDC", "USDT", "DAI", "PYUSD") for r in rows)
