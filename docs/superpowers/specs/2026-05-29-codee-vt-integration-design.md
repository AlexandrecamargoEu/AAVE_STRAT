# Codee → Volume_tracker Integration — Design

**Date:** 2026-05-29
**Author:** Alexandre + Claude
**Status:** Spec, pending review. Incorporates fixes from an adversarial workflow review (6 reviewers + synthesis) of the initial plan.
**Projects:** source `F:\codefee\AAVE_STRAT` (Codee, Phase 1a complete) → host `F:\codefee\Volume_tracker` (VT)

---

## 1. Goal

Surface Codee's data inside the existing Volume_tracker dashboard as a new native sidebar tab, in a single process / single port. Codee's ingestor and REST router plug into VT's existing FastAPI app and event loop. No separate process, no CORS.

**Non-negotiable constraint: Codee must never crash VT.** VT tracks live exchange volume in production; a Codee fault (import error, migration failure, ingest exception) must degrade to "tab absent, VT fully operational", never to "VT down".

---

## 2. Verified facts (resolved the two highest risks)

Confirmed via read-only SSH to the production server (`199.247.3.163`) on 29-mai-2026:

- **Production entrypoint = VT-root `main.py`.** `bigdeposits.service` runs `ExecStart=/opt/bigdeposits/venv/bin/python main.py`, `WorkingDirectory=/opt/bigdeposits`. So wiring into VT-root `main.py` + `services/big_orders/service.py` is the CORRECT target. `bigdeposits_system/` is just a subfolder, not the entrypoint.
- **No pydantic v1/v2 conflict.** Server venv has pydantic **2.12.5**, fastapi 0.129.0, aiohttp 3.13.3, sqlalchemy 2.0.46, aiosqlite 0.22.1, uvicorn 0.40.0, requests 2.32.5. Python 3.13.7.
- **One real dependency gap:** `pydantic-settings` is NOT in the server venv. Codee imports it at module top → must `pip install` before restart. `apscheduler` is declared by Codee but unused (asyncio.sleep instead) → drop it.

These two facts were the blocking unknowns. Both resolve in favor of proceeding.

---

## 3. Architecture (unchanged from brainstorm, validated)

Codee becomes an isolated package `Volume_tracker/codee/`. VT's own `config/`, `db/`, `services/`, `web/` are untouched (they have homonymous names — the `codee.` import prefix keeps namespaces distinct). VT's `main.py` gains the Codee ingestor (guarded) in its `asyncio.gather`, and `services/big_orders/service.py` registers the Codee router on the shared `bo_app`. Codee keeps its own SQLite (`codee/data/codee.db`); VT's QuestDB is untouched. Frontend: a new `sectionCodee` page + sidebar button in VT's monolithic `web/index.html`, built with VT's native CSS (`.spread-table`, `.mm-routes-tab`), NOT Codee's standalone styling.

---

## 4. File structure

```
Volume_tracker/                       (git repo, branch main → work on codee-integration)
├── codee/                            ← NEW isolated package
│   ├── __init__.py                      ← MUST create (AAVE_STRAT has no root __init__)
│   ├── config/  db/  sources/  services/  scripts/
│   ├── tests/
│   ├── conftest.py  (or pyproject.toml) ← carries testpaths + asyncio_mode='auto'
│   ├── .env                             (gitignored)
│   └── data/codee.db                    (gitignored, incl. -wal/-shm)
├── config/  db/  services/  bigdeposits_system/   ← VT, UNTOUCHED
├── web/index.html                    ← VT, + sidebar button + sectionCodee page + Codee JS (IIFE)
├── main.py                           ← VT, + guarded Codee wiring
└── services/big_orders/service.py    ← VT, + codee_db param + router registration
```

**Not moved:** AAVE_STRAT `.git`, `docs/`, PoC scripts (`demo_*.py`, `poc_*.py`, `export_snapshot.py`), standalone `web/index.html` (discarded), Codee's `main.py` (its ingestor+router are wired into VT's main.py; the uvicorn bootstrap is NOT carried over — VT already runs the server).

**Two repos diverge:** AAVE_STRAT standalone stays on GitHub as the Phase 1a snapshot. Live development continues inside VT.

---

## 5. The fixes (from the adversarial review — these replace the naive initial plan)

