# Codee → Volume_tracker Integration Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Integrate the Codee bot (currently `F:\codefee\AAVE_STRAT`) into the existing Volume_tracker (VT) dashboard as an isolated `codee/` package surfaced as a native sidebar tab — single process, single port, and Codee can never crash VT.

**Architecture:** Move Codee's source into `Volume_tracker/codee/` (isolated package; VT's homonymous `config/`/`db/`/`services/` stay untouched, `codee.` import prefix keeps namespaces distinct). VT's `main.py` gains the Codee ingestor (triple-guarded for fail-open) in its `asyncio.gather`; `services/big_orders/service.py` registers Codee's router on the shared `bo_app`. Frontend: a new `sectionCodee` page + sidebar button in VT's monolithic `web/index.html`, built with VT's native CSS, JS wrapped in an IIFE to avoid clobbering VT globals.

**Tech Stack:** Python 3.13, FastAPI (shared `bo_app`), SQLAlchemy+aiosqlite (Codee's own SQLite), aiohttp, pydantic v2 + pydantic-settings, vanilla JS. Reference spec: `docs/superpowers/specs/2026-05-29-codee-vt-integration-design.md`.

**Working directory:** `F:\codefee\Volume_tracker` (the host). Source pulled from `F:\codefee\AAVE_STRAT`.

**Testing reality (important):** VT's full runtime needs QuestDB + exchange credentials, not available locally. So local validation covers: (a) the `codee/` package (its 75 pytest tests), (b) the router mounted in isolation via FastAPI TestClient, (c) the fail-open guard logic as a unit. Full "VT boots with Codee end-to-end" validation happens at server deploy (which has the environment) — documented, not run in this plan.

---

## Task 1: Branch + working venv in Volume_tracker

**Files:**
- Create: `F:\codefee\Volume_tracker\.venv\` (Codee-deps venv for local validation)

- [ ] **Step 1: Confirm VT git state and branch off**

```bash
cd /f/codefee/Volume_tracker
git status --short          # note the pre-existing uncommitted changes (config/config.py, web/index.html, scripts)
git switch -c codee-integration
```
Expected: now on branch `codee-integration`. The uncommitted tracked changes follow the branch (no stash needed). Do NOT commit the user's pending changes — leave them in the working tree; they are theirs to handle.

- [ ] **Step 2: Create a venv with Codee's runtime deps (for local package validation)**

```bash
cd /f/codefee/Volume_tracker
python -m venv .venv
.venv/Scripts/python -m pip install --upgrade pip -q
.venv/Scripts/pip install -q aiohttp aiosqlite "sqlalchemy>=2.0" fastapi uvicorn "pydantic>=2.7" "pydantic-settings>=2.4" python-dotenv pytest pytest-asyncio httpx
```
Expected: clean install. This venv is ONLY for validating the `codee/` package locally — it deliberately does NOT install VT's heavy deps (QuestDB client, exchange connectors), because we are not booting full VT locally.

- [ ] **Step 3: Confirm .venv is gitignored**

```bash
git check-ignore -v .venv 2>/dev/null && echo "ignored" || echo "NOT ignored — must add"
```
If NOT ignored, append `.venv/` to `F:\codefee\Volume_tracker\.gitignore` (do not commit the venv).

- [ ] **Step 4: Commit the branch marker (gitignore only, if changed)**

```bash
# only if .gitignore was modified in step 3
git add .gitignore
git commit -m "Task 1: codee-integration branch + venv gitignore"
```
If `.gitignore` already covered `.venv/`, skip the commit — nothing to record yet.

---

## Task 2: Move Codee source into Volume_tracker/codee/

**Files:**
- Create: `F:\codefee\Volume_tracker\codee\` (the package) + `codee/__init__.py`
- Move: AAVE_STRAT `config/ db/ sources/ services/ scripts/ tests/` → `codee/`

- [ ] **Step 1: Copy Codee source into the package dir**

```bash
cd /f/codefee/Volume_tracker
mkdir -p codee
cp -r /f/codefee/AAVE_STRAT/config   codee/config
cp -r /f/codefee/AAVE_STRAT/db       codee/db
cp -r /f/codefee/AAVE_STRAT/sources  codee/sources
cp -r /f/codefee/AAVE_STRAT/services codee/services
cp -r /f/codefee/AAVE_STRAT/scripts  codee/scripts
cp -r /f/codefee/AAVE_STRAT/tests    codee/tests
cp /f/codefee/AAVE_STRAT/.env.example codee/.env.example
```
Do NOT copy: AAVE_STRAT `main.py`, `web/`, `.git/`, `docs/`, `.venv/`, the PoC scripts (`demo_*.py`, `poc_*.py`, `export_snapshot.py`), `pyproject.toml` (relocated in step 3), or any `__pycache__`.

- [ ] **Step 2: Create the package marker**

```bash
# codee/__init__.py — empty file (makes `import codee.*` resolvable)
echo "" > codee/__init__.py
```

- [ ] **Step 3: Relocate pytest config into the package**

Create `F:\codefee\Volume_tracker\codee\conftest.py` is already present (it came with tests/ as `tests/conftest.py`). Add a `codee/pytest.ini` so pytest discovers async mode when run from VT root:

```ini
# codee/pytest.ini
[pytest]
asyncio_mode = auto
testpaths = tests
addopts = -v --tb=short
```
Do NOT carry over AAVE_STRAT's root `pyproject.toml` (it would register a pip dist named `codee` and set repo-wide pytest config that could clash with VT). The `pytest.ini` inside `codee/` scopes config to the package.

- [ ] **Step 4: Verify the file tree**

```bash
ls codee/                  # config db sources services scripts tests __init__.py .env.example pytest.ini conftest.py?
ls codee/services/         # api pools rewards routes __init__.py
```
Expected: all subpackages present.

- [ ] **Step 5: Commit (imports still broken — that's expected, fixed next task)**

```bash
git add codee/
git commit -m "Task 2: move Codee source into codee/ package (imports not yet rewritten)"
```

---

## Task 3: Rewrite imports to the codee. prefix

**Files:**
- Modify: every `.py` under `codee/` that imports `config.`, `db.`, `services.`, `sources.`
- Create: `codee/tests/test_namespace_smoke.py`

- [ ] **Step 1: Find every bare internal import**

```bash
cd /f/codefee/Volume_tracker
grep -rn -E "^(from|import) (config|db|services|sources)(\.|\s|import)" codee/ --include=*.py
```
Expected: a list of imports across ~25 files (e.g. `from config.config import settings`, `from services.rewards.lav import ...`, `from db.sqlite_client import ...`, `from sources.defillama.client import ...`). Note them all.

- [ ] **Step 2: Rewrite each to the codee. prefix**

For every match, prefix with `codee.`:
```
from config.config import settings        →  from codee.config.config import settings
from db.sqlite_client import ...          →  from codee.db.sqlite_client import ...
from services.X import ...                →  from codee.services.X import ...
from sources.X import ...                 →  from codee.sources.X import ...
import config.config                      →  import codee.config.config
```
Apply across ALL files under `codee/` (production AND tests). Use editor find-replace per-file or `sed`, but VERIFY each change (don't blind-replace — a string literal or comment containing "services." must not be rewritten; only actual import statements). Edit the import lines only.

- [ ] **Step 3: Confirm no residual bare imports remain**

```bash
grep -rn -E "^(from|import) (config|db|services|sources)(\.|\s|import)" codee/ --include=*.py
```
Expected: ZERO matches. Any remaining match would silently bind to VT's homonymous package at runtime.

- [ ] **Step 4: Write the namespace smoke test**

```python
# codee/tests/test_namespace_smoke.py
"""Guards the integration: every codee submodule must resolve to a file UNDER codee/,
never to VT's homonymous config/db/services packages."""
import importlib
import pathlib
import pytest

CODEE_ROOT = pathlib.Path(__file__).resolve().parent.parent  # .../codee

MODULES = [
    "codee.config.config",
    "codee.db.sqlite_client",
    "codee.db.models",
    "codee.sources.defillama.client",
    "codee.sources.merkl.client",
    "codee.services.rewards.lav",
    "codee.services.rewards.merkl_match",
    "codee.services.pools.validators",
    "codee.services.pools.snapshot",
    "codee.services.pools.aggregator",
    "codee.services.pools.ingestor",
    "codee.services.routes.analyzer",
    "codee.services.api.router",
    "codee.services.api.models",
]

@pytest.mark.parametrize("modname", MODULES)
def test_module_resolves_under_codee(modname):
    mod = importlib.import_module(modname)
    resolved = pathlib.Path(mod.__file__).resolve()
    assert CODEE_ROOT in resolved.parents, (
        f"{modname} resolved to {resolved}, NOT under {CODEE_ROOT} — "
        f"likely bound to VT's homonymous package"
    )
```

- [ ] **Step 5: Run the smoke test from VT root**

```bash
cd /f/codefee/Volume_tracker
.venv/Scripts/python -m pytest codee/tests/test_namespace_smoke.py -v
```
Expected: 14 passed. Critical: run from VT root so VT's `config/`/`db/`/`services/` are also on the path — this is the real collision scenario. If any test fails, an import wasn't rewritten.

- [ ] **Step 6: Commit**

```bash
git add codee/
git commit -m "Task 3: rewrite Codee imports to codee. prefix + namespace smoke test"
```

---

## Task 4: Run the full Codee test suite under the new namespace

**Files:**
- Verify only (no new files)

- [ ] **Step 1: Run all Codee tests from VT root**

```bash
cd /f/codefee/Volume_tracker
.venv/Scripts/python -m pytest codee/tests/ -p no:cacheprovider
```
Expected: 75 passed + 1 skipped + 14 (namespace) = the original 75 plus the new namespace tests, all green. If imports in test files weren't rewritten, they fail here — go back and fix.

- [ ] **Step 2: If any test fails on a bare import, fix and re-run**

Re-apply Task 3 step 2 to the offending test file, then re-run step 1 until green.

- [ ] **Step 3: Commit (only if test files needed fixes)**

```bash
git add codee/tests/
git commit -m "Task 4: Codee test suite green under codee. namespace"
```

---

## Task 5: Config hardening

**Files:**
- Modify: `codee/config/config.py`
- Modify: `codee/.env.example`
- Test: `codee/tests/test_config.py` (extend)

- [ ] **Step 1: Write the failing test for absolute DB path + env prefix**

Add to `codee/tests/test_config.py`:
```python
def test_db_path_is_absolute_and_under_codee():
    from codee.config.config import settings
    import pathlib
    p = pathlib.Path(settings.CODEE_DB_PATH)
    assert p.is_absolute(), f"DB path must be absolute, got {settings.CODEE_DB_PATH}"
    assert "codee" in p.parts, "DB must live under the codee package dir"
    assert p.name == "codee.db"


def test_settings_use_codee_env_prefix():
    from codee.config.config import Settings
    assert Settings.model_config.get("env_prefix") == "CODEE_"


def test_no_dead_api_host_port():
    from codee.config.config import Settings
    fields = Settings.model_fields
    assert "API_HOST" not in fields and "API_PORT" not in fields, \
        "Codee no longer runs its own uvicorn — these are dead"
```

- [ ] **Step 2: Run to confirm failure**

```bash
.venv/Scripts/python -m pytest codee/tests/test_config.py -v
```
Expected: the 3 new tests FAIL (db path is CWD-relative, no env_prefix, API_HOST/PORT still present).

- [ ] **Step 3: Edit `codee/config/config.py`**

```python
"""Codee runtime config loader.

Loads .env via pydantic-settings, JSON config files via plain json.
Single source of truth — never read env vars or config files directly elsewhere.
"""
import json
from pathlib import Path
from pydantic_settings import BaseSettings, SettingsConfigDict


CONFIG_DIR = Path(__file__).resolve().parent
_ENV_FILE = str(CONFIG_DIR.parent / ".env")                       # codee/.env
_DEFAULT_DB = str(CONFIG_DIR.parent / "data" / "codee.db")        # codee/data/codee.db (absolute)


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=_ENV_FILE, env_prefix="CODEE_", extra="ignore")

    CODEE_DB_PATH: str = _DEFAULT_DB
    CODEE_LOG_LEVEL: str = "INFO"
    SNAPSHOT_INTERVAL_MIN: int = 60
    MIN_TVL_USD: float = 1_000_000
    PRINCIPAL_DEFAULT: float = 250_000
    HOLD_HOURS_DEFAULT: int = 168
    STALENESS_BANNER_HOURS: int = 3
    # NOTE: API_HOST / API_PORT removed — Codee no longer runs its own uvicorn;
    # it plugs its router into VT's shared bo_app.


