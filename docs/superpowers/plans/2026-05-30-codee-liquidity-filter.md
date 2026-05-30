# Codee Liquidity Filter Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace Codee's hard $1M TVL gate (which silently dropped real markets like Aave Sonic USDC) with a $10k dust floor plus a user-adjustable minimum-liquidity slider (default $100k) and a plain "Liquidez" column.

**Architecture:** Backend change is tiny — lower the `MIN_TVL_USD` config default and add one `available_liquidity_usd` field to the cross-chain route (passive/loops already expose `tvl_usd`/`min_tvl_usd`, which *are* available liquidity for lending pools). Frontend gets a log-scale range slider that filters the already-loaded table rows client-side, plus a Liquidez column per view.

**Tech Stack:** Python 3.13, FastAPI, pydantic v2, pytest (offline fixtures); vanilla JS + VT's native CSS in `web/index.html`.

**Where to implement:** Primary = `F:\codefee\Volume_tracker` (the deployed copy). Backend changes are mirrored into `F:\codefee\AAVE_STRAT` at the end (Task 6). Frontend is VT-only. All commands below run from `F:\codefee\Volume_tracker` unless stated.

**Test runner:** `.venv\Scripts\pytest` from the `Volume_tracker` root. Codee's tests live under `codee\tests\` with `codee\pytest.ini`; run a single test file with `.venv\Scripts\pytest codee/tests/test_x.py -v`.

---

### Task 1: Lower the dust floor (config default $1M → $10k)

**Files:**
- Modify: `codee/config/config.py:23`
- Test: `codee/tests/test_pools_ingestor.py:53-70` (existing test asserts the old behavior — must update)

- [ ] **Step 1: Update the failing ingestor test to the new boundary**

Replace the body of `test_ingestor_full_pipeline_persists_filtered_pools` in
`codee/tests/test_pools_ingestor.py` so it asserts the new $10k floor (a $500k pool now
PASSES; a sub-$10k pool is dropped):

```python
async def test_ingestor_full_pipeline_persists_filtered_pools(db):
    supply = [
        _supply_pool("u1", "BSC", "aave-v3", "USDC", base=2.6),
        _supply_pool("u2", "BSC", "aave-v3", "USDT", base=2.4),
        # mid-size pool: above the new $10k floor -> now KEPT (was dropped under $1M)
        _supply_pool("u3", "BSC", "aave-v3", "DAI", tvl=500_000),
        # dust: below the $10k floor -> dropped (TUSD is in stable_symbols.json)
        _supply_pool("u5", "BSC", "aave-v3", "TUSD", tvl=5_000),
        # non-stable -> filtered
        _supply_pool("u4", "BSC", "aave-v3", "WBNB"),
    ]
    borrow = [_borrow_pool("u1"), _borrow_pool("u2"), _borrow_pool("u3"),
              _borrow_pool("u5"), _borrow_pool("u4")]
    merkl = [_merkl_opp("Mantle", "aave", "USDC", 1.37)]  # won't match BSC pools

    ing = PoolsIngestor(db, StubDefiLlama(supply, borrow), StubMerkl(merkl))
    n = await ing.run_once(ts=1716800000)

    assert n == 3  # u1 + u2 + u3; u5 (dust) and u4 (not stable) filtered
    rows = await db.fetch_all("SELECT pool_id, symbol FROM pools_snapshot ORDER BY pool_id")
    assert rows == [("u1", "USDC"), ("u2", "USDT"), ("u3", "DAI")]
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `.venv\Scripts\pytest codee/tests/test_pools_ingestor.py::test_ingestor_full_pipeline_persists_filtered_pools -v`
Expected: FAIL — under the current $1M default `u3` ($500k) is filtered, so `n == 2` and the row assertion mismatches.

- [ ] **Step 3: Lower the config default**

In `codee/config/config.py`, change line 23:

```python
    MIN_TVL_USD: float = 10_000              # env: CODEE_MIN_TVL_USD (dust floor / slider min)
