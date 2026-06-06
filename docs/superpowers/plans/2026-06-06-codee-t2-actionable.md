# Codee T2 — Actionable-Protocol Filter Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Kill non-executable "junk" yields (peapods 507%, y2k 639%…) from the Multi-Hop route graph and label them everywhere else — using DefiLlama's protocol `category` as a self-maintaining whitelist ("Lending" → actionable) plus a tiny manual override file.

**Architecture:** New DefiLlama fetch (`api.llama.fi/protocols` → `{slug: category}`) cached per ingest tick as `protocol_categories.json` (same JSON-cache pattern as `aci_incentives.json` — no DB schema change). A pure classifier (`is_actionable`) combines category + overrides. Read-time: `/routes/multihop` filters its pool universe to actionable protocols BEFORE pathfinding (unblocks the beam → 3/4-hop routes appear); `/routes/passive` gains an `actionable` flag; the dashboard's Passive view hides non-actionable rows by default behind a "Show non-lending" toggle (never silently dropped — toggle reveals, marker labels). **Fail-open rule:** empty/missing category cache → no filtering, everything actionable (a DefiLlama hiccup must not blank the radar).

**Decisions locked (Alexandre, 06-jun-2026):** overrides include = `spark-savings`, `sky-lending`, `ethena-usde` (big, real, executable supply-side yields despite non-Lending category); overrides exclude = `radiant-v2` (exploited twice, dead TVL), `credit`, `permapod` (tiny/suspicious). Loops/Cross-Chain views NOT filtered in this pass (junk rarely has the borrow side they need; revisit if it shows up).

**Tech Stack:** Python 3.13, FastAPI, pydantic v2, aiohttp, pytest (offline); vanilla JS in `web/index.html`.

**Where:** Backend in `F:\codefee\Volume_tracker\codee\…` on branch `codee-t2-actionable` (create from `main`), mirrored to `F:\codefee\AAVE_STRAT\…` (bare imports, NO frontend; branch from `master`). Test cmd (Bash, from VT): `PYTHONIOENCODING=utf-8 .venv/Scripts/pytest codee/tests/ -q`.

**Validation evidence (live, 06-jun):** all 176 snapshot projects have a DefiLlama category (0 unmapped); category caught every junk case (peapods→Yield, y2k→Derivatives, vesper/yearn/beefy→Yield Aggregator) and every real lender (incl. maple/aave-v4/lista-lending that the has-borrow-side heuristic would miss).

---

### Task 1: DefiLlama client — fetch protocol categories

**Files:**
- Modify: `codee/sources/defillama/client.py`
- Test: `codee/tests/test_defillama_client.py`