def _load_json(name: str):
    path = CONFIG_DIR / name
    with path.open(encoding="utf-8") as f:
        return json.load(f)


def load_stable_symbols() -> set[str]:
    return {s.upper() for s in _load_json("stable_symbols.json")}


def load_lav_buckets() -> dict:
    return _load_json("lav_buckets.json")


def load_chains() -> dict:
    return _load_json("chains.json")


def load_projects() -> dict:
    return _load_json("projects.json")


settings = Settings()
```

Note: with `env_prefix="CODEE_"`, the env var for `CODEE_DB_PATH` becomes `CODEE_CODEE_DB_PATH`. To avoid the double prefix, rename the fields to drop the redundant `CODEE_` and let the prefix supply it:
- `CODEE_DB_PATH` field → keep as-is ONLY if you also keep env name `CODEE_DB_PATH`; with prefix `CODEE_` the field should be `DB_PATH` so the env var is `CODEE_DB_PATH`. Rename fields accordingly: `DB_PATH`, `LOG_LEVEL`, `SNAPSHOT_INTERVAL_MIN`, etc., and update the ONE consumer (`db/sqlite_client.py` reads `settings.CODEE_DB_PATH`). Update that read to `settings.DB_PATH`.

Final field set (prefix `CODEE_` applied by pydantic-settings):
```python
    DB_PATH: str = _DEFAULT_DB              # env: CODEE_DB_PATH
    LOG_LEVEL: str = "INFO"                 # env: CODEE_LOG_LEVEL
    SNAPSHOT_INTERVAL_MIN: int = 60         # env: CODEE_SNAPSHOT_INTERVAL_MIN
    MIN_TVL_USD: float = 1_000_000          # env: CODEE_MIN_TVL_USD
    PRINCIPAL_DEFAULT: float = 250_000      # env: CODEE_PRINCIPAL_DEFAULT
    HOLD_HOURS_DEFAULT: int = 168           # env: CODEE_HOLD_HOURS_DEFAULT
    STALENESS_BANNER_HOURS: int = 3         # env: CODEE_STALENESS_BANNER_HOURS