### 5.1 Package & imports (review critical #4)
- **Create `codee/__init__.py`** — without it `import codee.*` won't resolve.
- **Rewrite every bare internal import** (`from config.`, `from db.`, `from services.`, `from sources.`) to the `codee.` prefix, in production AND test files. Use an AST-based rewrite (libcst) not regex, to avoid partial matches.
- **Relocate `pyproject.toml`** — do not leave AAVE_STRAT's pyproject pip-installable as a dist named `codee`. Move its `[tool.pytest.ini_options]` (testpaths, asyncio_mode='auto') into `codee/conftest.py` or `codee/pyproject.toml`.
- **Smoke test:** assert every `codee.*` submodule's resolved `__file__` is under `.../codee/`; CI grep fails on any residual `from (config|db|services|sources)\.` in `codee/`. Verify `python -c "import codee, codee.config.config, codee.db.sqlite_client"` from VT root, and `pytest codee/tests` runs (async tests execute, not skip).

### 5.2 Config & paths (review important)
- **DB path absolute, `__file__`-anchored:** `CODEE_DB_PATH` default → `str(CONFIG_DIR.parent / "data" / "codee.db")` = `Volume_tracker/codee/data/codee.db`. Removes the CWD-relative default that would land in VT's `data/`.
- **`env_prefix='CODEE_'`** on the Settings model — VT and Codee share `os.environ`; namespacing prevents a VT env var from overriding a Codee setting.
- **Remove dead settings** `API_HOST`/`API_PORT` (Codee no longer runs its own uvicorn).
- **`.env` already resolves** via `CONFIG_DIR.parent / ".env"` → `codee/.env`, separate from VT's `.env`. Update `.env.example` to drop/absolutize `CODEE_DB_PATH` so a copied relative value can't override the good default.

### 5.3 gitignore (review important)
Append to VT's `.gitignore`: `codee/.env`, `codee/data/`, and defensive `*.db-wal` / `*.db-shm` (the existing `*.db` misses WAL/SHM sidecar files). Verify with `git check-ignore -v codee/data/codee.db-wal`.

