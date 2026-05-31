# Codee — Backlog

Tasks from Paul's feedback (`analise.md`, 30–31 May 2026) + findings from live-data validation.
Ordered by recommended priority. Status: `todo` unless noted.

---

## T0 — Symbol normalization (₮ glyph + variants) — **quick win, high impact**

**Status:** todo · **Effort:** small · **Priority:** 1

**Problem:** the symbol filter (`config/stable_symbols.json`, exact `.upper()` match) misses
pools whose ticker uses Tether's stylized glyph `₮` (U+20AE) or other unicode variants.
DefiLlama lists Tether as `USD₮` / `USD₮0`, which never equals `"USDT"` / `"USDT0"`.

**Impact (measured live, 31-mai-2026):** **16 lendable pools (tvl ≥ $10k) silently dropped**, incl:
- Xlayer `USD₮0` aave-v3 — **$49.3M** free liquidity
- Arbitrum `USD₮0` aave-v3 — $9.2M
- Celo `USD₮` aave-v3 — $2.19M  *(this is the leg in Paul's cross-chain route that we wrongly reported as "missing")*
- Hyperliquid `USD₮0` $5.1M, Ink `USD₮0` $5.1M, + 11 more

**Fix:** normalize symbols before matching — map `₮`→`T`, apply Unicode NFKD, strip to
ASCII alnum, uppercase. Apply in the ingestor's stable-symbol filter (and anywhere a pool
symbol is compared/grouped, e.g. cross-chain per-asset bucketing in `analyzer.py`). Keep the
ORIGINAL symbol for display; normalize only for matching/grouping.

**Tests:** `USD₮`→USDT matches; `USD₮0`→USDT0 matches; a genuinely non-stable symbol still
excluded; display symbol preserved.

---

## T1 — Asset filter on the tables (Paul: "filter by asset… look up usdc only")

**Status:** todo · **Effort:** small · **Priority:** 2

A symbol filter next to the liquidity slider, client-side, instant feedback (Paul liked the
slider's live feel). Passive/cross-chain filter by `symbol`; loops by `asset_x`/`asset_y`.
Hide on rewards/history sub-tabs (like the slider).

---

## T2 — Actionable-protocol whitelist / flag (kills non-vanilla "junk")

**Status:** todo · **Effort:** small–medium · **Priority:** 3

**Why:** Paul couldn't find the `peapods-finance` "USDC 507%" option on its UI — because
peapods isn't a plain lending deposit (leveraged pods); the 507% isn't an executable supply
APY. These pollute the radar. Add a project whitelist of "plain lending" protocols (or a flag
for non-vanilla ones) so the dashboard can default to actionable pools. Don't hard-delete —
flag + let the user toggle (consistent with "never silently drop").

---

## T3 — Starting-capital selector: USDC / USDT / ETH / BTC (Binance-withdrawable)

**Status:** todo · **Effort:** medium · **Priority:** 4 · needs a short design pass

Paul: "options to use USDC/USDT/ETH/BTC as starting capital that Binance offers withdrawal
options for." Two parts:
1. **Expand the universe beyond stablecoins** to include ETH/BTC families (live: 434 ETH-family
   + 251 BTC-family lendable pools exist in DefiLlama). New asset-class config, not just
   `stable_symbols`.
2. **Anchor routes to the chosen start asset** and constrain to Binance-withdrawable assets;
   the entry leg = that asset.

Design questions: price-risk framing for volatile collateral (this is the "delta-neutral
volatile-collateral loops" deferred to Phase 2 in CLAUDE.md). Brainstorm before building.

---

## T4 — Multi-hop cross-chain chains (Paul: "we're missing many options")

**Status:** todo · **Effort:** large · **Priority:** 5 · needs a dedicated spec

Today `cross_chain_carry` is **single-hop, same-asset, stablecoin-only**. Paul wants
multi-leg, cross-asset chains across N chains, e.g.:
> USDC@Sonic (supply 7.4%) → borrow WETH (0.36%) → bridge → WETH@Celo (supply) → borrow
> USD₮@Celo (1.9%) → bridge → USDT@Avax (supply 4.9%) → borrow BTC.B (0.12%) → continue.

Model: graph/pathfinding over `(chain, asset)` lending nodes, edges = borrow→bridge→supply;
roughly delta-neutral per asset (borrow X, re-supply X elsewhere). Requirements:
- **Reward-APY coverage** (see open question below — DefiLlama misses Aave Merit-type incentives).
- **Bridge-availability + cost model** (which chains/assets are bridgeable; ≤$1 gate is Phase 2).
- Handle missing legs gracefully; respect per-pool LTV / health-factor for leverage.

Phase 2/3 scope.

---

## Open question — confirm Celo WETH supply 4.2% (reward-coverage gap)

Paul's route lists "WETH on Aave Celo — 4.2%", but live sources disagree:
- DefiLlama: `apyBase=0.015%`, `apyReward=None`, `rewardTokens=None` — not present.
- Merkl (Celo): only LP campaigns (`USD₮-WETH` Uniswap/Ichi), **no Aave WETH supply incentive**.

So 4.2% isn't in any source we index. Most likely **Aave Merit** (off-chain/claimable
incentive shown on app.aave.com) — consistent with the documented "DefiLlama misses Aave
Merit" gap. **Action:** confirm via on-chain `UiIncentiveDataProvider` (Celo) or ask Paul
which screen; if real & systematic, it motivates a reward-coverage upgrade feeding T4.

**Note:** validation also confirmed our **borrow-side data is solid** — Paul's borrow rates
matched DefiLlama exactly (Sonic WETH 0.36%, Celo USD₮ 1.89%, Avax BTC.B 0.12%). The gaps are
on the **supply-incentive** side + symbol normalization (T0).