```
And update the test from step 1 to read `settings.DB_PATH` (not `CODEE_DB_PATH`). Update `db/sqlite_client.py` `self.db_path = db_path or settings.DB_PATH`.

- [ ] **Step 4: Update `codee/.env.example`**

```
# All Codee env vars are prefixed CODEE_ to avoid colliding with Volume_tracker's env.
# DB_PATH defaults to codee/data/codee.db (absolute) — leave unset unless overriding.
# CODEE_DB_PATH=/abs/path/to/codee.db
CODEE_LOG_LEVEL=INFO
CODEE_SNAPSHOT_INTERVAL_MIN=60
CODEE_MIN_TVL_USD=1000000
CODEE_PRINCIPAL_DEFAULT=250000
CODEE_HOLD_HOURS_DEFAULT=168
CODEE_STALENESS_BANNER_HOURS=3
```

- [ ] **Step 5: Run tests (config + db + full suite)**

```bash
.venv/Scripts/python -m pytest codee/tests/test_config.py codee/tests/test_db.py -v
```
Expected: all pass, including the 3 new ones. Then run full suite `pytest codee/tests/` — still green (the `settings.DB_PATH` rename must not break anything).

- [ ] **Step 6: Commit**

```bash
git add codee/config/config.py codee/.env.example codee/db/sqlite_client.py codee/tests/test_config.py
git commit -m "Task 5: config hardening (absolute DB path, CODEE_ env prefix, drop dead API_HOST/PORT)"
```

---

## Task 6: gitignore for Codee runtime artifacts

**Files:**
- Modify: `F:\codefee\Volume_tracker\.gitignore`

- [ ] **Step 1: Append Codee ignores**

Add to `F:\codefee\Volume_tracker\.gitignore`:
```
# Codee runtime (local-only)
codee/.env
codee/data/
codee/**/__pycache__/
*.db-wal
*.db-shm
```

- [ ] **Step 2: Verify WAL/SHM and data dir are ignored**

```bash
cd /f/codefee/Volume_tracker
git check-ignore -v codee/data/codee.db-wal codee/data/codee.db codee/.env
```
Expected: all three report a matching ignore rule.

- [ ] **Step 3: Commit**

```bash
git add .gitignore
git commit -m "Task 6: gitignore Codee runtime (.env, data/, WAL/SHM)"
```

---

## Task 7: Merge dependencies into VT's requirements

**Files:**
- Modify: `F:\codefee\Volume_tracker\requirements.txt`

- [ ] **Step 1: Check what VT already pins vs what Codee needs**

```bash
grep -iE "pydantic|fastapi|aiohttp|sqlalchemy|aiosqlite|uvicorn|pydantic-settings" F:/codefee/Volume_tracker/requirements.txt
```
Server venv already has: pydantic 2.12.5, fastapi, aiohttp, sqlalchemy, aiosqlite, uvicorn. The only missing one is `pydantic-settings`.

- [ ] **Step 2: Append the single missing dep**

Add to `F:\codefee\Volume_tracker\requirements.txt` (only if not already present):
```
pydantic-settings>=2.4
```
Do NOT add apscheduler (Codee declares but never uses it — the ingestor uses asyncio.sleep) or requests (only used by PoC scripts not moved). Do NOT add a second uvicorn/fastapi pin if VT already has them.

- [ ] **Step 3: Verify the local venv can import everything Codee needs**

```bash
cd /f/codefee/Volume_tracker
.venv/Scripts/python -c "import codee.services.api.router, codee.services.pools.ingestor; print('codee imports OK under VT root')"
```
Expected: `codee imports OK under VT root`.

- [ ] **Step 4: Commit**

```bash
git add requirements.txt
git commit -m "Task 7: add pydantic-settings to requirements (only missing server dep)"
```

---

## Task 8: Event-loop performance hardening

**Files:**
- Modify: `codee/services/pools/ingestor.py`
- Modify: `codee/services/pools/snapshot.py`
- Test: `codee/tests/test_pools_ingestor.py` (must still pass)

- [ ] **Step 1: Move the sync transform off the event loop**

In `codee/services/pools/ingestor.py`, the `run_once` method does synchronous CPU work (join_supply_borrow + build_rebate_lookup + overlay_rebates + _filter + _validate) over ~20k pools. Wrap that block so it runs in a thread, freeing VT's shared event loop:

```python
import asyncio
# ... inside run_once, after the awaited fetches return supply, borrow, merkl_opps:

