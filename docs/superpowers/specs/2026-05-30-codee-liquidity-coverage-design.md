# Codee — Liquidity filter: surface thin-liquidity pools behind an adjustable slider

**Date:** 2026-05-30
**Status:** design — approved, pending spec review
**Origin:** Alexandre noticed the Aave **Sonic Market** (USDC) was absent from the Loops/Passive views. Root cause: the $1M TVL gate silently drops it. Decision: replace the hard gate with a user-controllable liquidity slider so the filter stops being "too restrictive."

---

## Problem

The ingestor scope filter (`services/pools/ingestor.py::_filter`) drops any pool whose
`tvlUsd < MIN_TVL_USD` (= **$1,000,000**) before it ever reaches the analyzer.

Two things were discovered validating against live DefiLlama data:

1. **DefiLlama's `tvlUsd` for a lending pool is *available liquidity* (supplied − borrowed), not market size.** The Aave Sonic USDC pool has **$3.51M supplied / $3.21M borrowed → $0.28M free** (`tvlUsd = $0.28M`, UR ≈ 91%). It's a real, sizable market with thin free liquidity — but the $1M gate treats the $0.28M free figure as "too small" and drops it.

2. **Silently dropping violates the project convention** (`CLAUDE.md`: *"Never silently drop a pool — flag and surface it"*). The gate hides real opportunities instead of surfacing them, and the threshold is hard-coded — the user has no control.

Naively removing the gate floods the UI: the stable+lendable universe is **909 pools**, most of them dust. The fix is a low dust floor + an **adjustable slider** the user controls, defaulting to a sensible value.

### Live counts (2026-05-30, captured during design)

| Free liquidity (`tvlUsd`) | Pools (cumulative ≥) |
|---|---|
| ≥ $100k | 209 |
| ≥ $50k | 237 |
| **≥ $10k (dust floor)** | **323** |
| total (no floor) | 909 |

Sonic Aave USDC ($0.28M free) survives every threshold above → appears, as intended.

---

## Design (simple — it's just a better filter control)

### 1. Backend — replace the hard gate with a low dust floor

`services/pools/ingestor.py::_filter`:
- Keep the stablecoin-symbol filter and the chain-exclusion filter unchanged.
- Change the TVL filter from a "$1M scope gate" to a **dust floor**: drop only pools with
  `tvlUsd < MIN_TVL_USD`, default lowered **$1,000,000 → $10,000**.
- This is a config default change (`config/config.py`, `MIN_TVL_USD`). The floor is the
  absolute minimum stored, and the lower bound of the slider. Everything ≥ $10k is stored
  (323 pools today); pure dust (< $10k) stays dropped.

### 2. Backend — expose available liquidity

- The merged pool dict already carries `totalSupplyUsd` and `totalBorrowUsd` (from the
  `/lendBorrow` join). Compute `available_liquidity_usd = totalSupplyUsd − totalBorrowUsd`.
- Add `available_liquidity_usd` (nullable float) to the API response models for the
  passive, loops, and cross-chain endpoints (`services/api/models.py`), populated from the
  stored snapshot fields. `analyzer.py` stays pure (just the subtraction / passthrough,
  no I/O).
- For loops, the relevant figure is the **borrow-leg** pool's available liquidity (the leg
  that draws on free liquidity); surface that on the loop result.

### 3. Frontend — adjustable liquidity slider + plain column (VT native CSS)

In Volume_tracker `web/index.html`, Codee tab (Passive / Loops / Cross-Chain):
- A **minimum-liquidity slider** styled like a price-range filter, range **$10k → max**
  (max = the largest pool's free liquidity, or a sensible cap), **default $100k**.
  - Default view shows only pools with free liquidity **> $100k** (209 today).
  - Dragging down toward $10k reveals thinner pools (up to 323); dragging up tightens.
  - Filtering is **client-side** over the already-loaded payload (323 pools is small).
- A plain **Liquidez** column showing `available_liquidity_usd` (e.g. `$0.28M`) — **no color
  coding** — so the user sees where each pool sits relative to the slider.
- For loops, the slider filters on the **borrow-leg** available liquidity.

### 4. Keep `high_utilization` (UR > 92%) flag

Orthogonal structural signal, unchanged in `validators.py`.

---

## Explicitly dropped (from the earlier draft of this spec)

- ❌ Position-relative **coverage** metric (liquidity ÷ position).
- ❌ Green / amber / red **color legend** (5× / 2× bands).
- ❌ Collapsible "low-liquidity tail" toggle.

The slider replaces all three with one simple, user-controllable filter. (Kept the field
`available_liquidity_usd` and the dust-floor idea; everything else is simplified away.)

## Out of scope (YAGNI)

- No new `QualityFlag` enum value.
- No staking-yield ingestion (the Sonic stS/S LST loop stays invisible — separate concern).
- No change to the History tab / `strategy_history`, bridge costs, or execution.

---

## Implementation target — which repo

The code exists in two places:
- **`F:\codefee\AAVE_STRAT`** — standalone, on GitHub. Its `web/index.html` is the
  discarded standalone amber UI (NOT used in production).
- **`F:\codefee\Volume_tracker\codee`** — the integrated package, **deployed to production**
  (`199.247.3.163`). Frontend lives in VT's `web/index.html` (native styling).

**Decision:** implement in **`Volume_tracker`** (the deployed copy):
- Backend → `Volume_tracker/codee/{config,services}/...`
- Frontend → `Volume_tracker/web/index.html` (Codee tab).

Mirror the **backend** changes (filter, config default, API field, analyzer passthrough)
back into **`AAVE_STRAT`** to keep the standalone repo in sync. The frontend change does
**not** mirror (AAVE_STRAT's standalone UI is dead). Deploy via the same git-bundle path
used for the integration.

---

## Testing

- **ingestor `_filter`:** `tvlUsd = $8k` dropped; `$10k` kept (`>=` boundary); `$50M` kept.
  Stable-symbol and chain-exclusion filters unchanged.
- **API models:** `available_liquidity_usd = totalSupplyUsd − totalBorrowUsd`; null when
  either input is null; loop result carries the borrow-leg figure.
- **analyzer purity:** the subtraction is pure, no I/O — one new case asserting the field
  flows through ranking output.
- **Golden regression** (`test_golden.py`): the new field + the now-included sub-$1M pools
  change the locked payload — regenerate and review the diff.
- **Frontend:** manual check via `local_harness.py` (port 8011) — slider at default hides
  ≤$100k pools, dragging to $10k reveals Sonic USDC; Liquidez column renders, no colors.
- All backend tests offline against fixtures, per project convention.
