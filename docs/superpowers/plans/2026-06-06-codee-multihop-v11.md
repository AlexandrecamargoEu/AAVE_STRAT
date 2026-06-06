# Codee Multi-Hop v1.1 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make the Multi-Hop view self-explanatory and the Max-hops selector useful: per-leg rates inline in the route, depth-diverse API results (top-K per hops level), retire the Cross-Chain sub-tab, and fix the multi-pool-per-symbol indexing bug.

**Architecture:** All ranking changes stay in the pure analyzer (`enumerate_multihop_paths`): dedupe pools to best-supply / cheapest-borrow per `(chain, project, symbol)`, carry per-leg rates through the beam state, and distribute the final `limit` across depths (quota `limit // max_hops` per level + backfill). The API exposes the legs (`supply_apy` per node + `borrows` list). The frontend renders rates inline in the Route cell and drops the Cross-Chain sub-tab (backend `/routes/crosschain`, analyzer fn and History chart stay untouched).

**Tech Stack:** Python 3.13, FastAPI, pydantic v2, pytest (offline); vanilla JS in `web/index.html`.

**Where:** Backend in `F:\codefee\Volume_tracker\codee\…` on branch `codee-multihop-v11` (create from `main` at execution start), mirrored to `F:\codefee\AAVE_STRAT\…` (bare imports, NO frontend; branch `codee-multihop-v11` from `master`). Frontend in `Volume_tracker\web\index.html` only. Test cmd (Bash, from `F:\codefee\Volume_tracker`): `PYTHONIOENCODING=utf-8 .venv/Scripts/pytest codee/tests/ -q`.

**Why (live evidence, 06-jun-2026):** `/routes/multihop?limit=200` returns 198× 2-hop + 2× 1-hop and ZERO 3/4-hop — global top-N is saturated by junk 2-hops, so the Max-hops selector looks broken. Also: the top 2-hop (445%) ends at a peapods pool whose best variant never appears as a 1-hop root — `by_cp[(chain,proj)][sym] = p` keeps only the LAST pool per symbol while `supply_nodes` keeps all, so multi-market platforms (peapods pods, Morpho vaults) are roots/borrow-legs via an arbitrary pool but destinations via every pool.

---

### Task 1: Analyzer v1.1 — dedupe indexes, per-leg rates, depth-diverse limit

**Files:**
- Modify: `codee/services/routes/analyzer.py` (the multi-hop section, currently lines ~210-305)
- Test: `codee/tests/test_analyzer_multihop.py`

- [ ] **Step 1: Write the failing tests** — append to `codee/tests/test_analyzer_multihop.py` (reuses its existing `_p`, `POOLS`, `WMAP`, `DMAP`, `COSTS` fixtures):