def _transform():
    joined = join_supply_borrow(supply, borrow)
    rebates = build_rebate_lookup(merkl_opps)
    overlaid = overlay_rebates(joined, rebates)
    filtered = self._filter(overlaid)
    validated = self._validate(filtered)
    return validated, len(joined), len(rebates)

validated, n_joined, n_rebates = await asyncio.to_thread(_transform)
```
Keep the DB writes (`apply_snapshot`, `compute_aggregates`) as awaited calls after the thread returns.

- [ ] **Step 2: Batch the snapshot writes**

In `codee/services/pools/snapshot.py::apply_snapshot`, replace the per-row loop (one `execute`+commit per UPSERT and per history INSERT) with `executemany`:
```python
# instead of: for p in params: await db.execute(_SNAPSHOT_UPSERT, p); await db.execute(_HISTORY_INSERT, p)
await db.executemany(_SNAPSHOT_UPSERT, params)
await db.executemany(_HISTORY_INSERT, params)
# then the single inactive-marking UPDATE as before
```
`SqliteClient.executemany` already exists and commits once. This drops ~2N commits to ~3.

- [ ] **Step 3: Run the ingestor + snapshot tests**

```bash
.venv/Scripts/python -m pytest codee/tests/test_pools_ingestor.py codee/tests/test_pools_snapshot.py -v
```
Expected: all pass unchanged (behavior identical, just threaded + batched).

- [ ] **Step 4: Commit**

```bash
git add codee/services/pools/ingestor.py codee/services/pools/snapshot.py
git commit -m "Task 8: run ingest transform via asyncio.to_thread + batch snapshot writes"
```

---

## Task 9: Backend wiring — three fail-open guards + router plumbing

**Files:**
- Modify: `F:\codefee\Volume_tracker\main.py`
- Modify: `F:\codefee\Volume_tracker\services\big_orders\service.py`
- Test: `codee/tests/test_failopen_guard.py` (new — unit-tests the guard pattern)

- [ ] **Step 1: Write a unit test for the supervisor guard pattern**

```python
# codee/tests/test_failopen_guard.py
"""The Codee ingestor is wrapped in a never-raises supervisor so a crash can't
propagate into VT's asyncio.gather (which uses return_exceptions=False)."""
import asyncio
import logging
import pytest