```

- [ ] **Step 4: Run the test to verify it passes**

Run: `.venv\Scripts\pytest codee/tests/test_pools_ingestor.py -v`
Expected: PASS (all tests in the file).

- [ ] **Step 5: Commit**

```bash
git add codee/config/config.py codee/tests/test_pools_ingestor.py
git commit -m "Lower Codee dust floor MIN_TVL_USD 1M -> 10k (stop silently dropping real markets)"
```

---

### Task 2: Add `available_liquidity_usd` to the cross-chain analyzer (pure)

**Files:**
- Modify: `codee/services/routes/analyzer.py:156-202` (`CrossChainCarry` dataclass + `cross_chain_carry`)
- Test: `codee/tests/test_analyzer_crosschain.py`

- [ ] **Step 1: Write the failing test**

Append to `codee/tests/test_analyzer_crosschain.py`:

```python
def test_cross_chain_exposes_min_available_liquidity():
    """available_liquidity_usd = min(supply-pool tvl, borrow-pool tvl)."""
    pools = [
        _p("Canto",  "canto-lending", "USDC", base=13.5, borrow_base=15.0, tvl=2_000_000),
        _p("Cronos", "tectonic",      "USDC", base=2.0,  borrow_base=0.5,  tvl=300_000),
    ]
    rows = cross_chain_carry(pools)
    usdc = next(r for r in rows if r.symbol == "USDC")
    # supply leg = Canto ($2M), borrow leg = Cronos ($300k) -> min = 300k
    assert usdc.available_liquidity_usd == pytest.approx(300_000)


def test_cross_chain_available_liquidity_none_when_tvl_missing():
    pools = [
        _p("Canto",  "canto-lending", "USDC", base=13.5, borrow_base=15.0, tvl=None),
        _p("Cronos", "tectonic",      "USDC", base=2.0,  borrow_base=0.5,  tvl=None),
    ]
    rows = cross_chain_carry(pools)
    usdc = next(r for r in rows if r.symbol == "USDC")
    assert usdc.available_liquidity_usd is None
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `.venv\Scripts\pytest codee/tests/test_analyzer_crosschain.py::test_cross_chain_exposes_min_available_liquidity -v`
Expected: FAIL — `CrossChainCarry` has no attribute `available_liquidity_usd`.

- [ ] **Step 3: Add the field and compute it**

In `codee/services/routes/analyzer.py`, add the field to the dataclass (after line 166):

```python
@dataclass(frozen=True)
class CrossChainCarry:
    symbol: str
    supply_chain: str
    supply_project: str
    supply_apy: float
    borrow_chain: str
    borrow_project: str
    borrow_apr: float
    spread: float
    pre_bridge_ceiling: bool = True   # always True in Phase 1a — no bridge cost applied
    available_liquidity_usd: float | None = None
```

Then rewrite the body of `cross_chain_carry` to thread `tvlUsd` through the tuples and
select by APY with an explicit key (avoids comparing `None` tvls):

