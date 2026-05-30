# Codee — Liquidity coverage: surface thin-liquidity pools instead of dropping them

**Date:** 2026-05-30
**Status:** design — approved, pending spec review
**Origin:** Alexandre noticed the Aave **Sonic Market** (USDC) was absent from the Loops/Passive views. Root cause: the $1M TVL gate silently drops it. Decision: stop silently dropping, and add a position-relative liquidity signal.

---

## Problem

The ingestor scope filter (`services/pools/ingestor.py::_filter`) drops any pool whose
`tvlUsd < MIN_TVL_USD` (= **$1,000,000**) before it ever reaches the analyzer.

Two things were discovered validating against live DefiLlama data:

1. **DefiLlama's `tvlUsd` for a lending pool is *available liquidity* (supplied − borrowed), not market size.** The Aave Sonic USDC pool has **$3.51M supplied / $3.21M borrowed → $0.28M free** (`tvlUsd = $0.28M`, UR ≈ 91%). It's a real, sizable market with thin free liquidity — but the $1M gate treats the $0.28M free figure as "too small" and drops it.

2. **Silently dropping violates the project convention** (`CLAUDE.md`: *"Never silently drop a pool — flag and surface it"*). The gate hides real opportunities (and their exit risk) instead of surfacing them.

But naively removing the gate floods the UI: the stable+lendable universe is **909 pools**, of which **672 have < $50k free liquidity** (dead/dust pools). That buries the signal.

### Live counts (2026-05-30, captured during design)

| Free liquidity (`tvlUsd`) | Pools |
|---|---|
| > $1M | 110 |
| $250k–$1M | 64 |
| $100k–$250k | (part of below) |
| < $50k | 672 |
| **≥ $100k (chosen floor)** | **209** |
| < $100k (dropped as dust) | 700 |

Sonic Aave USDC ($0.28M free) **survives** the $100k floor → appears, as intended.

---

## The metric: liquidity coverage, not absolute liquidity

Absolute free liquidity is meaningless without position size. The right signal is
**coverage = available_liquidity / position_size** — how many times over you can exit.