async def _make_guarded(ingestor):
    """Mirror of the supervisor defined in VT main.py."""
    async def _codee_guarded():
        if ingestor is None:
            return
        try:
            await ingestor.run()
        except Exception:
            logging.getLogger("codee").exception("ingestor crashed — VT unaffected")
    return _codee_guarded


class _BoomIngestor:
    async def run(self):
        raise RuntimeError("simulated ingestor crash")


class _NoneSafe:
    pass


async def test_supervisor_swallows_ingestor_crash():
    guarded = await _make_guarded(_BoomIngestor())
    # gather with return_exceptions=False — like VT. If the guard leaks, this raises.
    await asyncio.gather(guarded())   # must NOT raise


async def test_supervisor_noop_when_ingestor_none():
    guarded = await _make_guarded(None)
    await asyncio.gather(guarded())   # must NOT raise
```

- [ ] **Step 2: Run to confirm the pattern is sound**

```bash
.venv/Scripts/python -m pytest codee/tests/test_failopen_guard.py -v
```
Expected: 2 passed. (This validates the guard logic the wiring will use.)

- [ ] **Step 3: Guard the imports at the top of VT's `main.py`**

In `F:\codefee\Volume_tracker\main.py`, after the existing imports (near line 45), add:
```python
# ── Codee (DeFi yield) — optional add-on; must NEVER crash VT ──────────────
try:
    from codee.db.sqlite_client import SqliteClient as CodeeDB
    from codee.services.pools.ingestor import PoolsIngestor as CodeeIngestor
    from codee.services.api.router import router as codee_router, set_db as codee_set_db
except Exception:
    CodeeDB = CodeeIngestor = codee_router = codee_set_db = None
    logging.getLogger("codee").exception("[Codee] import failed — VT continues without Codee")
```
(Confirm `import logging` is already present in main.py; VT uses logging — it is.)

- [ ] **Step 4: Guard Codee init inside `main()` and add the supervised task**

In `main()`, before the `_tasks = [...]` list (around line 332), add:
```python
    # Codee init — guarded so a failure leaves VT fully operational
    codee_db = None
    codee_ingestor = None
    if CodeeDB is not None:
        try:
            codee_db = CodeeDB()
            await codee_db.connect()
            await codee_db.apply_migrations()
            codee_ingestor = CodeeIngestor(codee_db)
            print("[Codee] initialized")
        except Exception:
            codee_db = None
            codee_ingestor = None
            logging.getLogger("codee").exception("[Codee] init failed — VT continues without Codee")

    async def _codee_guarded():
        if codee_ingestor is None:
            return
        try:
            await codee_ingestor.run()
        except Exception:
            logging.getLogger("codee").exception("[Codee] ingestor crashed — VT unaffected")
```
Then add the supervised task to the `_tasks` list (the list defined at line 332):
```python
    _tasks = [
        # ... existing VT tasks ...
        _codee_guarded(),     # never raises; no-op if Codee failed to init
    ]
```

- [ ] **Step 5: Add the `codee_db` param to `run_big_orders_server` and register the router**

In `F:\codefee\Volume_tracker\services\big_orders\service.py`, add `codee_db=None` to the signature (line 21 area, alongside the other kwargs), and register the router (following the existing `include_router` pattern, e.g. after the margin router around line 159):
```python
    # Codee router — only mount when the DB initialized, else /api/codee/* would all 503
    if codee_db is not None:
        try:
            from codee.services.api.router import set_db as codee_set_db
            codee_set_db(codee_db)
            from codee.services.api.router import router as codee_router
            bo_app.include_router(codee_router)
            logger.info("API router (codee) registrado")
        except Exception:
            logger.exception("[Codee] router registration failed — VT API unaffected")
```

- [ ] **Step 6: Pass `codee_db` at the call site in `main.py`**

In `main.py`, the `run_big_orders_server(...)` call (line 368-391) — add the kwarg:
```python
            run_big_orders_server(
                Config.BO_SERVER_HOST, Config.BO_SERVER_PORT,
                aggregator=aggregator,
                # ... all existing kwargs ...
                margin_aggregator=margin_aggregator,
                codee_db=codee_db,            # ← Codee router plumbing (was the 503 bug)
            ),
```

- [ ] **Step 7: Syntax-check both modified VT files**

```bash
cd /f/codefee/Volume_tracker
.venv/Scripts/python -m py_compile main.py services/big_orders/service.py
echo "exit: $?"
```
Expected: exit 0 (compiles). Note: this only checks syntax — full VT boot needs the QuestDB environment (server). The fail-open guard logic itself is covered by Task 9 step 1-2.

- [ ] **Step 8: Commit**

```bash
git add main.py services/big_orders/service.py codee/tests/test_failopen_guard.py
git commit -m "Task 9: wire Codee into VT with 3 fail-open guards + router plumbing"
```

---

## Task 10: Router isolated integration test

**Files:**
- Test: `codee/tests/test_router_isolated_mount.py` (new)

- [ ] **Step 1: Write a test that mounts the Codee router on a fresh app (proves no 503 when db is set)**

```python
# codee/tests/test_router_isolated_mount.py
"""Proves the router works when codee_db IS plumbed in (the bug Task 9 step 6 fixes):
mount codee_router on a bare FastAPI app exactly as run_big_orders_server does."""
import time
import pytest
from fastapi import FastAPI
from httpx import AsyncClient, ASGITransport

from codee.db.sqlite_client import SqliteClient
from codee.services.api.router import router as codee_router, set_db


