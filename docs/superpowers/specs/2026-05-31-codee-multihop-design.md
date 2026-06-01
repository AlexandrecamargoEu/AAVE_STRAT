# Codee — Multi-hop cross-chain carry (Binance-routable paths)

**Date:** 2026-05-31
**Status:** design — pending spec review
**Origin:** Paul (`analise.md`, 31-mai): *"we're missing many options for the cross-chain"* + a 3-hop example (USDC@Sonic → borrow WETH → Celo → borrow USDT → Avax → borrow BTC.B…). Backlog item **T4**.

---

## Goal & scope

Surface **multi-hop cross-chain carry chains**: start with a Binance starting-capital asset on
chain C0, supply it, borrow another asset against it, **bridge that asset via Binance** to
another chain, supply it there, borrow again, … up to a depth cap, ending on a supply. Rank the
chains by the **net leveraged carry on the initial capital**.

Today's `cross_chain_carry` is single-hop, same-asset. This adds the N-hop, cross-asset graph.

### Confirmed decisions
- **Depth:** ≤ **3 hops** default (one supply leg per hop; configurable up to 4 via setting).
- **Assets:** every node's asset is one of the **4 Binance classes** (USDC/USDT/ETH/BTC) — they
  are the most-bridgeable/liquid and cover Paul's example (WETH=ETH, USDT, BTC.B=BTC). Reuses
  the T3 `asset_class` machinery. (Broadening to more bridgeable stables is a Phase-2 knob.)
- **Bridge model:** an edge exists only if Binance can bridge the borrowed asset — i.e.
  `depositEnable(asset, source_chain) AND withdrawEnable(asset, dest_chain)`. Cost = the dest
  chain's `bridge_cost_usd` (`config/chains.json`). Extends the T3 Binance client to also parse
  `depositEnable`.
- **Anchor:** root = the capital class chosen in the T3 selector (USDC/USDT/ETH/BTC), on a chain
  Binance can withdraw that class to (you withdraw your capital to C0).
- **Termination:** a chain ALWAYS ends on a supply (no open final borrow) — economically correct
  for carry (you only borrow if you redeploy) and avoids an open short.
- **Ranking metric:** net leveraged carry APY on the initial capital (see §3).
- **Framing:** a *theoretical ceiling* radar with loud caveats (bridge cost shown separately;
  per-leg health-factor risk; reward-coverage gap). No HF/liquidation modeling in the MVP.