- **≥ 5×** → 🟢 green — exit comfortably even if liquidity tightens or others exit with you
- **2× – 5×** → 🟡 amber — fits, but exit may be slow / slippy if utilization spikes
- **< 2×** → 🔴 red — you barely fit (or don't) in the free liquidity; real exit risk

**Rationale for the bands:** free liquidity is the most volatile quantity in a lending
pool (it's what's left after borrows, and borrows/withdrawals move constantly). At 1×
you exactly fill the free liquidity — pulling out pushes UR toward 100%, the rate model
spikes, and you wait for borrowers to repay. 2× lets you exit after half the free
liquidity is taken by others; 5× is real comfort. (Alexandre's own gut example — $50k
position wanting ~$300k liquidity = 6× — lands squarely in green, confirming calibration.)

**Coverage is position-relative and computed client-side**, using the principal the user
already controls in the dashboard. It re-colors live as the principal changes — no fixed
capital assumption. There is **no new server-side quality flag**; the server only exposes
the raw `available_liquidity_usd`.

**For loops**, the relevant position is the **total borrowed against the borrow-leg pool**
(the borrow leg draws on that pool's free liquidity, and unwinding repays then withdraws) —
not the principal. So the loop table colors coverage =
`borrow_leg_available_liquidity / total_borrowed`, where
`total_borrowed = principal × (leverage − 1)` (the cumulative debt the loop opens against
the borrow-side pool).

---

## Design

### 1. Backend — replace the scope gate with a dust floor

`services/pools/ingestor.py::_filter`:
- Keep the stablecoin-symbol filter and the chain-exclusion filter unchanged.
- Change the TVL filter semantics from "$1M scope gate" to a **dust floor**: drop only
  pools with `tvlUsd < MIN_TVL_USD` where `MIN_TVL_USD` default is lowered **$1,000,000 → $100,000**.
- This is a config default change (`config/config.py`, `MIN_TVL_USD`), no new field.

### 2. Backend — expose available liquidity

- The merged pool dict already carries `totalSupplyUsd` and `totalBorrowUsd` (from the
  `/lendBorrow` join). Compute `available_liquidity_usd = totalSupplyUsd − totalBorrowUsd`
  and persist/surface it.
- Add `available_liquidity_usd` (nullable float) to the API response models for the
  passive, loops, and cross-chain endpoints (`services/api/models.py`), populated by
  `analyzer.py` / the router from stored snapshot fields.
- `analyzer.py` stays pure — it just passes through / computes the subtraction; no I/O.

### 3. Frontend — "Liquidez" column colored by coverage (VT native CSS)

In Volume_tracker `web/index.html`, Codee tab (sub-tabs Passive / Loops / Cross-Chain):
- Add a **Liquidez** column rendering `available_liquidity_usd` (e.g. `$0.28M`).
- Color the cell by coverage vs the current position input: 🟢 ≥5× / 🟡 2–5× / 🔴 <2×.
  - Passive & Cross-Chain: coverage = `available_liquidity_usd / principal`.
  - Loops: coverage = `borrow_leg_available_liquidity / loan_size_per_loop`.
- Use VT's existing palette (no new standalone styling — see memory `feedback-vt-native-styling`).

### 4. Frontend — collapse the illiquid tail (anti-pollution, no silent drop)

- Rows that are 🔴 (<2× at the current position) are **collapsed behind a toggle**:
  `"+N pools de baixa liquidez"`. Default view shows green/amber only.
- Because coverage is position-relative, the hidden set re-computes live as the principal
  changes (tiny position → almost everything green/visible; large position → more hidden).
- Nothing is dropped from the payload — collapsed rows are one click away.

### 5. Keep `high_utilization` (UR > 92%) flag

Orthogonal structural signal (pool-level tightness), independent of the user's position.
Left exactly as-is in `validators.py`.

---

## Out of scope (YAGNI)

- No new `QualityFlag` enum value (coverage is client-side & position-relative).
- No staking-yield ingestion (the Sonic stS/S LST loop remains invisible — separate concern).
- No change to the History tab / `strategy_history`.
- No bridge-cost / cross-chain execution changes.

---

## Implementation target — which repo

The code exists in two places:
- **`F:\codefee\AAVE_STRAT`** — standalone, on GitHub. Its `web/index.html` is the
  discarded standalone amber UI (NOT used in production).
- **`F:\codefee\Volume_tracker\codee`** — the integrated package, **deployed to production**
  (`199.247.3.163`). Frontend lives in VT's `web/index.html` (native styling).

**Decision:** implement in **`Volume_tracker`** (the deployed copy):
- Backend changes → `Volume_tracker/codee/{config,services}/...`
- Frontend changes → `Volume_tracker/web/index.html` (Codee tab).

Mirror the **backend** changes (ingestor filter, config default, API field, analyzer
passthrough) back into **`AAVE_STRAT`** to keep the standalone repo in sync. The frontend
change does **not** mirror (AAVE_STRAT's standalone UI is dead). Deploy to production via
the same git-bundle path used for the integration.

---

## Testing

- **`test_filter` / ingestor:** a pool with `tvlUsd = $80k` is dropped; `$120k` is kept;
  `$50M` kept. Boundary at exactly `$100k` (kept, `>=`). Stable + chain filters unchanged.
- **API models:** `available_liquidity_usd = totalSupplyUsd − totalBorrowUsd`; null when
  either input is null.
- **analyzer purity:** the subtraction is pure, no I/O — covered by existing analyzer tests
  + one new case asserting the field flows through ranking output.
- **Golden regression** (`test_golden.py`): the new field changes the locked payload —
  regenerate and review the diff (only the added field + the now-included sub-$1M pools
  should appear).
- All tests offline against fixtures, per project convention.