@pytest.fixture
async def app(tmp_path):
    db = SqliteClient(db_path=str(tmp_path / "iso.db"))
    await db.connect()
    await db.apply_migrations()
    set_db(db)                       # the plumbing step
    a = FastAPI()
    a.include_router(codee_router)   # mirrors bo_app.include_router(codee_router)
    yield a, db
    await db.close()


async def test_health_not_503_when_db_plumbed(app):
    a, _ = app
    transport = ASGITransport(app=a)
    async with AsyncClient(transport=transport, base_url="http://t") as ac:
        r = await ac.get("/api/codee/health")
    assert r.status_code == 200          # NOT 503 — db is wired
    assert r.json()["status"] == "warming_up"   # empty db, but responding


async def test_passive_route_serves_after_insert(app):
    a, db = app
    now = int(time.time())
    await db.execute(
        "INSERT INTO pools_snapshot (pool_id, chain, project, symbol, tvl_usd, supply_apy_base, supply_apy_reward, updated_at) "
        "VALUES (?, 'BSC', 'aave-v3', 'USDC', 1e7, 5.0, 0.0, ?)", ("u1", now))
    transport = ASGITransport(app=a)
    async with AsyncClient(transport=transport, base_url="http://t") as ac:
        r = await ac.get("/api/codee/routes/passive")
    assert r.status_code == 200
    assert r.json()[0]["symbol"] == "USDC"
```

- [ ] **Step 2: Run it**

```bash
.venv/Scripts/python -m pytest codee/tests/test_router_isolated_mount.py -v
```
Expected: 2 passed. This proves the exact mount path used in `run_big_orders_server` returns data (not 503) when `codee_db` is plumbed — the regression the review caught.

- [ ] **Step 3: Commit**

```bash
git add codee/tests/test_router_isolated_mount.py
git commit -m "Task 10: isolated router-mount test (proves no 503 when codee_db plumbed)"
```

---

## Task 11: Frontend — sidebar tab + sectionCodee page + IIFE JS

**Files:**
- Modify: `F:\codefee\Volume_tracker\web\index.html`

- [ ] **Step 1: Add the sidebar button (between Margins and the bottom-pinned Config)**

In `web/index.html`, after the Margins `.sidebar-item` (around line 1649) and before the disabled Config item (line ~1650 with `margin-top:auto`):
```html
      <button class="sidebar-item" data-section="sectionCodee">
        <svg viewBox="0 0 24 24"><path d="M3 3v18h18"/><rect x="7" y="10" width="3" height="7"/><rect x="12" y="6" width="3" height="11"/><rect x="17" y="13" width="3" height="4"/></svg>
        <span>Codee</span>
      </button>
```

- [ ] **Step 2: Add the page section (alongside the other `.page` divs, e.g. after sectionMargins ~line 2527+)**

```html
      <div id="sectionCodee" class="page">
        <div class="spread-table-header" style="display:flex;justify-content:space-between;align-items:center;">
          <span>CODEE — DEFI YIELD RADAR</span>
          <span id="codeeRegime" style="color:var(--text-3)">—</span>
        </div>
        <div class="mm-routes-tabs" style="padding:8px 24px;">
          <div class="mm-routes-tab-pair">
            <button class="mm-routes-tab active" data-codeetab="passive">Passive</button>
            <button class="mm-routes-tab" data-codeetab="loops">Loops</button>
            <button class="mm-routes-tab" data-codeetab="crosschain">Cross-Chain</button>
            <button class="mm-routes-tab" data-codeetab="rewards">Rewards</button>
          </div>
        </div>
        <div class="spread-table-wrap">
          <div id="codeeCaveat" style="display:none;font-size:10px;color:var(--text-3);padding:4px 0;"></div>
          <table class="spread-table"><thead id="codeeThead"></thead><tbody id="codeeTbody"></tbody></table>
        </div>
      </div>
```

- [ ] **Step 3: Verify VT's nav handler and find the insertion point**

```bash
sed -n '5365,5460p' F:/codefee/Volume_tracker/web/index.html
```
Identify: the generic page-swap (it toggles `.page.active` by `data-section`), and the lazy-init/refresh if-ladder. Note the exact line after the if-ladder to add the Codee branch.

- [ ] **Step 4: Add the Codee nav branch + gated timer + IIFE JS block**

In the inline `<script>`, add the Codee branch in the nav click handler (after the existing if-ladder identified in step 3):
```javascript
        if (btn.dataset.section === 'sectionCodee') {
          if (!window.__codeeInit) { window.__codeeInit = true; codeeInit(); }
          else codeeRefresh();
        }