**Out of scope (YAGNI):** non-Binance bridges; assets outside the 4 classes; per-leg HF /
liquidation simulation; on-chain RewardsController coverage / non-Aave incentive feeds;
execution. (Aave **Merit + Self** incentives ARE now in scope — added as a prerequisite source,
§0 — because that's where the Celo WETH "4.2%" lives and it materially changes route viability.)

---

## 0. Prerequisite — ACI Merit reward source (include Merit + Self incentives)

**Why:** the supply yields that drive route viability are understated whenever a pool has
off-protocol incentives (Aave **Merit** + **Self**) — these are NOT in DefiLlama (`apyReward=null`),
NOT in Merkl, and NOT in the on-chain RewardsController (verified: 0). They are exactly why Aave's
UI shows Celo WETH at **4.22%** while we read 0.017%. Found a free public feed that carries them,
so we ingest it and enrich effective supply APY **across all views** (passive/loops/cross-chain/
multi-hop). Do this **before** the pathfinding so multi-hop viability uses the real yields.

**Source:** `GET https://apps.aavechan.com/api/merit/aprs` (free, public, no key). Shape:
```
{"currentAPR": {"actionsAPR": {
   "celo-supply-weth": 2.08, "self-celo-supply-weth": 2.08,
   "celo-supply-usdt": 4.23, "self-celo-supply-usdt": 4.23,
   "ethereum-sgho": 3.76, ... }}}
```
Keys: `<chain>-supply-<asset>` = Merit APR; `self-<chain>-supply-<asset>` = Self APR. Currently
~7 non-null entries (sparse, targeted set). Verified live: Celo WETH = Merit 2.08 + Self 2.08
(+ protocol 0.02 ≈ 4.22, matches the Aave UI exactly).

**New module** `codee/sources/aci/client.py` (mirrors the Merkl client pattern: async ctx
manager, stubbable). Fetched each ingest tick (campaigns expire). A small `config/aci_chains.json`
maps ACI chain slugs → DefiLlama chain names (`celo→Celo, ethereum→Ethereum, avalanche→Avalanche,
arbitrum→Arbitrum, base→Base, optimism→OP Mainnet`). A pure `parse_merit_aprs(payload, chain_map)`
→ `{(chain, normalized_asset): {"merit": apr, "self": apr}}`.

**Applying it** (in `analyzer.effective_supply_apy`, via an overlay like Merkl's `overlay_rebates`):
- Add **Merit** APR to the pool's supply reward (claimable in aUSDT ≈ a stablecoin → bucket A,
  ~no LAV discount).
- Add **Self** APR too, but **tag it** `incentive_conditional=1` (gated on zkPoH verification +
  capped at the first $35k of supply per user). Default: included; the UI can offer a toggle to
  exclude gated incentives. Surface the split (protocol / Merit / Self) so the number is honest.
- Pools with no ACI entry are unchanged.

**Tests (offline):** `parse_merit_aprs` maps `celo-supply-weth`→`(Celo, WETH)` with merit+self;
unknown chain slugs ignored; the overlay raises a Celo WETH pool's effective supply from ~0.02%
to ~4.2% and sets `incentive_conditional` when Self is present; a pool with no ACI entry is
untouched; empty/failed fetch → no change (graceful).

---

## 1. The position model (how a hop works)

A lending hop happens **on one platform**: you supply asset A as collateral on platform `P`
at chain `C`, and borrow asset B **against it on the same platform `P@C`**, then bridge B to
another chain. So the data for a hop needs TWO pools on the same `(C, P)`:
- the **supply** pool `(C, P, A)` → its `effective_supply_apy` and its `ltv` (borrowing power of A);
- the **borrow** pool `(C, P, B)` → its `effective_borrow_apr` (cost of borrowing B).

This mirrors the existing `enumerate_same_chain_loops` indexing (`(project, asset) → pool`).

A **path** is a sequence of nodes `(C0,P0,A0) → (C1,P1,A1) → … → (Cn,Pn,An)` where:
- A0 ∈ chosen capital class; C0 ∈ Binance-withdrawable chains for A0's class.
- For each step i→i+1: `(Ci, Pi, A_{i+1})` exists (you can borrow A_{i+1} on Pi@Ci),
  A_{i+1} ∈ one of the 4 classes, Binance bridges A_{i+1} from Ci to C_{i+1}
  (`depositEnable(A_{i+1}, Ci) AND withdrawEnable(A_{i+1}, C_{i+1})`), and
  `(C_{i+1}, P_{i+1}, A_{i+1})` exists with a supply side.
- Final node `(Cn,Pn,An)` is a supply only (no further borrow).
- Chains/assets may repeat across hops only if it doesn't form a trivial cycle (no immediate
  back-and-forth to the exact same `(C,P,A)` node already in the path — prevents infinite loops;
  the depth cap also bounds it).

---

## 2. Graph + algorithm (`services/routes/analyzer.py`, PURE)

New pure function `enumerate_multihop_paths(pools, withdraw_map, deposit_map, *, max_hops=3,
capital_class=None) -> list[MultiHopPath]`.

- **Index:** `by_cp[(chain, project)][normalized_asset] = pool` (only pools whose asset is in a
  Binance class). A `(chain, project)` with both a supply pool for A and a (borrow-side) pool for
  B enables the hop A→B.
- **Roots:** every supply pool `(C0,P0,A0)` with `asset_class(A0)==capital_class` (or any class
  if `capital_class is None`) and `C0 ∈ withdraw_map[class(A0)]`.
- **DFS** from each root, depth ≤ `max_hops`, extending via valid bridge edges, recording the
  full path. At each depth ≥ 1 the current node is a valid terminal (supply-only) → emit the path.
- **Pruning:** skip an edge whose marginal carry is clearly negative if it can't be offset (keep
  simple for MVP: enumerate all within the cap, rank after — the 4-class graph is small). Cap the
  total emitted paths (e.g. top 200 by metric) and `log()` if truncated.
- Pure: no I/O. `withdraw_map`/`deposit_map` are passed in (built by the Binance source, §4).

---

## 3. Ranking metric — net leveraged carry on initial capital

Generalizes the same-chain loop math to a path. Initial capital `S0 = 1` (unit of A0).
- `per_iter_ltv_i = per_iter_ltv(supply_pool_i.ltv)` (platform LTV − 5% buffer; reuse analyzer).
- Position sizes: `S_{i+1} = S_i × per_iter_ltv_i` (the amount borrowed at hop i becomes the
  supply at hop i+1 — geometric decay).
- `net_carry = Σ_{i=0..n} S_i · eff_supply_i  −  Σ_{i=0..n-1} S_{i+1} · eff_borrow_i`
  where `eff_borrow_i` = effective borrow APR of asset A_{i+1} on `(Ci,Pi)`.