```python
def cross_chain_carry(pools: list[dict]) -> list[CrossChainCarry]:
    """Per-stable-asset: best supply on any chain vs cheapest net-borrow on any
    OTHER chain. With Merkl rebates already applied via overlay_rebates() upstream.

    Pre-bridge-cost ceiling — the executable filter (bridge <= $1) is Phase 2.
    """
    # tuples: (apy, chain, project, tvlUsd)
    sup_by_asset: dict[str, list[tuple]] = defaultdict(list)
    bor_by_asset: dict[str, list[tuple]] = defaultdict(list)
    for p in pools:
        sym = (p.get("symbol") or "").upper()
        chain = p.get("chain") or ""
        proj = p.get("project") or ""
        tvl = p.get("tvlUsd")
        sup_by_asset[sym].append((effective_supply_apy(p), chain, proj, tvl))
        if p.get("apyBaseBorrow") is not None:
            bor_by_asset[sym].append((effective_borrow_apr(p), chain, proj, tvl))

    out: list[CrossChainCarry] = []
    for sym, sup_list in sup_by_asset.items():
        bor_list = bor_by_asset.get(sym, [])
        if not bor_list:
            continue
        best_sup = max(sup_list, key=lambda t: t[0])
        cheap_bor = min(bor_list, key=lambda t: t[0])
        if best_sup[1] == cheap_bor[1]:
            # same chain — skip (covered by same-chain loop ranking)
            continue
        avail = min((t for t in (best_sup[3], cheap_bor[3]) if t is not None), default=None)
        out.append(CrossChainCarry(
            symbol=sym,
            supply_chain=best_sup[1], supply_project=best_sup[2], supply_apy=best_sup[0],
            borrow_chain=cheap_bor[1], borrow_project=cheap_bor[2], borrow_apr=cheap_bor[0],
            spread=best_sup[0] - cheap_bor[0],
            available_liquidity_usd=avail,
        ))
    out.sort(key=lambda r: r.spread, reverse=True)
    return out
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `.venv\Scripts\pytest codee/tests/test_analyzer_crosschain.py -v`
Expected: PASS (the two new tests + the three existing ones).

- [ ] **Step 5: Run the golden test to confirm no regression**

Run: `.venv\Scripts\pytest codee/tests/test_golden.py -v`
Expected: PASS — the golden `_pipeline` hardcodes its own `>= 1_000_000` filter, and the
cross-chain assertion only checks `any(...symbol in...)`, so the new field/selection-key
does not change locked values.

- [ ] **Step 6: Commit**

```bash
git add codee/services/routes/analyzer.py codee/tests/test_analyzer_crosschain.py
git commit -m "Add available_liquidity_usd (min of legs) to cross-chain carry route"
```

---

### Task 3: Surface `available_liquidity_usd` on the cross-chain API model

**Files:**
- Modify: `codee/services/api/models.py:42-51` (`CrossChainRoute`)
- Modify: `codee/services/api/router.py:158-167` (`routes_crosschain`)
- Test: `codee/tests/test_api.py`

- [ ] **Step 1: Write the failing test**

Append to `codee/tests/test_api.py`:

```python
async def test_crosschain_endpoint_includes_available_liquidity(app):
    app_, db = app
    import time
    now = int(time.time())
    # supply leg on Canto ($2M free), borrow leg on Cronos ($300k free), same asset
    await db.execute(
        """INSERT INTO pools_snapshot (pool_id, chain, project, symbol, tvl_usd,
           supply_apy_base, borrow_apr_base, updated_at)
           VALUES (?, 'Canto', 'canto-lending', 'USDC', 2e6, 13.5, 15.0, ?)""",
        ("cc1", now),
    )
    await db.execute(
        """INSERT INTO pools_snapshot (pool_id, chain, project, symbol, tvl_usd,
           supply_apy_base, borrow_apr_base, updated_at)
           VALUES (?, 'Cronos', 'tectonic', 'USDC', 3e5, 2.0, 0.5, ?)""",
        ("cc2", now),
    )
    transport = ASGITransport(app=app_)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        resp = await ac.get("/api/codee/routes/crosschain")
    body = resp.json()
    usdc = next(r for r in body if r["symbol"] == "USDC")
    assert usdc["available_liquidity_usd"] == pytest.approx(3e5)
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `.venv\Scripts\pytest codee/tests/test_api.py::test_crosschain_endpoint_includes_available_liquidity -v`
Expected: FAIL with `KeyError`/assertion — `available_liquidity_usd` not in the response.

- [ ] **Step 3: Add the field to the model**

In `codee/services/api/models.py`, add to `CrossChainRoute` (after `pre_bridge_ceiling`):

```python
class CrossChainRoute(BaseModel):
    symbol: str
    supply_chain: str
    supply_project: str
    supply_apy: float
    borrow_chain: str
    borrow_project: str
    borrow_apr: float
    spread: float
    pre_bridge_ceiling: bool = True
    available_liquidity_usd: float | None = None
```

- [ ] **Step 4: Populate it in the router**

In `codee/services/api/router.py`, `routes_crosschain`, add the field to the constructor:

```python
    return [CrossChainRoute(
        symbol=r.symbol,
        supply_chain=r.supply_chain, supply_project=r.supply_project, supply_apy=r.supply_apy,
        borrow_chain=r.borrow_chain, borrow_project=r.borrow_project, borrow_apr=r.borrow_apr,
        spread=r.spread, pre_bridge_ceiling=r.pre_bridge_ceiling,
        available_liquidity_usd=r.available_liquidity_usd,
    ) for r in rows[:limit]]
```

- [ ] **Step 5: Run the test to verify it passes**

Run: `.venv\Scripts\pytest codee/tests/test_api.py -v`
Expected: PASS (all API tests).

- [ ] **Step 6: Commit**

```bash
git add codee/services/api/models.py codee/services/api/router.py codee/tests/test_api.py
git commit -m "Expose available_liquidity_usd on /routes/crosschain"
```

---

### Task 4: Full backend test sweep

**Files:** none (verification only)

- [ ] **Step 1: Run the whole Codee suite**