```
Then add this self-contained IIFE near the end of the script (all globals namespaced `codee*` — NEVER bare `fmt`/`pct`/`data`/`render*`, which already exist in VT):
```javascript
// ===================== CODEE (DeFi yield radar) =====================
(function () {
  const API = '/api/codee';
  let activeTab = 'passive';

  const codeeFetch = async (path) => {
    const r = await fetch(API + path);
    if (!r.ok) throw new Error(path + ' -> ' + r.status);
    return r.json();
  };
  const codeeFmtApy = (v) => (v == null ? '—' : Number(v).toFixed(2) + '%');
  const codeeFmtTvl = (v) => {
    if (v == null) return '—';
    if (v >= 1e9) return '$' + (v / 1e9).toFixed(2) + 'B';
    if (v >= 1e6) return '$' + (v / 1e6).toFixed(1) + 'M';
    if (v >= 1e3) return '$' + (v / 1e3).toFixed(0) + 'K';
    return '$' + v.toFixed(0);
  };
  const codeeSpreadClass = (v) => (v > 0.1 ? 'pos' : v < -0.1 ? 'neg' : '');

  const VIEWS = {
    passive: {
      cols: ['Chain', 'Project', 'Symbol', 'Eff APY', 'TVL', 'Flag'],
      path: '/routes/passive?limit=50',
      caveat: '',
      row: (d) => `<td>${d.chain}</td><td>${d.project}</td><td>${d.symbol}</td>
        <td class="r">${codeeFmtApy(d.effective_apy)}</td><td class="r">${codeeFmtTvl(d.tvl_usd)}</td>
        <td>${d.quality_flag === 'ok' ? '' : d.quality_flag}</td>`,
    },
    loops: {
      cols: ['Chain', 'A→B', 'X/Y', 'Spread', 'Lev', 'Gross APY'],
      path: '/routes/loops?limit=50',
      caveat: '',
      row: (d) => `<td>${d.chain}</td><td>${d.plat_a}→${d.plat_b}</td><td>${d.asset_x}/${d.asset_y}</td>
        <td class="r ${codeeSpreadClass(d.spread)}">${codeeFmtApy(d.spread)}</td>
        <td class="r">${Number(d.leverage).toFixed(2)}x</td><td class="r">${codeeFmtApy(d.gross_apy)}</td>`,
      empty: 'No positive-spread same-chain loops right now. Check Cross-Chain.',
    },
    crosschain: {
      cols: ['Symbol', 'Supply (chain/proj)', 'Sup APY', 'Borrow (chain/proj)', 'Bor APR', 'Spread'],
      path: '/routes/crosschain?limit=50',
      caveat: 'Pre-bridge ceiling — spreads ignore bridge cost/slippage. Theoretical upper bounds.',
      row: (d) => `<td>${d.symbol}</td><td>${d.supply_chain}/${d.supply_project}</td>
        <td class="r">${codeeFmtApy(d.supply_apy)}</td><td>${d.borrow_chain}/${d.borrow_project}</td>
        <td class="r">${codeeFmtApy(d.borrow_apr)}</td>
        <td class="r ${codeeSpreadClass(d.spread)}">${codeeFmtApy(d.spread)}</td>`,
    },
    rewards: {
      cols: ['Metric', 'Value'],
      path: '/rewards/coverage',
      caveat: '',
      render: (d) => [
        ['Pools in scope', d.pools_in_scope],
        ['Classified reward (LAV known)', d.pools_with_classified_reward],
        ['LAV coverage', codeeFmtApy((d.lav_coverage_pct || 0) * 100)],
        ['Merkl borrow-rebate pools', d.pools_with_merkl_borrow_rebate],
        ['Reward-active pools', d.reward_active_pools],
      ].map(([k, v]) => `<tr><td>${k}</td><td class="r">${v}</td></tr>`).join(''),
    },
  };

  function renderCodeeTable(view, data) {
    const v = VIEWS[view];
    document.getElementById('codeeThead').innerHTML =
      '<tr>' + v.cols.map((c, i) => `<th class="${i >= (view==='rewards'?1:3) ? 'r' : ''}">${c}</th>`).join('') + '</tr>';
    const cv = document.getElementById('codeeCaveat');
    cv.style.display = v.caveat ? 'block' : 'none';
    cv.textContent = v.caveat;
    const tb = document.getElementById('codeeTbody');
    if (v.render) { tb.innerHTML = v.render(data); return; }
    if (!data || !data.length) {
      tb.innerHTML = `<tr><td colspan="${v.cols.length}" style="text-align:center;color:var(--text-3);padding:18px;">${v.empty || 'No data.'}</td></tr>`;
      return;
    }
    tb.innerHTML = data.map((d) => '<tr>' + v.row(d) + '</tr>').join('');
  }

  async function loadCodeeView(view) {
    try {
      const data = await codeeFetch(VIEWS[view].path);
      renderCodeeTable(view, data);
    } catch (e) {
      document.getElementById('codeeTbody').innerHTML =
        `<tr><td colspan="6" style="color:var(--red);padding:12px;">Codee API error: ${e.message}</td></tr>`;
    }
  }

  async function loadRegime() {
    try {
      const h = await codeeFetch('/health');
      document.getElementById('codeeRegime').textContent =
        `reward-active ${h.reward_active_pools} · in-scope ${h.pool_count_in_scope} · ${h.status}`;
    } catch (e) { /* leave dash */ }
  }

  window.codeeInit = function () {
    document.querySelectorAll('#sectionCodee .mm-routes-tab').forEach((btn) => {
      btn.addEventListener('click', () => {
        document.querySelectorAll('#sectionCodee .mm-routes-tab').forEach((b) => b.classList.remove('active'));
        btn.classList.add('active');
        activeTab = btn.dataset.codeetab;
        loadCodeeView(activeTab);
      });
    });
    loadRegime();
    loadCodeeView(activeTab);
  };
  window.codeeRefresh = function () { loadRegime(); loadCodeeView(activeTab); };

  // gated 60s refresh — only ticks after the tab has been opened
  setInterval(() => { if (window.__codeeInit) window.codeeRefresh(); }, 60000);
})();
```

- [ ] **Step 5: Manual smoke (requires a running backend exposing /api/codee/*)**

Since full VT won't boot locally (no QuestDB), validate the frontend against a minimal harness: temporarily run a tiny FastAPI app that mounts ONLY `codee_router` (reuse Task 10's pattern) on port 8000, plus serve `web/index.html`. Open it, click the Codee tab, confirm: regime line populates, sub-tabs switch, tables render, cross-chain shows the caveat, no JS console errors, and the OTHER tabs' globals (`fmt`, `pct`) are untouched (open another tab, confirm it still works). If a full local harness is impractical, defer this visual check to the server deploy and rely on Task 10 for API correctness.

- [ ] **Step 6: Commit**

```bash
git add web/index.html
git commit -m "Task 11: Codee sidebar tab + sectionCodee page + IIFE JS (VT-native styling)"
```

---

## Task 12: Final local validation + deploy documentation

**Files:**
- Create: `codee/DEPLOY.md` (server deploy runbook)

- [ ] **Step 1: Full Codee suite one more time from VT root**

```bash
cd /f/codefee/Volume_tracker
.venv/Scripts/python -m pytest codee/tests/ -p no:cacheprovider
```
Expected: all green (75 original + namespace + config + failopen + router-mount tests).

- [ ] **Step 2: Confirm VT's two modified files still compile and the call site has codee_db**

```bash
.venv/Scripts/python -m py_compile main.py services/big_orders/service.py && echo "compile OK"
grep -n "codee_db=codee_db" main.py
grep -n "codee_db=None" services/big_orders/service.py
```
Expected: compile OK; both greps return a line (proves the plumbing the review caught is in place).

- [ ] **Step 3: Write the deploy runbook**

```markdown
# codee/DEPLOY.md — Server deploy runbook (199.247.3.163, /opt/bigdeposits)