- Result = net APY on the initial capital (×100 for %). This is the ranking key (desc).
- **Bridge cost** (separate, NOT folded into APY — "pre-bridge ceiling"): `Σ bridge_cost_usd(C_{i+1})`
  for each hop, surfaced as a `$` column so the user judges whether N bridges eat the spread.
- **Min liquidity along path:** `min(available_liquidity)` (the `tvlUsd`) across all pools in the
  path — feeds the existing liquidity slider.

---

## 4. Bridge data — extend the Binance source

`capital/config/getall` already returns `depositEnable` per network alongside `withdrawEnable`.
- Add `build_deposit_chains(coin_list, network_map, classes)` (mirror of `build_withdrawable_chains`,
  keyed on `depositEnable`) → `{class: set(chains)}`.
- The ingestor writes BOTH maps to the cache JSON: `{"withdraw": {...}, "deposit": {...}}`
  (extend `binance_withdraw.json`; keep backward-compatible loading — old shape = withdraw-only).
- The router loads both; passes `withdraw_map` + `deposit_map` into `enumerate_multihop_paths`.
- Bridge feasible for asset B, Ci→C_{i+1}: `Ci ∈ deposit_map[class(B)] AND C_{i+1} ∈ withdraw_map[class(B)]`.

> Note: the per-class maps are keyed by the 4 classes (Binance base coins USDC/USDT/ETH/BTC),
> which is exactly the asset set multi-hop uses — so no new coin mapping is needed.

---

## 5. API + UI

- **API:** `GET /api/codee/routes/multihop?capital=<class>&max_hops=3&limit=50` → list of
  `MultiHopRoute`: `{path: [{chain, project, symbol}], net_apy, hops, bridge_cost_usd,
  min_liquidity_usd, entry_asset_classes}`. `capital` defaults to none (all classes);
  `entry_asset_classes` = `[class(A0)]` so the T3 Capital selector filters these rows too.
  (No `binance_withdrawable` field here — every emitted path is Binance-routable by construction,
  so the flag would be trivially true.)
- **UI:** new sub-tab **"Multi-Hop"** in the Codee tab. Each row renders the path compactly:
  `USDC·Sonic → ETH·Celo → USDT·Avax` (asset·chain per node, arrow-joined) + columns
  `Net APY`, `Hops`, `Bridge $`, `Liquidity`. Respects the liquidity slider (min_liquidity_usd)
  and the Capital selector (entry_asset_classes). A loud caveat line: *"theoretical ceiling —
  ignores bridge cost in APY (shown separately), per-leg liquidation risk, and unindexed supply
  incentives."*

---

## 6. Implementation target — which repo

Same split as prior Codee work:
- **Backend** (analyzer pathfinding + metric, Binance deposit-map extension, ingestor cache,
  API model + router endpoint) → `Volume_tracker/codee/…`, **mirrored** to `AAVE_STRAT/…`.
- **Frontend** (Multi-Hop sub-tab) → `Volume_tracker/web/index.html` only.
- Deploy via git-bundle; backend changed → **needs `systemctl restart`**.

---

## 7. Testing (offline, per project convention)

- **`enumerate_multihop_paths`:** a small hand-built fixture graph (3 chains, aave on each,
  classes USDC/ETH/USDT) with a known best path → assert the path sequence, that it terminates on
  a supply, respects `max_hops`, and excludes edges where the bridge map forbids
  deposit/withdraw. A no-bridge map → zero multi-hop paths (degrade).
- **carry metric:** a 2-hop path with known rates+LTV → assert `net_apy` equals the hand-computed
  geometric-decay value; `bridge_cost_usd` = sum of dest `bridge_cost_usd`; `min_liquidity_usd` =
  min across path pools.
- **deposit map:** `build_deposit_chains` parses `depositEnable` (mirror of the withdraw test);
  cache round-trips the `{"withdraw":..,"deposit":..}` shape; old withdraw-only shape still loads.
- **API:** `/routes/multihop` returns paths with the documented fields; `capital=ETH` filters
  roots to the ETH class; empty bridge maps → empty list (no crash).
- **Golden test:** unaffected (separate ranking path).
- **Frontend:** manual via `local_harness` — Multi-Hop tab renders paths; slider + capital filter
  apply; caveat shown.

---

## 8. Risk & honesty (must be visible in the UI)

The aggregate position is delta-neutral per bridged asset (borrow X, re-supply X elsewhere), BUT
**health factor is per-position**: if a borrowed asset's price moves, the specific leg that
borrowed it can be liquidated even though you hold that asset elsewhere — cross-chain neutrality
does NOT protect individual-leg HF. Combined with N bridge costs and the supply-incentive
coverage gap, the net APY is an **upper-bound radar number**, not an executable guarantee. The UI
must say this plainly (consistent with the existing cross-chain "pre-bridge ceiling" framing).