```python
def test_per_leg_rates_exposed():
    paths = enumerate_multihop_paths(POOLS, WMAP, DMAP, COSTS, capital_class="USDC")
    best = [p for p in paths if p.hops == 2][0]
    assert len(best.supply_apys) == 2
    assert best.supply_apys[0] == pytest.approx(10.0)
    assert best.supply_apys[1] == pytest.approx(5.0)
    assert len(best.borrow_legs) == 1
    assert best.borrow_legs[0][0] == "WETH"
    assert best.borrow_legs[0][1] == pytest.approx(2.0)


def test_same_symbol_pools_collapse_to_best_supply():
    # duplicate ChainB aave-v3 WETH with much better supply -> it must win the node
    pools = POOLS + [_p("ChainB", "aave-v3", "WETH", base=50.0, borrow_base=9.0, ltv=0.80, tvl=1e6)]
    paths = enumerate_multihop_paths(pools, WMAP, DMAP, COSTS, capital_class="USDC")
    two = [p for p in paths if p.hops == 2]
    assert two[0].net_apy == pytest.approx(10 - 0.75 * 2 + 0.75 * 50)   # 46.0
    # exactly ONE route per node id (no duplicate-pool ghost routes)
    assert len([p for p in two if p.nodes[-1] == ("ChainB", "aave-v3", "WETH")]) == 1


def test_borrow_leg_uses_cheapest_pool():
    # second WETH@ChainA pool with cheaper borrow -> borrow leg must use 1.0 not 2.0
    pools = POOLS + [_p("ChainA", "aave-v3", "WETH", base=0.1, borrow_base=1.0, ltv=0.80)]
    paths = enumerate_multihop_paths(pools, WMAP, DMAP, COSTS, capital_class="USDC")
    best = [p for p in paths if p.hops == 2][0]
    assert best.borrow_legs[0][1] == pytest.approx(1.0)
    assert best.net_apy == pytest.approx(10 - 0.75 * 1 + 0.75 * 5)      # 13.0


def test_limit_reserves_slots_per_depth():
    # two 2-hop routes (13.0 via ChainC, 12.25 via ChainB) both beat the 10.0 root;
    # with limit=2 the old global top-N would return ONLY 2-hops — the per-depth
    # quota must still surface the best 1-hop.
    pools = POOLS + [_p("ChainC", "aave-v3", "WETH", base=6.0, borrow_base=3.0)]
    wmap = {"USDC": {"ChainA"}, "ETH": {"ChainB", "ChainC"}, "USDT": set(), "BTC": set()}
    paths = enumerate_multihop_paths(pools, wmap, DMAP, COSTS, capital_class="USDC", limit=2)
    assert len(paths) == 2
    assert {p.hops for p in paths} == {1, 2}
    assert paths[0].net_apy >= paths[1].net_apy        # still net-desc overall
```

- [ ] **Step 2: Run — expect FAIL** (`supply_apys` attribute missing; diversity test gets 2× 2-hop)

Run: `cd /f/codefee/Volume_tracker && PYTHONIOENCODING=utf-8 .venv/Scripts/pytest codee/tests/test_analyzer_multihop.py -v`

- [ ] **Step 3: Implement** — replace the multi-hop section of `codee/services/routes/analyzer.py` (from `@dataclass(frozen=True)\nclass MultiHopPath:` through the final `return emitted[:limit]`) with:

```python
@dataclass(frozen=True)
class MultiHopPath:
    nodes: tuple                 # ((chain, project, symbol), ...) one per supply leg
    net_apy: float               # leveraged net carry % on the initial capital
    hops: int                    # len(nodes)
    bridge_cost_usd: float       # sum of dest-chain bridge costs
    min_liquidity_usd: float     # thinnest tvlUsd among ALL pools used (supply + borrow legs)
    entry_asset_class: str | None
    supply_apys: tuple = ()      # effective supply APY per node (aligned with nodes)
    borrow_legs: tuple = ()      # ((borrow symbol, effective borrow APR), ...) per transition


def enumerate_multihop_paths(pools: list[dict], withdraw_map: dict, deposit_map: dict,
                             bridge_costs: dict, *, max_hops: int = 4,
                             capital_class: str | None = None,
                             beam_width: int = 300, limit: int = 200) -> list[MultiHopPath]:
    """Beam-search enumeration of supply->borrow->bridge->supply chains (spec section 2).

    A hop lives on ONE platform: supply A on (chain,project), borrow B on the SAME
    (chain,project), Binance-bridge B (deposit on source chain AND withdraw on dest
    chain, by B's class), supply B on the dest. Chains always end on a supply; the
    dest chain must differ from the source. Beam search bounds the combinatorial
    blow-up: at each depth only the top `beam_width` partial paths (by net carry)
    are expanded; every retained partial path is also a terminal candidate
    (beam-dropped partials are not emitted). The final `limit` is distributed
    across depths (quota limit // max_hops per hops level, best-first backfill)
    so deep routes are never starved by a wall of better shallow ones. Pure: no I/O.
    """
    # Best pool per (chain, project, symbol): platforms like peapods/Morpho list
    # MULTIPLE pools under the same symbol — collapse to the best-supply pool
    # (roots/destinations) and the cheapest-borrow pool (borrow legs) so every
    # role draws from the same universe (pre-v1.1 the last-seen pool silently won).
    by_cp_supply: dict[tuple[str, str], dict[str, dict]] = {}
    by_cp_borrow: dict[tuple[str, str], dict[str, dict]] = {}
    for p in pools:
        cls = asset_class(p.get("symbol"))
        if cls is None:
            continue
        key = (p.get("chain"), p.get("project"))
        sym = normalize_symbol(p.get("symbol"))
        cur = by_cp_supply.setdefault(key, {}).get(sym)
        if cur is None or effective_supply_apy(p) > effective_supply_apy(cur):
            by_cp_supply[key][sym] = p
        if p.get("apyBaseBorrow") is not None:
            curb = by_cp_borrow.setdefault(key, {}).get(sym)
            if curb is None or effective_borrow_apr(p) < effective_borrow_apr(curb):
                by_cp_borrow[key][sym] = p

    supply_nodes: dict[str, list[tuple[str, str, dict]]] = defaultdict(list)  # class -> [(chain, proj, pool)]
    for (chain, proj), assets in by_cp_supply.items():
        for sym, pool in assets.items():
            supply_nodes[asset_class(sym)].append((chain, proj, pool))

    def node_id(chain, proj, pool):
        return (chain, proj, normalize_symbol(pool.get("symbol")))

    # state: (visited, nodes, last(chain,proj,pool), S, net, bridge$, minliq, entry_cls,
    #         supply_apys tuple, borrow_legs tuple)
    frontier = []
    emitted: list[MultiHopPath] = []
    for (chain, proj), assets in by_cp_supply.items():
        for sym, pool in assets.items():
            cls = asset_class(sym)
            if capital_class is not None and cls != capital_class:
                continue
            if chain not in withdraw_map.get(cls, set()):
                continue                      # can't withdraw the starting capital here
            sup = effective_supply_apy(pool)
            nid = node_id(chain, proj, pool)
            frontier.append((frozenset([nid]), (nid,), (chain, proj, pool),
                             1.0, sup, 0.0, float(pool.get("tvlUsd") or 0), cls,
                             (sup,), ()))

    for _depth in range(1, max_hops):         # expansions: hop 2 .. max_hops
        frontier.sort(key=lambda s: s[4], reverse=True)
        frontier = frontier[:beam_width]
        nxt = []
        for visited, nodes, (chain, proj, pool), S, net, bridge, minliq, entry, sups, bors in frontier:
            emitted.append(MultiHopPath(nodes, net, len(nodes), bridge, minliq, entry, sups, bors))
            r = per_iter_ltv(pool.get("ltv"))
            if r <= 0:
                continue
            d = S * r
            for bsym, bpool in by_cp_borrow.get((chain, proj), {}).items():
                bcls = asset_class(bsym)
                if bcls is None or chain not in deposit_map.get(bcls, set()):
                    continue                  # Binance can't take the borrowed asset off this chain
                bor = effective_borrow_apr(bpool)
                for (c2, p2, spool) in supply_nodes.get(bcls, []):
                    if c2 == chain:
                        continue              # must actually move chains
                    if c2 not in withdraw_map.get(bcls, set()):
                        continue
                    nid = node_id(c2, p2, spool)
                    if nid in visited:
                        continue
                    sup2 = effective_supply_apy(spool)
                    new_net = net - d * bor + d * sup2
                    new_liq = min(minliq, float(bpool.get("tvlUsd") or 0),
                                  float(spool.get("tvlUsd") or 0))
                    nxt.append((visited | {nid}, nodes + (nid,), (c2, p2, spool),
                                d, new_net, bridge + float(bridge_costs.get(c2, 1.0)),
                                new_liq, entry, sups + (sup2,), bors + ((bsym, bor),)))
        frontier = nxt

    for _v, nodes, _last, _S, net, bridge, minliq, entry, sups, bors in frontier:  # deepest level
        emitted.append(MultiHopPath(nodes, net, len(nodes), bridge, minliq, entry, sups, bors))

    emitted.sort(key=lambda p: p.net_apy, reverse=True)
    # Depth-diverse cut: reserve limit // max_hops slots per hops level (≥1), then
    # backfill the remainder best-first. A global top-N would let a wall of junk
    # 2-hops starve every deeper route out of the response.
    per_depth = max(1, limit // max_hops)
    picked: list[MultiHopPath] = []
    leftover: list[MultiHopPath] = []
    count: dict[int, int] = {}
    for p in emitted:                          # already net-desc
        if count.get(p.hops, 0) < per_depth:
            picked.append(p)
            count[p.hops] = count.get(p.hops, 0) + 1
        else:
            leftover.append(p)
    picked.extend(leftover[: max(0, limit - len(picked))])
    picked.sort(key=lambda p: p.net_apy, reverse=True)
    return picked
```