PRE-REQ: rotate the root password exposed in chat + VT CLAUDE.md; prefer SSH keys.

1. Local: from Volume_tracker, create a bundle of the codee-integration branch:
   git bundle create /tmp/codee.bundle <last-server-commit>..codee-integration
2. Upload bundle + the gitignored codee/.env (NOT in the bundle):
   scp /tmp/codee.bundle root@199.247.3.163:/tmp/
   scp codee/.env root@199.247.3.163:/opt/bigdeposits/codee/.env   # after pull creates codee/
3. Server: apply the bundle on a branch, install the one new dep BEFORE restart:
   cd /opt/bigdeposits && git pull /tmp/codee.bundle codee-integration
   /opt/bigdeposits/venv/bin/pip install pydantic-settings>=2.4
4. Restart and verify:
   systemctl restart bigdeposits
   systemctl status bigdeposits          # active (running)
   curl -s localhost:<BO_PORT>/api/codee/health   # JSON, not 503/404
   # open dashboard, click Codee tab, confirm existing tabs still work
5. Rollback if anything breaks:
   git checkout <previous-commit> && systemctl restart bigdeposits
```

- [ ] **Step 4: Commit**

```bash
git add codee/DEPLOY.md
git commit -m "Task 12: final local validation + server deploy runbook"
```

- [ ] **Step 5: Report integration branch ready**

The `codee-integration` branch in `F:\codefee\Volume_tracker` is ready for: (a) user review of the diff, (b) merge to `main` after review, (c) server deploy per `codee/DEPLOY.md` when the user approves. Do NOT deploy or merge without explicit user go-ahead.

---

## Self-Review

**1. Spec coverage** — every §5 fix maps to a task:
- §5.1 package/imports → Task 2 (package + __init__), Task 3 (AST rewrite + smoke test), Task 4 (suite green)
- §5.2 config/paths → Task 5 (absolute DB path, env_prefix, drop dead settings)
- §5.3 gitignore → Task 6
- §5.4 dependencies → Task 7 (pydantic-settings only; drop apscheduler/requests)
- §5.5 three fail-open guards → Task 9 (steps 3-4 + guard unit test step 1-2)
- §5.6 router plumbing → Task 9 (steps 5-6) + Task 10 (isolated mount proves no 503)
- §5.7 event-loop perf → Task 8 (asyncio.to_thread + executemany)
- §5.8 frontend native JS → Task 11
- §5.9 git isolation → Task 1 (branch off, no stash, leave user's changes)
- §6 testing → Tasks 4, 10, 11 step 5, 12
- §7 deploy → Task 12 step 3 (runbook, not executed)

**2. Placeholder scan** — no TBD/TODO/"appropriate"; the one honest limitation (full VT can't boot locally) is stated explicitly with the isolated-validation alternative, not hidden.

**3. Type consistency** — `codee_db`, `codee_router`, `codee_set_db`, `CodeeDB`, `CodeeIngestor`, `_codee_guarded`, `set_db`, `settings.DB_PATH` used consistently across Tasks 5/9/10. The `settings.CODEE_DB_PATH`→`settings.DB_PATH` rename in Task 5 is propagated to its one consumer (db/sqlite_client.py) in the same task.

**Known limitation flagged:** local validation cannot boot full VT (QuestDB absent). Tasks 9 step 7 (py_compile) + Task 10 (isolated router) + Task 9 step 1-2 (guard unit) cover what's locally provable; end-to-end VT-boot fail-open proof happens at deploy. This is called out in the header and Task 11 step 5.

---

## Plan complete

Saved to `docs/superpowers/plans/2026-05-29-codee-vt-integration.md`. Two execution options:

**1. Subagent-Driven (recommended)** — fresh subagent per task, two-stage review between tasks.

**2. Inline Execution** — execute in this session with checkpoints.

Which approach?
