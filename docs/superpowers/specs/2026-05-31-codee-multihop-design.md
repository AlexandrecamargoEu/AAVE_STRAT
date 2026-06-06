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
- **Depth:** backend enumerates ALL paths up to a **hard cap of 4 hops** (one supply leg per
  hop), once. The UI gets a **"Max hops" selector** `[All · 1 · 2 · 3 · 4]` (default **All**)
  that filters client-side on each route's `hops` field — instant, no recalculation, same
  pattern as the liquidity slider / Capital selector. The best route always shows regardless of
  its depth; selecting ≤N answers "best route if I only accept N positions". (This converts the
  former "3 vs 2 vs 4" open question into a per-user UI preference — Paul's answer just sets the
  default selection.)
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

### Key design questions — alternatives considered

Two questions defined the design; chosen option marked **[✓]** (open to revision on Paul's review).

**Q1 — What counts as a valid "hop" (how to move the borrowed asset between chains)?**
- **[✓] A. Binance-bridgeable only** — edge exists iff Binance allows *deposit* of the asset on
  the source chain AND *withdraw* on the dest chain; cost from `chains.json`. Executable +
  data-backed (reuses T3); **limits to Binance-supported assets/chains** (→ assets capped to the
  4 majors USDC/USDT/ETH/BTC). *Why chosen:* only bridge we can both price (≤~$1) and guarantee.
- **B. Any bridge (any asset/chain)** — borrow→move anywhere it exists. Much larger graph, exotic
  routes, but **no feasibility/cost data for non-Binance bridges** → theoretical/likely non-executable.
- **C. Hybrid (Binance OR same-token native bridge)** — also allow moving the asset to a chain
  where it's the same canonical token (assume native bridge). More coverage, but **bridge cost is
  imprecise** for the non-Binance edges.
- *Linked sub-decision (RESOLVED, data-grounded):* route assets stay restricted to the **4
  classes** at launch. Live check (Binance chains, ≥$100k liquidity legs): best cross-chain carry
  USDC **29.0%** / USDT **22.4%** vs DAI 5.0% / USDe 6.6% / USD1 5.8%; FDUSD/TUSD/PYUSD have **no
  viable pair at all**. Stables are fungible — majors are listed on every chain with the deepest
  pools, so for any chain pair there is almost always a major leg ≥ the niche-stable leg; adding
  niche stables would add worse variants, not new winners. It's a config list
  (`asset_classes.json`): **USDe/USD1 are the named watchlist** (only candidates with real carry +
  Binance listing) — add an entry if a recurring route beats the majors.

**Q2 — Where does the chain start, and what about the final borrowed asset (open = price risk)?**
- **[✓] A. Root = T3 capital class; end on a supply** — root = chosen capital (USDC/USDT/ETH/BTC,
  Binance-withdrawable); last hop only supplies (no borrow) → **no open position**. Clean/executable.
- **B. Root = T3 capital; free final borrow** — allow ending by borrowing any asset (like Paul's
  example ending in BTC.B). Captures "keep arbing" but **leaves an open short** → price risk (caveat).
- **C. Enumerate all roots** — don't anchor on T3; any bridgeable asset as a start. More routes,
  but loses the capital-selector integration and inflates the graph.
- *Linked sub-decision (RESOLVED):* backend computes up to a hard cap of **4 hops** once; the UI
  "Max hops" selector `[All·1·2·3·4]` filters client-side (default All — the best route always
  shows). Depth preference becomes a per-user UI choice, not an architecture decision; Paul's
  answer ("3 realistic, or 2 max?") just sets the default selection.

---

## 0. Prerequisite — supply-incentive coverage via TWO aggregators

**Why:** supply yields drive route viability, but DefiLlama (`apyReward`) misses a whole class of
incentives — off-protocol / merkle / conditional programs. Concretely, Aave's UI shows Celo WETH
at **4.22%** while we read 0.017% (verified: not in DefiLlama, not in our current Merkl pull, not
in the on-chain RewardsController = 0). Rather than integrate ~50 protocol APIs, we add **two
aggregators** (one API → many protocols) and enrich `effective_supply_apy` **across all views**
(passive/loops/cross-chain/multi-hop). Do this **before** the pathfinding so multi-hop viability
uses real yields. Both are free public JSON, no key, fetched each ingest tick (campaigns expire →
freshness matters; a hot 1-week incentive surfaces within ~1h).

### (A) Merkl — supply side (`action=LEND`)
We already consume Merkl for BORROW rebates (`codee/sources/merkl/client.py`). **Extend it to also
fetch supply incentives:** `GET https://api.merkl.xyz/v4/opportunities?action=LEND&status=LIVE&items=100&page=N`
(`SUPPLY` is invalid → 500; **LEND** is the supply action). One call returns ~100 live supply
incentives across **~17 protocols** (aave, morpho, euler, fluid, dolomite, gearbox, spectra,
curvance, …). Useful fields: `apr`, `maxApr`, `protocol.id`, `tokens[].symbol`, `chain.name`,
`tvl`, `latestCampaignStart`/`latestCampaignEnd` (campaign timing). Match to pools by the existing
Merkl key `(chain.name normalized, protocol.id, token.symbol)` — same join `merkl_match.py` already
does for borrow. Add a `fetch_supply_opportunities()` mirroring `fetch_borrow_opportunities()`
(paginated, `action=LEND`).

### (B) ACI Merit — Aave off-protocol (Merit + Self), which Merkl does NOT carry
`GET https://apps.aavechan.com/api/merit/aprs` (free, public, no key). Shape:
```
{"currentAPR": {"actionsAPR": {
   "celo-supply-weth": 2.08, "self-celo-supply-weth": 2.08,
   "celo-supply-usdt": 4.23, "self-celo-supply-usdt": 4.23,
   "ethereum-sgho": 3.76, ... }}}
```
Keys: `<chain>-supply-<asset>` = Merit APR; `self-<chain>-supply-<asset>` = Self APR. ~7 non-null
entries (sparse, Aave-specific). Verified live: Celo WETH = Merit 2.08 + Self 2.08 (+ protocol
0.02 ≈ 4.22, matches the Aave UI exactly). New module `codee/sources/aci/client.py` (mirrors the
Merkl client: async ctx manager, stubbable). A small `config/aci_chains.json` maps ACI chain slugs
→ DefiLlama chain names (`celo→Celo, ethereum→Ethereum, avalanche→Avalanche, arbitrum→Arbitrum,
base→Base, optimism→OP Mainnet`). Pure `parse_merit_aprs(payload, chain_map)` →
`{(chain, normalized_asset): {"merit": apr, "self": apr}}`.

### Applying both (overlay on `effective_supply_apy`, like Merkl's `overlay_rebates`)
- Add the **Merkl LEND** APR and the **ACI Merit** APR to the pool's supply reward (claimable
  tokens; stablecoin rewards → bucket A ~no LAV discount; non-stable reward tokens get the normal
  LAV discount). If both sources hit the same pool, take the **max** (don't double-count the same
  program surfaced twice), and `log()` the overlap.
