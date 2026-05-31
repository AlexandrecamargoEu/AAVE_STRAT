# Codee — Starting-capital anchor (USDC/USDT/ETH/BTC, Binance-withdrawable)

**Date:** 2026-05-31
**Status:** design — pending spec review
**Origin:** Paul (`analise.md`, 30-mai): *"options to use USDC / USDT / ETH / BTC as starting
capital that Binance offers withdrawal options for."* Backlog item **T3**.

---

## Goal & scope

Let the user pick the **asset they start with on Binance** (USDC / USDT / ETH / BTC) and see
only the routes that **enter** with that asset on a chain Binance can actually **withdraw to**.

This is the **anchor** approach (chosen over a new dedicated "deploy capital" view): a selector
that filters the existing Passive / Loops / Cross-Chain views. Rationale: the expensive,
valuable foundation — expanding the universe to ETH/BTC and modeling Binance-withdrawability —
is shared by both approaches; a unified cross-strategy ranked list (the "new view") needs a
common net-return metric that overlaps with T4 (multi-hop) and is deferred as a fast-follow.

**In scope:** asset-class config, universe expansion to ETH/BTC, a signed Binance
withdraw-networks source, a per-route `binance_withdrawable` flag, and a frontend anchor
selector + withdrawable toggle.

**Out of scope (YAGNI):** price-risk / delta-neutral modeling for volatile collateral (holding
ETH is the user's own capital choice; loops already surface leverage). A small "volatile
collateral" visual note on ETH/BTC routes is the only nod to it. No new "deploy capital" view.
No multi-hop (T4).

---

## 1. Asset classes (`codee/config/asset_classes.json`)

The four Binance starting-capital classes → the **normalized** on-chain tickers you actually
receive when withdrawing that asset (native + per-chain wrapped). LSTs/derivatives are excluded
(you don't withdraw wstETH/cbBTC-as-yield from Binance).

```json
{
  "USDC": ["USDC", "USDC.E", "USDC.B"],
  "USDT": ["USDT", "USDT0"],
  "ETH":  ["ETH", "WETH"],
  "BTC":  ["BTC", "WBTC", "BTCB", "BTC.B", "CBBTC"]
}
```

Helper in `config/config.py`:
```python
def asset_class(symbol: str | None) -> str | None:
    """Return the Binance starting-capital class for a ticker, or None.
    Matches on the normalized symbol (reuses normalize_symbol from T0)."""
```
Tickers are compared via `normalize_symbol` (so `USD₮`→USDT→USDT class, etc.).

> Note: the broad stablecoin universe (DAI, FRAX, GHO, …) stays ingested as today — those are
> valid legs *within* routes, but only the 4 classes are selectable starting capital, per Paul.

---

## 2. Universe expansion (`codee/services/pools/ingestor.py::_filter`)

Today the symbol gate is `normalize_symbol(sym) in stables`. Widen it:
```python
if normalize_symbol(sym) not in stables and asset_class(sym) is None:
    continue
```
i.e. keep a pool if it's a stablecoin (as today) **or** belongs to an ETH/BTC class. ETH/BTC
pools now flow through ingestion, snapshot, and all three analyzer views. The $10k dust floor
and chain-exclusion filters are unchanged.

---

## 3. Binance withdraw-networks source (`codee/sources/binance/client.py`)

A small signed client for `GET /sapi/v1/capital/config/getall` (HMAC-SHA256 over the query with
`timestamp`/`recvWindow`, `X-MBX-APIKEY` header).

- **Credentials:** read `BI_API_KEY` / `BI_API_SECRET` from the environment via `os.getenv`
  (the SAME vars Volume_tracker already uses — see VT `config/config.py:89-90`). Codee does NOT
  import VT code; it only reads the shared env, preserving package isolation. If the vars are
  absent, the source no-ops (returns an empty map) and the gate degrades gracefully (everything
  treated as "unknown", not hidden — see §4).
- **Parse:** for each coin in the response, collect `networkList` entries with
  `withdrawEnable == true` → `{coin: [binance_network_code, ...]}`. Keep only the coins we care
  about (USDC, USDT, ETH, BTC).
- **Network → chain mapping** (`codee/config/binance_networks.json`): Binance network codes →
  DefiLlama chain names, e.g. `{"ETH":"Ethereum","ARBITRUM":"Arbitrum","BSC":"BSC",
  "MATIC":"Polygon","BASE":"Base","OPTIMISM":"OP Mainnet","AVAXC":"Avalanche", ...}`. Codes with
  no mapping are ignored (logged once).
- **Output:** `withdrawable_chains: dict[class -> set[chain]]`, e.g.
  `{"USDC": {"Ethereum","Arbitrum","Base",...}, "ETH": {...}, ...}`.
- **Cadence:** fetched once per ingest tick (60-min loop) alongside DefiLlama/Merkl; the result
  is cached in memory and persisted to the snapshot path of the gate (see §4). Capital-config
  changes rarely, so a per-tick refresh is ample and cheap.

---

## 4. Backend — `binance_withdrawable` flag per route

For each route, the **entry (asset, chain)** must be Binance-withdrawable:
- **Passive:** entry = `(class(symbol), chain)`.
- **Cross-chain:** entry = `(class(supply symbol), supply_chain)` — you withdraw the asset and
  supply it on the supply chain.
- **Loops:** entry = `(class(asset_x or asset_y), chain)` — withdrawable if *either* leg asset's
  class can reach the loop's chain (you can start the ping-pong from whichever leg is reachable).

Compute `binance_withdrawable: bool | None` = `entry_chain in withdrawable_chains[entry_class]`.
- `None` (unknown) when the entry asset isn't one of the 4 classes, or when the Binance map is
  empty (no creds / fetch failed) — never silently hide; render as "—".
- Add `binance_withdrawable` (nullable bool) to `PassiveRoute`, `LoopRoute`, `CrossChainRoute`.
  The analyzer stays pure: the gate is computed in the router/ingestor layer (which has the
  Binance map), passed into the route objects — NOT inside `analyzer.py`.

The withdrawable map is produced by the Binance source (I/O) and handed to the router. Each
ingest tick writes the latest map to a small JSON cache at `codee/data/binance_withdraw.json`
(no DB migration); the router loads it (cheap, cached in memory with mtime check) and applies the
gate per request — no live Binance call on the read path. Missing/empty file → gate yields `None`
for all routes (graceful degrade).

---

## 5. Frontend — anchor selector + withdrawable toggle (VT `web/index.html`)

In the Codee filter row (next to the liquidity slider + asset filter from T1):
- **Starting-capital selector**: segmented control / dropdown `[ All · USDC · USDT · ETH · BTC ]`,
  default **All**. Selecting a class filters rows (client-side) to those whose **entry asset**
  is in that class (reuse `codeeNormSym` + the class ticker lists shipped to the client, or a
  per-route `asset_class` field from the backend — prefer the backend field to keep one source
  of truth).
- **"Binance-withdrawable only" toggle**: default **on** when a class is selected, **off** for
  All. When on, hide rows with `binance_withdrawable === false`; rows with `null` (unknown) stay
  visible. Non-withdrawable rows (when shown) get a small muted marker.
- **Volatile-collateral note**: when the selected class is ETH or BTC, show a one-line caveat
  ("volatile collateral — routes carry ETH/BTC price exposure").
- Hidden on Rewards/History sub-tabs (same as the slider/asset filter).

To keep the anchor's entry-class match unambiguous, the backend adds an `entry_asset_class`
string to each route (the class of its entry asset, or null), so the client filters on that
rather than re-deriving classes in JS.

---

## 6. Implementation target — which repo

Same split as prior Codee work:
- **Backend** (asset_classes config, `asset_class` helper, ingestor universe, Binance source,
  network map, route flags) → `Volume_tracker/codee/…`, **mirrored** to `AAVE_STRAT/…`.
- **Frontend** (selector + toggle) → `Volume_tracker/web/index.html` only (AAVE_STRAT's
  `web/index.html` is the dead standalone UI).
- Deploy via the established git-bundle flow; this one **needs a `systemctl restart`** (backend
  `.py` + new config files). Requires `BI_API_KEY`/`BI_API_SECRET` present in the server env
  (already set for VT) — verify before deploy.

---

## 7. Testing (all offline, per project convention)

- **`asset_class` / config:** `asset_class("USD₮")=="USDT"`, `"WETH"->"ETH"`, `"BTCB"->"BTC"`,
  `"DAI"->None`, `None->None`.
- **ingestor universe:** a WETH pool (≥$10k) is now KEPT; a WBTC pool KEPT; a random non-class
  token still dropped; stablecoins still kept.
- **Binance source:** a `StubBinance` returning a captured `capital/config` fixture →
  `withdrawable_chains` maps coins to DefiLlama chains via `binance_networks.json`; a
  `withdrawEnable=false` network is excluded; unmapped network codes ignored; empty creds → empty
  map (no crash).
- **gate flag:** a USDC@Arbitrum route with Arbitrum in USDC's withdrawable set →
  `binance_withdrawable=True`; USDC@Sonic with Sonic absent → `False`; a DAI route → `None`
  (not a class); empty map → `None`.
- **API models:** the three route endpoints include `binance_withdrawable` + `entry_asset_class`.
- **Golden test:** unchanged (its `_pipeline` hardcodes a stablecoin subset + $1M filter; ETH/BTC
  expansion doesn't touch it). Confirm it still passes; do not relax it.
- **Frontend:** manual via `local_harness` — selector filters by class, withdrawable toggle
  hides `false` rows, ETH/BTC shows the volatile note, Rewards/History hide the controls.

---

## 8. Decomposition note

Single cohesive spec, on the larger side. If the implementation plan grows unwieldy, a clean cut
is: **Phase A** = asset classes + universe expansion + anchor selector (no Binance gate);
**Phase B** = Binance source + `binance_withdrawable` gate + toggle. Phase A delivers visible
value (ETH/BTC + class anchor) without the signed-API dependency; Phase B adds the
withdrawability gate. The plan may sequence them as two task groups within one branch.