Run: `.venv\Scripts\pytest codee/tests/ -q`
Expected: PASS — all tests green (≈98 + the 3 added). If anything fails, fix the cause
before proceeding; do NOT edit a test to mask a real regression.

---

### Task 5: Frontend — liquidity slider + Liquidez column (VT web/index.html)

**Files:**
- Modify: `F:\codefee\Volume_tracker\web\index.html` — HTML control near line 2641 (inside `#sectionCodee`, just before the table) and the Codee JS IIFE around lines 7757–7836.

This task has no automated test (it's the monolithic VT dashboard). Verify manually with
the local harness in Step 7. Commit at the end.

- [ ] **Step 1: Add the slider HTML above the Codee table**

In `web/index.html`, find (around line 2641-2642):

```html
          <div id="codeeCaveat" style="display:none;font-size:10px;color:var(--text-3);padding:4px 0;"></div>
          <table class="spread-table"><thead id="codeeThead"></thead><tbody id="codeeTbody"></tbody></table>
```

Insert this control block **between** the `codeeCaveat` div and the `<table>`:

```html
          <div id="codeeLiqFilter" style="display:flex;align-items:center;gap:10px;padding:6px 0;font-size:11px;color:var(--text-3);">
            <span>Liquidez mín.</span>
            <input id="codeeLiqSlider" type="range" min="0" max="1000" value="200" step="1" style="flex:0 0 220px;accent-color:var(--accent);">
            <span id="codeeLiqValue" style="color:var(--text-1);font-family:'JetBrains Mono',monospace;min-width:64px;">$100K</span>
          </div>
```

(Slider position 200/1000 maps to $100k on the log scale defined in Step 3 — default.)

- [ ] **Step 2: Add a liquidity accessor per view + the Liquidez column**

In the Codee JS IIFE, update the `VIEWS` object (lines 7767–7810). Add a `liq` accessor to
the three row views and a Liquidez column. Replace the `passive`, `loops`, and `crosschain`
entries with:

```javascript
    passive: {
      cols: ['Chain', 'Project', 'Symbol', 'Eff APY', 'Liquidez', 'Flag'],
      rcols: 3,
      path: '/routes/passive?limit=50',
      caveat: '',
      liq: (d) => d.tvl_usd,
      row: (d) => `<td>${d.chain}</td><td>${d.project}</td><td>${d.symbol}</td>
        <td class="r">${codeeFmtApy(d.effective_apy)}</td><td class="r">${codeeFmtTvl(d.tvl_usd)}</td>
        <td>${d.quality_flag === 'ok' ? '' : d.quality_flag}</td>`,
    },
    loops: {
      cols: ['Chain', 'A→B', 'X/Y', 'Spread', 'Lev', 'Gross APY', 'Liquidez'],
      rcols: 3,
      path: '/routes/loops?limit=50',
      caveat: '',
      empty: 'No positive-spread same-chain loops right now. Check Cross-Chain.',
      liq: (d) => d.min_tvl_usd,
      row: (d) => `<td>${d.chain}</td><td>${d.plat_a}→${d.plat_b}</td><td>${d.asset_x}/${d.asset_y}</td>
        <td class="r ${codeeSpreadClass(d.spread)}">${codeeFmtApy(d.spread)}</td>
        <td class="r">${Number(d.leverage).toFixed(2)}x</td><td class="r">${codeeFmtApy(d.gross_apy)}</td>
        <td class="r">${codeeFmtTvl(d.min_tvl_usd)}</td>`,
    },
    crosschain: {
      cols: ['Symbol', 'Supply (chain/proj)', 'Sup APY', 'Borrow (chain/proj)', 'Bor APR', 'Spread', 'Liquidez'],
      rcols: 2,
      path: '/routes/crosschain?limit=50',
      caveat: 'Pre-bridge ceiling — spreads ignore bridge cost/slippage. Theoretical upper bounds.',
      liq: (d) => d.available_liquidity_usd,
      row: (d) => `<td>${d.symbol}</td><td>${d.supply_chain}/${d.supply_project}</td>
        <td class="r">${codeeFmtApy(d.supply_apy)}</td><td>${d.borrow_chain}/${d.borrow_project}</td>
        <td class="r">${codeeFmtApy(d.borrow_apr)}</td>
        <td class="r ${codeeSpreadClass(d.spread)}">${codeeFmtApy(d.spread)}</td>
        <td class="r">${codeeFmtTvl(d.available_liquidity_usd)}</td>`,
    },
```

(The `rewards` view is unchanged — it has no `liq` accessor, so the slider won't apply to it.)

- [ ] **Step 3: Add the log-scale slider helpers + state (top of the IIFE)**

Just after `let activeTab = 'passive';` (line 7750), add:

```javascript
  let codeeMinLiq = 100_000;       // current min-liquidity threshold ($)
  let codeeLastData = null;        // last fetched rows, for client-side re-filtering
  // Log scale: slider 0..1000 -> $10k .. $1B  (value = 1e4 * 10^(5 * t))
  const codeeSliderToLiq = (pos) => Math.round(1e4 * Math.pow(10, 5 * (pos / 1000)));
```

- [ ] **Step 4: Filter rows by the slider in renderCodeeTable**

Replace `renderCodeeTable` (lines 7812–7826) with a version that filters by `v.liq` when present:

```javascript
  function renderCodeeTable(view, data) {
    const v = VIEWS[view];
    document.getElementById('codeeThead').innerHTML =
      '<tr>' + v.cols.map((c, i) => `<th class="${i >= v.rcols ? 'r' : ''}">${c}</th>`).join('') + '</tr>';
    const cv = document.getElementById('codeeCaveat');
    cv.style.display = v.caveat ? 'block' : 'none';
    cv.textContent = v.caveat;
    // Show the liquidity slider only for row-views that expose a liq accessor.
    document.getElementById('codeeLiqFilter').style.display = v.liq ? 'flex' : 'none';
    const tb = document.getElementById('codeeTbody');
    if (v.render) { tb.innerHTML = v.render(data); return; }
    let rows = data || [];
    if (v.liq) {
      rows = rows.filter((d) => { const l = v.liq(d); return l == null || l >= codeeMinLiq; });
    }
    if (!rows.length) {
      tb.innerHTML = `<tr><td colspan="${v.cols.length}" style="text-align:center;color:var(--text-3);padding:18px;">${v.empty || 'No data.'}</td></tr>`;
      return;
    }
    tb.innerHTML = rows.map((d) => '<tr>' + v.row(d) + '</tr>').join('');
  }
```

(Rows with `null` liquidity are kept — we don't hide a pool just because the source omitted
the figure; only positive values below the threshold are filtered.)

- [ ] **Step 5: Cache fetched data + re-render on slider input**

Replace `loadCodeeView` (lines 7828–7836) with a version that caches the data:

```javascript
  async function loadCodeeView(view) {
    try {
      const data = await codeeFetch(VIEWS[view].path);
      codeeLastData = data;
      renderCodeeTable(view, data);
    } catch (e) {
      document.getElementById('codeeTbody').innerHTML =
        `<tr><td colspan="7" style="color:var(--red,#e05252);padding:12px;">Codee API error: ${e.message}</td></tr>`;
    }
  }
```

Then wire the slider inside `window.codeeInit` (lines 7901–7913), adding this before
`loadRegime();`:

```javascript
    const liqSlider = document.getElementById('codeeLiqSlider');
    const liqValue = document.getElementById('codeeLiqValue');
    liqSlider.addEventListener('input', () => {
      codeeMinLiq = codeeSliderToLiq(Number(liqSlider.value));
      liqValue.textContent = codeeFmtTvl(codeeMinLiq);
      if (codeeLastData && activeTab !== 'rewards' && activeTab !== 'history') {
        renderCodeeTable(activeTab, codeeLastData);
      }
    });
    liqValue.textContent = codeeFmtTvl(codeeMinLiq);
```

- [ ] **Step 6: Commit**

```bash
git add web/index.html
git commit -m "Codee: add adjustable min-liquidity slider + Liquidez column (default 100k)"
```

- [ ] **Step 7: Manual verification via local harness**

Run: `.venv\Scripts\python -m codee.scripts.local_harness`
Open `http://127.0.0.1:8011/`, click the **Codee** tab, and confirm:
- The slider shows "$100K" by default; the Passive/Loops/Cross-Chain tables each show a
  **Liquidez** column.
- Dragging the slider left toward $10k reveals more (thinner) pools, including Aave Sonic
  USDC (`Sonic / aave-v3 / USDC`, ~$0.28M) once the threshold drops below ~$280k.
- Dragging right hides thin pools; the Rewards and History tabs show NO slider.
- No console errors.
Stop the harness (Ctrl+C) when done.

---

### Task 6: Mirror the backend changes into the standalone AAVE_STRAT repo

**Files (in `F:\codefee\AAVE_STRAT`):**
- Modify: `config/config.py` (MIN_TVL_USD default)
- Modify: `services/routes/analyzer.py` (`CrossChainCarry` + `cross_chain_carry`)
- Modify: `services/api/models.py` (`CrossChainRoute`)
- Modify: `services/api/router.py` (`routes_crosschain`)
- Modify: matching tests under `tests/`

> The standalone repo uses bare imports (`from services...`) instead of `from codee.services...`.
> Apply the **same code edits** as Tasks 1–3 (NOT the frontend — AAVE_STRAT's `web/index.html`
> is the dead standalone UI). The diffs are identical except for the import prefix, which these
> files don't change.

- [ ] **Step 1: Apply the four backend edits**

In `F:\codefee\AAVE_STRAT`, make the identical changes from:
- Task 1 Step 3 → `config/config.py` (`MIN_TVL_USD: float = 10_000`)
- Task 2 Step 3 → `services/routes/analyzer.py` (add field + rewrite `cross_chain_carry`)
- Task 3 Step 3 → `services/api/models.py` (add `available_liquidity_usd` to `CrossChainRoute`)
- Task 3 Step 4 → `services/api/router.py` (populate the field)

- [ ] **Step 2: Apply the matching test edits**

Apply Task 1 Step 1, Task 2 Step 1, and Task 3 Step 1 test changes to the corresponding
files under `F:\codefee\AAVE_STRAT\tests\` (same content, bare imports already in place).

- [ ] **Step 3: Run the standalone suite**

Run (from `F:\codefee\AAVE_STRAT`): `.venv\Scripts\pytest -q`
Expected: PASS.

- [ ] **Step 4: Commit (in AAVE_STRAT)**

```bash
git add config/config.py services/routes/analyzer.py services/api/models.py services/api/router.py tests/
git commit -m "Mirror liquidity-filter backend: 10k dust floor + cross-chain available_liquidity_usd"
```

---

### Task 7: Deploy to production (199.247.3.163)

> Same git-bundle path used for the original integration (the server has no GitHub creds).
> Do this only after Tasks 1–5 are merged on the `Volume_tracker` side and the user approves
> deploying. The password must NOT be written into any file — use the existing SSH workflow.

- [ ] **Step 1: Confirm the working tree is clean and tests pass**

Run (from `Volume_tracker`): `.venv\Scripts\pytest codee/tests/ -q`
Expected: PASS. Then `git status` — only intended commits, nothing uncommitted.

- [ ] **Step 2: Build the bundle, transfer, fetch+merge on the server, restart**

Follow the runbook in `codee/DEPLOY.md` (git bundle → SFTP → `git fetch` + `git merge --ff-only`
→ `systemctl restart bigdeposits`). No new pip deps this time (no `pydantic-settings`-style
addition).

- [ ] **Step 3: Verify live**

- `curl -s http://127.0.0.1:8000/api/codee/health` (on the server) → 200, `pool_count_in_scope`
  noticeably higher than before (was ~209-ish under $1M; now ~323 under $10k).
- `curl -s http://127.0.0.1:8000/api/codee/routes/crosschain` → rows include `available_liquidity_usd`.
- Open the dashboard → Codee tab → slider present, default $100K, Sonic USDC appears when
  dragged below ~$280k.
- `curl -s http://127.0.0.1:8000/api/orders` → 200 (VT not regressed).

---

## Self-review notes

- **Spec coverage:** dust floor (Task 1), available_liquidity field (Tasks 2-3), slider +
  Liquidez column + anti-pollution-via-filter (Task 5), keep `high_utilization` (untouched —
  no task needed), repo mirror (Task 6), deploy (Task 7). All spec sections mapped.
- **Golden test:** confirmed unaffected (Task 2 Step 5) — `_pipeline` hardcodes its own filter.
- **Type consistency:** `available_liquidity_usd: float | None` is identical across the
  dataclass (Task 2), the Pydantic model (Task 3), and the JS accessor `d.available_liquidity_usd`
  (Task 5). Passive uses `d.tvl_usd`, loops use `d.min_tvl_usd` — both pre-existing fields.
- **No new DB column / migration:** `tvl_usd`, `total_supply_usd`, `total_borrow_usd` already
  stored; cross-chain liquidity is derived in pure code from `tvlUsd`.