- [ ] **Step 4: Run — expect PASS** (all 10 tests: 6 pre-existing + 4 new) + golden untouched

Run: `PYTHONIOENCODING=utf-8 .venv/Scripts/pytest codee/tests/test_analyzer_multihop.py codee/tests/test_golden.py -v`

- [ ] **Step 5: Commit**
```bash
git add codee/services/routes/analyzer.py codee/tests/test_analyzer_multihop.py
git commit -m "T4v1.1-1: analyzer — best-pool dedupe per node, per-leg rates, depth-diverse limit"
```

---

### Task 2: API — expose per-leg rates

**Files:**
- Modify: `codee/services/api/models.py`
- Modify: `codee/services/api/router.py`
- Test: `codee/tests/test_api.py`

- [ ] **Step 1: Write the failing test** — in `codee/tests/test_api.py`, extend the existing `test_multihop_endpoint_returns_paths` by appending after the current assertions:

```python
    # v1.1: per-leg rates exposed
    assert best["path"][0]["supply_apy"] == pytest.approx(10.0)
    assert best["path"][1]["supply_apy"] == pytest.approx(5.0)
    assert len(best["borrows"]) == 1
    assert best["borrows"][0]["symbol"] == "WETH"
    assert best["borrows"][0]["borrow_apr"] == pytest.approx(2.0)
```

- [ ] **Step 2: Run — expect FAIL** (`supply_apy` key missing)

Run: `PYTHONIOENCODING=utf-8 .venv/Scripts/pytest codee/tests/test_api.py::test_multihop_endpoint_returns_paths -v`

- [ ] **Step 3: Implement**

`codee/services/api/models.py` — extend `MultiHopNode` and add `MultiHopBorrow`; `MultiHopRoute` gains `borrows`:
```python
class MultiHopNode(BaseModel):
    chain: str
    project: str
    symbol: str
    supply_apy: float | None = None       # effective supply APY of this leg


class MultiHopBorrow(BaseModel):
    symbol: str                            # borrowed asset (normalized)
    borrow_apr: float                      # effective borrow APR paid on that leg


class MultiHopRoute(BaseModel):
    path: list[MultiHopNode]
    borrows: list[MultiHopBorrow] = []     # one per transition (len == hops-1)
    net_apy: float
    hops: int
    bridge_cost_usd: float
    min_liquidity_usd: float
    entry_asset_classes: list[str] = []
    incentive_conditional: bool = False   # any leg has a Self-gated incentive
```