- [ ] **Step 1: Write the failing test** — append to `codee/tests/test_defillama_client.py` (mirror the file's existing stub-session idiom — read it first):

```python
async def test_fetch_protocol_categories_maps_slug_to_category():
    payload = [
        {"slug": "aave-v3", "category": "Lending", "tvl": 1},
        {"slug": "peapods-finance", "category": "Yield"},
        {"slug": "broken-entry"},                      # no category -> skipped
        {"category": "Lending"},                       # no slug -> skipped
    ]

    class FakeResp:
        async def __aenter__(self): return self
        async def __aexit__(self, *a): pass
        def raise_for_status(self): pass
        async def json(self): return payload

    class FakeSession:
        def get(self, url):
            assert "api.llama.fi/protocols" in url
            return FakeResp()

    from codee.sources.defillama.client import DefiLlamaClient
    c = DefiLlamaClient(session=FakeSession())
    out = await c.fetch_protocol_categories()
    assert out == {"aave-v3": "Lending", "peapods-finance": "Yield"}
```

- [ ] **Step 2: Run — expect FAIL** (method missing):
`PYTHONIOENCODING=utf-8 .venv/Scripts/pytest codee/tests/test_defillama_client.py -v`

- [ ] **Step 3: Implement** — in `codee/sources/defillama/client.py`, add the URL const next to the others and the method after `_get_json`:
```python
PROTOCOLS_URL = "https://api.llama.fi/protocols"
```
```python
    async def fetch_protocol_categories(self) -> dict[str, str]:
        """{project slug: category} from api.llama.fi/protocols (T2 actionable filter).
        'Lending' category = plain lending platform. Entries lacking slug/category
        are skipped; non-list payloads yield {}."""
        data = await self._get_json(PROTOCOLS_URL)
        if not isinstance(data, list):
            return {}
        return {p["slug"]: p["category"] for p in data
                if isinstance(p, dict) and p.get("slug") and p.get("category")}
```

- [ ] **Step 4: Run — expect PASS** (whole file)
- [ ] **Step 5: Commit**
```bash
git add codee/sources/defillama/client.py codee/tests/test_defillama_client.py
git commit -m "T2-1: DefiLlama client fetches protocol categories (slug -> category)"
```

---

### Task 2: Overrides config + pure classifier

**Files:**
- Create: `codee/config/actionable_overrides.json`
- Modify: `codee/config/config.py` (loader)
- Create: `codee/services/pools/actionable.py`
- Test: `codee/tests/test_actionable.py`

- [ ] **Step 1: Create the overrides file** — `codee/config/actionable_overrides.json`:
```json
{
  "_comment": "T2 manual exceptions to the category-based actionable rule (cat == 'Lending'). include: actionable despite non-Lending category. exclude: NOT actionable despite Lending category.",
  "include": ["spark-savings", "sky-lending", "ethena-usde"],
  "exclude": ["radiant-v2", "credit", "permapod"]
}
```

- [ ] **Step 2: Add the loader** in `codee/config/config.py` (next to the other `load_*`):
```python
def load_actionable_overrides() -> dict:
    return _load_json("actionable_overrides.json")
```

- [ ] **Step 3: Write the failing tests** — `codee/tests/test_actionable.py`:
```python
from codee.services.pools.actionable import is_actionable

CATS = {"aave-v3": "Lending", "peapods-finance": "Yield",
        "spark-savings": "Yield", "radiant-v2": "Lending"}
OVR = {"include": ["spark-savings"], "exclude": ["radiant-v2"]}


def test_lending_category_is_actionable():
    assert is_actionable("aave-v3", CATS, OVR) is True


def test_non_lending_is_not_actionable():
    assert is_actionable("peapods-finance", CATS, OVR) is False


def test_include_override_wins_over_category():
    assert is_actionable("spark-savings", CATS, OVR) is True


def test_exclude_override_wins_over_category():
    assert is_actionable("radiant-v2", CATS, OVR) is False


def test_unknown_project_fails_open():
    # a project missing from the category map must NOT be dropped (fail-open)
    assert is_actionable("brand-new-protocol", CATS, OVR) is True


def test_empty_map_fails_open():
    assert is_actionable("peapods-finance", {}, OVR) is True
```

- [ ] **Step 4: Run — expect FAIL** (module missing):
`PYTHONIOENCODING=utf-8 .venv/Scripts/pytest codee/tests/test_actionable.py -v`

- [ ] **Step 5: Implement** — `codee/services/pools/actionable.py`:
```python
"""T2 actionable-protocol classification (pure — no I/O).

Rule: a protocol is 'actionable' (a plain lending platform whose quoted rates an
executor can actually capture by depositing/borrowing) iff its DefiLlama category
is 'Lending', with a small manual override list on top (include beats category,
exclude beats category, include beats exclude is irrelevant — keep them disjoint).

FAIL-OPEN: an empty category map (fetch failed, cache missing) or an unknown
project classifies as actionable — a DefiLlama hiccup must never blank the radar.
"""


def is_actionable(project: str, categories: dict[str, str], overrides: dict) -> bool:
    if project in (overrides.get("exclude") or []):
        return False
    if project in (overrides.get("include") or []):
        return True
    if not categories:
        return True                       # fail-open: no data, no filtering
    cat = categories.get(project)
    if cat is None:
        return True                       # fail-open: unknown project
    return cat == "Lending"
```

- [ ] **Step 6: Run — expect PASS** (all 6)
- [ ] **Step 7: Commit**
```bash
git add codee/config/actionable_overrides.json codee/config/config.py codee/services/pools/actionable.py codee/tests/test_actionable.py
git commit -m "T2-2: pure actionable classifier (Lending category + manual overrides, fail-open)"
```

---

### Task 3: Ingestor — fetch + cache categories (keep stale on failure)

**Files:**
- Modify: `codee/config/config.py` (Settings field)
- Modify: `codee/services/pools/ingestor.py`
- Test: `codee/tests/test_pools_ingestor.py`

- [ ] **Step 1: Write the failing test** — append to `codee/tests/test_pools_ingestor.py` (reuse the existing `db` fixture, `_supply_pool`/`_borrow_pool` helpers, `StubDefiLlama`, `StubMerkl`, `StubBinance` — read the file first; `StubDefiLlama` gains the categories method):
```python
async def test_ingestor_writes_protocol_categories_cache(db, tmp_path, monkeypatch):
    import json as _json
    from codee.config.config import settings
    cache = tmp_path / "cats.json"
    monkeypatch.setattr(settings, "PROTOCOL_CATEGORIES_CACHE", str(cache), raising=False)
    monkeypatch.setattr(settings, "BINANCE_WITHDRAW_CACHE", str(tmp_path / "bw.json"), raising=False)
    monkeypatch.setattr(settings, "ACI_INCENTIVES_CACHE", str(tmp_path / "aci.json"), raising=False)

    supply = [_supply_pool("p1", "Ethereum", "aave-v3", "USDC", base=3.0, tvl=5_000_000)]
    borrow = [_borrow_pool("p1")]
    dl = StubDefiLlama(supply, borrow)
    dl.categories = {"aave-v3": "Lending", "peapods-finance": "Yield"}
    ing = PoolsIngestor(db, dl, StubMerkl([]), binance=StubBinance([]))
    await ing.run_once(ts=1716800000)

    saved = _json.loads(cache.read_text())
    assert saved == {"aave-v3": "Lending", "peapods-finance": "Yield"}


async def test_ingestor_keeps_stale_categories_cache_on_fetch_failure(db, tmp_path, monkeypatch):
    import json as _json
    from codee.config.config import settings
    cache = tmp_path / "cats.json"
    cache.write_text(_json.dumps({"aave-v3": "Lending"}))      # pre-existing cache
    monkeypatch.setattr(settings, "PROTOCOL_CATEGORIES_CACHE", str(cache), raising=False)
    monkeypatch.setattr(settings, "BINANCE_WITHDRAW_CACHE", str(tmp_path / "bw.json"), raising=False)
    monkeypatch.setattr(settings, "ACI_INCENTIVES_CACHE", str(tmp_path / "aci.json"), raising=False)

    supply = [_supply_pool("p1", "Ethereum", "aave-v3", "USDC", base=3.0, tvl=5_000_000)]
    borrow = [_borrow_pool("p1")]
    dl = StubDefiLlama(supply, borrow)
    dl.categories = {}                                          # fetch "failed" / empty
    ing = PoolsIngestor(db, dl, StubMerkl([]), binance=StubBinance([]))
    await ing.run_once(ts=1716800000)

    saved = _json.loads(cache.read_text())
    assert saved == {"aave-v3": "Lending"}                     # stale kept, NOT clobbered
```
Add to the existing `StubDefiLlama` class (single place):
```python
    categories: dict = {}
    async def fetch_protocol_categories(self):
        return self.categories
```
(as a default so existing tests keep working; if the class uses `__init__` without class attrs, set `self.categories = {}` there instead.)

- [ ] **Step 2: Run — expect FAIL**
- [ ] **Step 3: Add the cache-path setting** in `codee/config/config.py` `Settings` (next to `ACI_INCENTIVES_CACHE`):
```python
    PROTOCOL_CATEGORIES_CACHE: str = str(CONFIG_DIR.parent / "data" / "protocol_categories.json")
```
- [ ] **Step 4: Wire into the ingestor** — in `codee/services/pools/ingestor.py`, extend the defillama context block to also fetch categories in the same gather (guarded by being inside the existing try-structure; an exception there already fails the tick — instead fetch it SEPARATELY guarded so a categories failure is non-fatal):
```python
        categories: dict = {}
        try:
            async with (self._defillama or DefiLlamaClient()) as dl2:
                categories = await dl2.fetch_protocol_categories()
        except Exception:
            log.exception("[Ingestor] protocol categories fetch failed (non-fatal)")
```
ADAPT: check how the ingestor stores its defillama source (`self._defillama`?) and whether the main `async with defillama` block can be extended with a 5th gather task instead — PREFER adding `cats_task = asyncio.create_task(defillama.fetch_protocol_categories())` to the EXISTING gather wrapped so its failure is non-fatal: use `asyncio.gather(..., return_exceptions=False)` is already in place for the required feeds; simplest correct shape: add the task to the existing gather and wrap ONLY the categories fetch inside a small helper that swallows exceptions:
```python
            async def _cats_safe():
                try:
                    return await defillama.fetch_protocol_categories()
                except Exception:
                    log.exception("[Ingestor] protocol categories fetch failed (non-fatal)")
                    return {}
            cats_task = asyncio.create_task(_cats_safe())
```
and unpack `categories` from the gather. After the ACI-cache block, persist — ONLY when non-empty (keep stale cache on failure):
```python
        if categories:
            try:
                cats_cache = Path(settings.PROTOCOL_CATEGORIES_CACHE)
                cats_cache.parent.mkdir(parents=True, exist_ok=True)
                cats_cache.write_text(json.dumps(categories))
            except Exception:
                log.exception("[Ingestor] categories cache write failed (non-fatal)")
```
(Write the FULL map, not just snapshot projects — ~600 Lending entries ≈ 300KB once a tick; simpler and lets read-time classify projects that enter the snapshot between ticks.)

- [ ] **Step 5: Run the FULL ingestor file + full suite** — ALL PASS (existing StubDefiLlama instances must keep working via the class-attr default).
- [ ] **Step 6: Commit**
```bash
git add codee/config/config.py codee/services/pools/ingestor.py codee/tests/test_pools_ingestor.py
git commit -m "T2-3: ingestor caches DefiLlama protocol categories (non-fatal, keeps stale on failure)"
```

---

### Task 4: API — multihop filters to actionable; passive gains the flag

**Files:**
- Modify: `codee/services/api/models.py` (PassiveRoute)
- Modify: `codee/services/api/router.py`
- Test: `codee/tests/test_api.py`

- [ ] **Step 1: Write the failing tests** — append to `codee/tests/test_api.py` (mirror existing fixture idioms):
```python
async def test_multihop_excludes_non_actionable_protocols(app, tmp_path, monkeypatch):
    app_, db = app
    import time, json as _json
    from codee.config.config import settings
    bw = tmp_path / "bw.json"
    bw.write_text(_json.dumps({"withdraw": {"USDC": ["ChainA", "ChainB"]},
                               "deposit":  {"USDC": ["ChainA"]}}))
    cats = tmp_path / "cats.json"
    cats.write_text(_json.dumps({"aave-v3": "Lending", "peapods-finance": "Yield"}))
    monkeypatch.setattr(settings, "BINANCE_WITHDRAW_CACHE", str(bw), raising=False)
    monkeypatch.setattr(settings, "PROTOCOL_CATEGORIES_CACHE", str(cats), raising=False)
    monkeypatch.setattr(settings, "ACI_INCENTIVES_CACHE", str(tmp_path / "none.json"), raising=False)
    now = int(time.time())
    rows = [("a1", "ChainA", "aave-v3", "USDC", 4e6, 3.0, 2.0, 0.80),
            ("x1", "ChainB", "peapods-finance", "USDC", 1e5, 507.0, None, None)]
    for pid, ch, pr, sym, tvl, sup, bor, ltv in rows:
        await db.execute("""INSERT INTO pools_snapshot
            (pool_id,chain,project,symbol,tvl_usd,supply_apy_base,borrow_apr_base,ltv,updated_at)
            VALUES (?,?,?,?,?,?,?,?,?)""", (pid, ch, pr, sym, tvl, sup, bor, ltv, now))
    transport = ASGITransport(app=app_)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        body = (await ac.get("/api/codee/routes/multihop")).json()
    projects = {n["project"] for r in body for n in r["path"]}
    assert "peapods-finance" not in projects       # junk never enters the graph
    assert "aave-v3" in projects                   # real lender does


async def test_passive_routes_carry_actionable_flag(app, tmp_path, monkeypatch):
    app_, db = app
    import time, json as _json
    from codee.config.config import settings
    cats = tmp_path / "cats.json"
    cats.write_text(_json.dumps({"aave-v3": "Lending", "peapods-finance": "Yield"}))
    monkeypatch.setattr(settings, "PROTOCOL_CATEGORIES_CACHE", str(cats), raising=False)
    now = int(time.time())
    await db.execute("""INSERT INTO pools_snapshot (pool_id,chain,project,symbol,tvl_usd,supply_apy_base,updated_at)
                        VALUES ('a1','Ethereum','aave-v3','USDC',5e6,3.0,?)""", (now,))
    await db.execute("""INSERT INTO pools_snapshot (pool_id,chain,project,symbol,tvl_usd,supply_apy_base,updated_at)
                        VALUES ('x1','Sonic','peapods-finance','USDC',1e5,507.0,?)""", (now,))
    transport = ASGITransport(app=app_)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        body = (await ac.get("/api/codee/routes/passive")).json()
    aave = next(r for r in body if r["project"] == "aave-v3")
    pea = next(r for r in body if r["project"] == "peapods-finance")
    assert aave["actionable"] is True
    assert pea["actionable"] is False


async def test_missing_categories_cache_fails_open(app, tmp_path, monkeypatch):
    app_, db = app
    import time
    from codee.config.config import settings
    monkeypatch.setattr(settings, "PROTOCOL_CATEGORIES_CACHE", str(tmp_path / "absent.json"), raising=False)
    now = int(time.time())
    await db.execute("""INSERT INTO pools_snapshot (pool_id,chain,project,symbol,tvl_usd,supply_apy_base,updated_at)
                        VALUES ('x1','Sonic','peapods-finance','USDC',1e5,507.0,?)""", (now,))
    transport = ASGITransport(app=app_)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        body = (await ac.get("/api/codee/routes/passive")).json()
    assert body[0]["actionable"] is True           # fail-open: no data, no judgement
```

- [ ] **Step 2: Run — expect FAIL** (`actionable` key missing)
- [ ] **Step 3: Implement**

`codee/services/api/models.py` — `PassiveRoute` gains (last field):
```python
    actionable: bool = True               # False = not a plain lending deposit (T2)
```

`codee/services/api/router.py` — extend imports (`load_actionable_overrides` from config; `is_actionable` from `codee.services.pools.actionable`); add a loader next to `_load_aci_map`:
```python
def _load_categories() -> dict[str, str]:
    """Protocol-categories cache ({project: category}); {} if absent (fail-open)."""
    try:
        return json.loads(Path(settings.PROTOCOL_CATEGORIES_CACHE).read_text())
    except Exception:
        return {}
```
In `routes_passive`: load once (`cats = _load_categories()`, `ovr = load_actionable_overrides()`) and set per route:
```python
            actionable=is_actionable(r.project, cats, ovr),
```
In `routes_multihop`: filter the universe BEFORE pathfinding:
```python
    cats = _load_categories()
    ovr = load_actionable_overrides()
    pools = [p for p in pools if is_actionable(p.get("project"), cats, ovr)]
```
(`is_actionable` fails open on empty map, so a missing cache leaves `pools` untouched.)

- [ ] **Step 4: Run — full test_api.py + full suite** — ALL PASS.
- [ ] **Step 5: Commit**
```bash
git add codee/services/api/models.py codee/services/api/router.py codee/tests/test_api.py
git commit -m "T2-4: multihop graph filtered to actionable protocols; passive carries the flag (fail-open)"
```

---

### Task 5: Frontend — Passive marker + "Show non-lending" toggle

**Files:** `Volume_tracker/web/index.html` only. No automated test; harness smoke in Step 4.

- [ ] **Step 1: State + toggle HTML** — next to `let codeeWdrawOnly = false;` add `let codeeShowNonActionable = false;`. In `#codeeLiqFilter`, after the Max-hops selector, add a label+checkbox mirroring the EXACT markup/style of `#codeeWdrawWrap` (read it first):
```html
            <label style="display:flex;align-items:center;gap:4px;cursor:pointer;" id="codeeNonActWrap">
              <input type="checkbox" id="codeeNonActChk" style="accent-color:var(--accent);cursor:pointer;">
              <span>Show non-lending</span>
            </label>
```
(match the wdraw label's actual inline style/visibility mechanism — if it's `display:none` toggled per tab, mirror that, but show this one on the passive tab at least; simplest consistent choice following the file's existing pattern.)

- [ ] **Step 2: Filter + marker** — in `renderCodeeTable`, after the hops filter:
```javascript
    if (!codeeShowNonActionable) {
      rows = rows.filter((d) => d.actionable !== false);
    }
```
(`!== false` keeps rows without the field — other views unaffected.) In `VIEWS.passive.row`, append a marker to the project cell when `d.actionable === false` (adapt to the actual cell template): render the project as `${d.project}${d.actionable === false ? ' ✗' : ''}` and title-attr `non-lending product — APY not a plain deposit rate` if the file's style supports it simply.

- [ ] **Step 3: Wiring** — in `codeeInit`, mirror the wdrawOnly handler:
```javascript
    const nonActChk = document.getElementById('codeeNonActChk');
    nonActChk.addEventListener('change', () => {
      codeeShowNonActionable = nonActChk.checked;
      if (codeeLastData && activeTab !== 'rewards' && activeTab !== 'history') {
        renderCodeeTable(activeTab, codeeLastData);
      }
    });
```

- [ ] **Step 4: Static + harness smoke** — `grep -c "codeeNonActChk" web/index.html` ≥ 2; start the harness, `curl -s http://127.0.0.1:8011/ | grep -c 'Show non-lending'` → 1; `/api/codee/routes/passive` rows carry `actionable`; kill harness.
- [ ] **Step 5: Commit**
```bash
git add web/index.html
git commit -m "T2-5: Passive hides non-lending rows by default (toggle + marker — never silently dropped)"
```

---

### Task 6: Mirror backend to AAVE_STRAT

Branch `codee-t2-actionable` in `F:\codefee\AAVE_STRAT`. Tasks 1-4 only (NOT Task 5). Bare imports. Same method + escalation rule as previous mirrors (report, don't force-fit). Run full suite (expect ~125 passed, 1 skipped; report exact). Commit:
```bash
git add config services sources tests
git commit -m "T2 (mirror): actionable-protocol filter (category whitelist + overrides)"
```

### Task 7: Deploy (gated on explicit user approval)

> Backend `.py` + config changed → `systemctl restart`. Do NOT deploy without explicit user approval.

- [ ] Full suites green; merge → `main` (VT) / `master` (AAVE_STRAT, push).
- [ ] Bundle from server HEAD (`0d8bf29` unless moved — check), SFTP via the paramiko helper pattern, ff-merge, restart.
- [ ] Verify: service active; `data/protocol_categories.json` written (~600+ entries); `/routes/multihop` top routes NO LONGER peapods (no `peapods-finance` in any path; top net_apy plausible, not 400%+); **hops distribution now includes 3/4-hop routes** (the beam unblocks — this is the acceptance signal); `/routes/passive` rows carry `actionable`; dashboard Passive default view has no 507% row, toggle reveals it with the ✗ marker. Hard-refresh reminder.

---

## Self-review notes

- **Coverage:** category fetch (T1), classifier + overrides incl. the 6 locked decisions (T2), cache with keep-stale (T3), multihop filter + passive flag + fail-open (T4), UI toggle/marker (T5), mirror (T6), deploy+acceptance (T7).
- **Fail-open is load-bearing:** tested at classifier level (empty map → True), API level (absent cache → actionable True), and ingest level (empty fetch → stale cache kept). A DefiLlama outage degrades to pre-T2 behavior, never to an empty radar.
- **Never silently drop:** passive rows stay in the API payload (flag only); UI hides by default but the toggle + ✗ marker surface them. Multihop is the one place rows are genuinely excluded — by design (routes through junk are fiction, not data).
- **Type consistency:** `fetch_protocol_categories() -> dict[str,str]` → cache JSON → `_load_categories()` → `is_actionable(project, cats, ovr)` used by both endpoints; `PassiveRoute.actionable: bool = True` default matches fail-open.
- **No schema change:** JSON cache pattern (3rd instance — binance_withdraw, aci_incentives, protocol_categories).