- Add the **Self** APR too but **tag it** `incentive_conditional=1` (gated on zkPoH verification +
  capped at the first $35k/user). Default included; UI may offer a toggle to exclude gated.
- Surface the split (protocol / Merkl / Merit / Self) so the number is honest. Pools with no
  aggregator entry are unchanged (shown yield = floor; flag "may have incentives" is a later idea).

**Tests (offline):**
- Merkl LEND: a stubbed `action=LEND` page joins to the right pool by `(chain, protocol, symbol)`
  and raises its effective supply by the campaign APR; pagination stops on a short page.
- ACI: `parse_merit_aprs` maps `celo-supply-weth`→`(Celo, WETH)` with merit+self; unknown chain
  slugs ignored; the overlay raises a Celo WETH pool from ~0.02% to ~4.2% and sets
  `incentive_conditional` when Self is present.
- Overlap: a pool present in BOTH Merkl-LEND and ACI takes the max (no double-count).
- A pool in neither is untouched; empty/failed fetch from either source → no change (graceful).

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

New pure function `enumerate_multihop_paths(pools, withdraw_map, deposit_map, *, max_hops=4,
capital_class=None) -> list[MultiHopPath]`. `max_hops=4` is the hard cap — the UI depth selector
filters client-side on the returned `hops` field (no recompute). If request-time enumeration at
depth 4 proves slow, cache the result per ingest tick (same pattern as the Binance withdraw map);
decide in the plan after measuring.

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

- **API:** `GET /api/codee/routes/multihop?capital=<class>&limit=50` → list of
  `MultiHopRoute`: `{path: [{chain, project, symbol}], net_apy, hops, bridge_cost_usd,
  min_liquidity_usd, entry_asset_classes}`. Always enumerated to the hard cap (4); each route
  carries its `hops` count so the client filters depth locally. `capital` defaults to none (all
  classes); `entry_asset_classes` = `[class(A0)]` so the T3 Capital selector filters these rows
  too. (No `binance_withdrawable` field here — every emitted path is Binance-routable by
  construction, so the flag would be trivially true.)
- **UI:** new sub-tab **"Multi-Hop"** in the Codee tab. Each row renders the path compactly:
  `USDC·Sonic → ETH·Celo → USDT·Avax` (asset·chain per node, arrow-joined) + columns
  `Net APY`, `Hops`, `Bridge $`, `Liquidity`. Filter row gains a **"Max hops" selector**
  `[All · 1 · 2 · 3 · 4]` (default All) filtering client-side on `hops` — instant, like the
  liquidity slider; the best route always shows regardless of depth. Also respects the liquidity
  slider (min_liquidity_usd) and the Capital selector (entry_asset_classes). A loud caveat line:
  *"theoretical ceiling — ignores bridge cost in APY (shown separately), per-leg liquidation
  risk, and unindexed supply incentives."*

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