`codee/services/api/router.py` — extend the models import with `MultiHopBorrow`; in `routes_multihop` replace the return-list construction with:
```python
    return [MultiHopRoute(
        path=[MultiHopNode(chain=c, project=pr, symbol=s,
                           supply_apy=(p.supply_apys[i] if i < len(p.supply_apys) else None))
              for i, (c, pr, s) in enumerate(p.nodes)],
        borrows=[MultiHopBorrow(symbol=bs, borrow_apr=ba) for (bs, ba) in p.borrow_legs],
        net_apy=p.net_apy, hops=p.hops, bridge_cost_usd=p.bridge_cost_usd,
        min_liquidity_usd=p.min_liquidity_usd,
        entry_asset_classes=[p.entry_asset_class] if p.entry_asset_class else [],
        incentive_conditional=any(_is_conditional(c, s, aci) for (c, _pr, s) in p.nodes),
    ) for p in paths]
```

- [ ] **Step 4: Run — expect PASS** (full test_api.py, then full suite)

Run: `PYTHONIOENCODING=utf-8 .venv/Scripts/pytest codee/tests/test_api.py -v` then `codee/tests/ -q`

- [ ] **Step 5: Commit**
```bash
git add codee/services/api/models.py codee/services/api/router.py codee/tests/test_api.py
git commit -m "T4v1.1-2: /routes/multihop exposes per-leg supply APYs + borrow legs"
```

---

### Task 3: Frontend — inline rates in Route, retire Cross-Chain sub-tab

**Files:**
- Modify: `Volume_tracker/web/index.html` only

No automated test; verify via harness in Step 4.