### 5.4 Dependencies (review critical #2, narrowed by SSH)
- **Append to `requirements.txt`** (the merged server spec): `pydantic-settings>=2.4`. Everything else Codee needs is already on the server.
- **Drop** `apscheduler` (unused) and `requests` (only used by one-off PoC scripts that aren't moved); change `sqlalchemy[asyncio]` to plain `sqlalchemy>=2.0` (server has 2.0.46).
- **Deploy procedure must `pip install -r requirements.txt` BEFORE `systemctl restart`** — otherwise the new top-level import crashes the service.

### 5.5 Backend fail-open — THREE guards (review critical #2 + #3)
VT's `main.py` uses `asyncio.gather(..., return_exceptions=False)`, so any escaped exception kills ALL VT tasks. The naive single try/except does NOT cover module-top imports, `apply_migrations()`, or an exception escaping the running task. Required:

**(a) Guard the imports** (module top of VT main.py):
```python
try:
    from codee.db.sqlite_client import SqliteClient as CodeeDB
    from codee.services.pools.ingestor import PoolsIngestor as CodeeIngestor
    from codee.services.api.router import router as codee_router, set_db as codee_set_db
except Exception:
    CodeeDB = CodeeIngestor = codee_router = codee_set_db = None
    logging.getLogger("codee").exception("[Codee] import failed — VT continues without Codee")
```

**(b) Guard init inside main()** — append the task only on success:
```python
codee_db = None
codee_ingestor = None
if CodeeDB is not None:
    try:
        codee_db = CodeeDB()
        await codee_db.connect()
        await codee_db.apply_migrations()
        codee_ingestor = CodeeIngestor(codee_db)
    except Exception:
        codee_db = None; codee_ingestor = None
        log.exception("[Codee] init failed — VT continues without Codee")
```

**(c) Never-raises supervisor** wrapping the run loop (do NOT change gather's `return_exceptions` for all VT tasks):
```python
async def _codee_guarded():
    if codee_ingestor is None:
        return
    try:
        await codee_ingestor.run()
    except Exception:
        log.exception("[Codee] ingestor crashed — VT unaffected")
# ... in the _tasks list: _codee_guarded()
```

### 5.6 Router plumbing (review critical #3)
In `services/big_orders/service.py::run_big_orders_server()`: add `codee_db=None` param; register the router ONLY when present so we never expose endpoints that all 503:
```python
if codee_db is not None and codee_router is not None:
    codee_set_db(codee_db)
    bo_app.include_router(codee_router)   # /api/codee/* — distinct prefix, no collision
```
**And pass it at the call site** in main.py (the bug the review caught): `run_big_orders_server(..., codee_db=codee_db)`.

### 5.7 Event-loop performance (review important)
The ingestor's transform (JOIN + build_rebate_lookup + overlay + filter + validate over ~20k pools) is **synchronous CPU work** that would stall VT's shared event loop (its WS/order processing is latency-sensitive). Wrap that block in `await asyncio.to_thread(...)`. Also replace per-row `execute`+`commit` in `snapshot.py`/`sqlite_client.py` with `executemany` + a single commit. Time the worst-case stall before wiring into prod.

### 5.8 Frontend — native port with mandatory JS (review critical #5)
VT's page-swap is generic, but data lazy-load/refresh is a hardcoded if-ladder with no `sectionCodee` branch, and the inline script is one flat global scope. Required:
- **Sidebar button** between Margins and the bottom-pinned Config item.
- **Nav handler branch:** `if (btn.dataset.section==='sectionCodee'){ if(!codeeInitDone){codeeInitDone=true; codeeInit();} else codeeRefresh(); }`
- **Gated timer:** `setInterval(()=>{ if(codeeInitDone) codeeRefresh(); }, 60000)` — lazy, matches VT's "fetch only when tab opened" convention (no eager load).
- **IIFE / namespace isolation** — all Codee JS wrapped, globals prefixed (`codeeState`, `codeeFetch`, `codeeFmtApy`). NEVER bare `fmt`/`pct`/`data`/`state`/`render*` (would clobber VT's `fmt`, `pct`, `currentPeriod`, `DATA`, `renderSpreadTable`).
- **Own sub-tab handler** for `#sectionCodee .mm-routes-tab` (VT's existing one is hard-scoped to `#sectionMargins`).
- **Reuse** `.spread-table`/`.pos`/`.neg`/`.mm-routes-tab` CSS, but author Codee's own thead/tbody + render fn (NOT the gold-bound `renderSpreadTable`).
- 5 sub-tabs: Passive / Loops / Cross-Chain / Rewards / History. Cross-Chain keeps the "pre-bridge ceiling" caveat as a discreet `.spread-table-header`, not a loud banner.

### 5.9 Git isolation (review minor)
VT is on `main` with uncommitted tracked changes (`config/config.py`, `web/index.html`, scripts). `web/index.html` is one of them → both the user's pending edit and Codee's edit touch it. Plan: `git switch -c codee-integration` from main (the tracked-modified files follow the branch; no stash needed). User decides whether to commit pending work first. Integration happens on this branch; merge to main after local validation.

---

## 6. Testing & validation

1. **Codee unit tests:** `pytest codee/tests` from VT root — all 75 pass after the import-prefix rewrite (criterion: same pass count as standalone).
2. **VT regression:** confirm VT boots and its existing tabs work before and after — Codee must not regress anything.
3. **Integration smoke (local):** run VT's `main.py` locally → (a) VT boots + Codee tab appears; (b) **simulated Codee import/migration failure leaves VT running with no tab** (fail-open proven — temporarily break an import and confirm VT still serves); (c) `/api/codee/*` returns data, not 503; (d) opening the tab triggers fetch + 60s refresh ONLY after first open.

---

## 7. Deploy (documented, NOT this session)

After local validation and user approval:
1. `pip install -r requirements.txt` on the server venv (gets `pydantic-settings`) — BEFORE restart.
2. `scp` `codee/.env` separately (gitignored, won't be in the bundle).
3. Deliver code via the VT's existing `git bundle` over scp mechanism.
4. `systemctl restart bigdeposits`; verify VT up + Codee tab + existing tabs OK.
5. Rollback ready: previous commit + restart.
6. **Prerequisite:** rotate the root passwords exposed in chat / VT CLAUDE.md and move to SSH keys.

---

## 8. Open questions

1. **Pending VT changes** — the user decides: commit their uncommitted work first, or let it ride on the integration branch. (`web/index.html` overlap means a conscious choice is needed.)
2. **Tab label** — "Codee" / "Yield" / "Lending"? (default: "Codee")
3. **VT refresh coordination** — does VT have a global refresh loop the Codee tab should hook into instead of its own `setInterval`? Confirm during frontend implementation by reading VT's existing refresh convention.

---

## Appendix — review provenance

This spec's §5 fixes come from an adversarial workflow review (6 parallel reviewers each probing one dimension against the real code in both projects, + synthesis). Verdict was "architecture sound, NOT safe to integrate as initially written" — 11 critical findings, of which the deploy-target and pydantic-conflict risks were retired by the SSH check, and the remaining (fail-open, router plumbing, package init, frontend JS) are addressed in §5.