- [ ] **Step 1: Remove the Cross-Chain sub-tab**
- Delete the button line (~2635): `<button class="mm-routes-tab" data-codeetab="crosschain">Cross-Chain</button>`
- Delete the whole `crosschain: { ... },` entry from the `VIEWS` object (~7840-7853).
- Do NOT touch: the `/routes/crosschain` backend endpoint, `codeeSpreadClass` (used elsewhere — verify with grep; if it became unused, leave it anyway, it's 1 line), or the History chart series `best_crosschain_spread` (independent data source).
- Grep for any other `crosschain` reference in the file (e.g. a default-tab fallback) — adjust if one selects the removed tab.

- [ ] **Step 2: Inline per-leg rates in the multihop Route cell** — replace `VIEWS.multihop.row` with a function body that interleaves `path` and `borrows` (Paul's notation: `USDC·Base 4.2% →(USDC 2.1%)→ USDC·Sonic 9.5%`):
```javascript
      row: (d) => {
        const segs = (d.path || []).map((n) => `${n.symbol}·${n.chain} ${codeeFmtApy(n.supply_apy)}`);
        const bs = d.borrows || [];
        let route = segs[0] || '';
        for (let i = 1; i < segs.length; i++) {
          const b = bs[i - 1];
          route += b ? ` →(${b.symbol} ${codeeFmtApy(b.borrow_apr)})→ ` : ' → ';
          route += segs[i];
        }
        if (d.incentive_conditional) route += ' ⚠';
        return `<td>${route}</td>
        <td class="r">${codeeFmtApy(d.net_apy)}</td>
        <td class="r">${d.hops}</td>
        <td class="r">$${Number(d.bridge_cost_usd).toFixed(2)}</td>
        <td class="r">${codeeFmtTvl(d.min_liquidity_usd)}</td>`;
      },
```
(`·` = `·`, `→` = `→`, `⚠` = `⚠` — keep literal chars if the file already uses them literally; match the file's existing style. Other `row:` entries are single template literals — a function body is still a valid VIEWS value since `row(d)` is invoked as a function either way; verify how `row` is called in `renderCodeeTable` before assuming.)

- [ ] **Step 3: Static check**
`grep -n "crosschain" web/index.html` → expect ONLY the History chart series line (`best_crosschain_spread`). `grep -c "codeeHopsSelect" web/index.html` → unchanged (2).

- [ ] **Step 4: Harness smoke test**
Start `PYTHONIOENCODING=utf-8 .venv/Scripts/python -m codee.scripts.local_harness` (port 8011, background). Verify:
- `curl -s http://127.0.0.1:8011/api/codee/routes/multihop` → 200 (fixtures may give `[]` — fine).
- `curl -s http://127.0.0.1:8011/ | grep -c 'data-codeetab="crosschain"'` → 0.
- `curl -s http://127.0.0.1:8011/ | grep -c 'data-codeetab="multihop"'` → 1.
Kill the harness.

- [ ] **Step 5: Commit**
```bash
git add web/index.html
git commit -m "T4v1.1-3: Multi-Hop shows per-leg rates inline; retire Cross-Chain sub-tab"
```

---

### Task 4: Mirror backend to AAVE_STRAT

**Files (in `F:\codefee\AAVE_STRAT`, branch `codee-multihop-v11`):** Tasks 1-2 only (NOT Task 3 — frontend is VT-only). Bare imports. Mirror method: take each VT file at `codee-multihop-v11` HEAD, apply the same hunks to the AAVE_STRAT counterpart (no `codee/` prefix). Known divergence: AAVE_STRAT models.py has no `StrategyHistoryPoint` and its test_api.py lacks some VT-only tests — same escalation rule as always (report, don't force-fit).

- [ ] **Step 1:** Apply the analyzer, models, router and test hunks with bare imports.
- [ ] **Step 2:** Run `cd /f/codefee/AAVE_STRAT && PYTHONIOENCODING=utf-8 .venv/Scripts/pytest -q`. Expected: all pass (112 + 4 new analyzer tests = 116ish; report exact).
- [ ] **Step 3:** Commit:
```bash
git add services tests
git commit -m "T4 v1.1 (mirror): per-leg rates, depth-diverse limit, best-pool dedupe"
```

### Task 5: Deploy (gated on explicit user approval)

> Backend `.py` changed → **`systemctl restart` required**. Do NOT deploy without the user's explicit go-ahead for this production push.

- [ ] **Step 1:** Full suites green in both repos; merge branch → `main` (VT) / `master` (AAVE_STRAT, push).
- [ ] **Step 2:** Deploy via `python scripts/_deploy.py` pattern (bundle from server HEAD `527c6fe`; note: run the bundle creation under Git Bash — `/tmp` doesn't exist for the Windows Python; reuse the one-off paramiko uploader approach from the T4 deploy if needed).
- [ ] **Step 3:** Verify: service active; `/api/codee/routes/multihop?limit=200` returns a MIX of hops levels (1 AND 2 at minimum; 3/4 if any exist); response rows carry `path[].supply_apy` + `borrows[]`; dashboard `/dashboard` has NO `data-codeetab="crosschain"` and the Multi-Hop tab renders inline rates; Max-hops selector now visibly changes the table (depth diversity present). Hard-refresh reminder to the user.

---

## Self-review notes

- **Coverage:** item 1 (depth diversity) → Task 1 quota cut + Task 5 verify; item 2 (per-leg rates) → Tasks 1-3; item 3 (retire Cross-Chain) → Task 3; item 4 (indexing bug) → Task 1 dedupe (+ regression tests). T2 whitelist explicitly OUT of scope (user's call, 06-jun).
- **Type consistency:** `MultiHopPath.supply_apys: tuple[float]` aligned with `nodes`; `borrow_legs: tuple[(sym, apr)]` → `MultiHopBorrow`; router zips by index with a length guard; defaults `()` keep the dataclass backward-constructible.
- **Behavioral notes:** with dedupe, junk multi-market platforms now also surface as 1-hop roots (e.g. the 590% peapods pool) — correct radar behavior ("never silently drop"), cleanliness is T2's job. The diversity quota changes the response composition for the same `limit`; the UI consumes it unchanged (client-side filters intact).
- **Purity:** analyzer change is pure (no new imports); models/router additive; no DB/schema impact; golden test untouched.
