# Codee Multi-Hop Cross-Chain Carry Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Find and rank multi-hop cross-chain carry chains (supply → borrow → Binance-bridge → supply…, up to 4 hops, ending on a supply), with supply yields enriched by two incentive aggregators (Merkl LEND + ACI Merit).

**Architecture:** Phase 0 adds the incentive aggregators (extend the existing Merkl client with `action=LEND`; new ACI Merit client) overlaid onto `apyReward` at ingest — enriching ALL views. Phase 1 extends the Binance source with the deposit map. Phase 2 adds the pure pathfinding (`enumerate_multihop_paths`, beam search, leveraged-carry metric) to the analyzer. Phase 3-4 add the API endpoint + the Multi-Hop sub-tab with a client-side "Max hops" selector. No DB schema change: the conditional-incentive tag and bridge maps are JSON caches read at request time (same pattern as `binance_withdraw.json`).

**Tech Stack:** Python 3.13, FastAPI, pydantic v2, aiohttp, pytest (offline fixtures); vanilla JS in `web/index.html`.

**Where:** Backend in `F:\codefee\Volume_tracker\codee\…` (branch created at execution), mirrored to `F:\codefee\AAVE_STRAT\…` (bare imports, NO frontend). Frontend in `Volume_tracker\web\index.html` only. Test cmd (from `F:\codefee\Volume_tracker`): `PYTHONIOENCODING=utf-8 .venv\Scripts\pytest codee/tests/ -q` (UTF-8 matters — ₮ glyphs in fixtures).

**Spec:** `docs/superpowers/specs/2026-05-31-codee-multihop-design.md` (all questions resolved).

---

# PHASE 0 — incentive aggregators (Merkl LEND + ACI Merit)

### Task 1: Merkl client — fetch supply (LEND) opportunities

**Files:**
- Modify: `codee/sources/merkl/client.py`
- Test: `codee/tests/test_merkl_client.py`

- [ ] **Step 1: Write the failing test**

Look at the existing tests in `codee/tests/test_merkl_client.py` for the stub-session pattern used to test `fetch_borrow_opportunities` (it stubs `aiohttp` responses). Append a mirrored test:

```python
async def test_fetch_supply_opportunities_paginates_lend(monkeypatch):
    """fetch_supply_opportunities pulls action=LEND pages until a short page."""
    pages = {
        0: [{"id": i} for i in range(100)],   # full page -> keep going
        1: [{"id": 100}],                      # short page -> stop
    }
    captured_urls = []

    class FakeResp:
        def __init__(self, data): self._d = data
        async def __aenter__(self): return self
        async def __aexit__(self, *a): pass
        def raise_for_status(self): pass
        async def json(self): return self._d

    class FakeSession:
        def get(self, url):
            captured_urls.append(url)
            page = int(url.split("page=")[1])
            return FakeResp(pages.get(page, []))

    from codee.sources.merkl.client import MerklClient
    c = MerklClient(session=FakeSession())
    out = await c.fetch_supply_opportunities()
    assert len(out) == 101
    assert all("action=LEND" in u for u in captured_urls)
    assert "status=LIVE" in captured_urls[0] and "items=100" in captured_urls[0]
```
(If the existing borrow test uses a different fake-session idiom, mirror THAT idiom instead — the assertions stay the same.)

- [ ] **Step 2: Run it — expect FAIL** (`fetch_supply_opportunities` doesn't exist)

Run: `PYTHONIOENCODING=utf-8 .venv\Scripts\pytest codee/tests/test_merkl_client.py -v`

- [ ] **Step 3: Implement**

In `codee/sources/merkl/client.py`, add below `fetch_borrow_opportunities` (note: Merkl's supply-side action is **LEND** — `SUPPLY` returns HTTP 500):

```python
    async def fetch_supply_opportunities(self, max_pages: int = 5) -> list[dict]:
        """Paginates LIVE LEND (supply-side) opportunities. items=100 per page.
        NOTE: Merkl's supply action is 'LEND' ('SUPPLY' is invalid and 500s)."""
        assert self._session is not None
        out: list[dict] = []
        for page in range(max_pages):
            url = f"{BASE_URL}?action=LEND&status=LIVE&items=100&page={page}"
            async with self._session.get(url) as resp:
                resp.raise_for_status()
                batch = await resp.json()
            if not batch:
                break
            out.extend(batch)
            if len(batch) < 100:
                break
        return out
```

- [ ] **Step 4: Run it — expect PASS**

Run: `PYTHONIOENCODING=utf-8 .venv\Scripts\pytest codee/tests/test_merkl_client.py -v`

- [ ] **Step 5: Commit**
```bash
git add codee/sources/merkl/client.py codee/tests/test_merkl_client.py
git commit -m "T4-0A: Merkl client fetches LEND (supply) opportunities"
```

---

### Task 2: ACI Merit source — client + chain map + pure parser

**Files:**
- Create: `codee/sources/aci/__init__.py` (empty)
- Create: `codee/sources/aci/client.py`
- Create: `codee/sources/aci/parse.py`
- Create: `codee/config/aci_chains.json`
- Modify: `codee/config/config.py` (loader)
- Test: `codee/tests/test_aci_merit.py`

- [ ] **Step 1: Create the chain-slug map**

`codee/config/aci_chains.json` (ACI key slug → DefiLlama chain name):
```json
{
  "ethereum": "Ethereum",
  "celo": "Celo",
  "avalanche": "Avalanche",
  "arbitrum": "Arbitrum",
  "base": "Base",
  "optimism": "OP Mainnet",
  "polygon": "Polygon",
  "bsc": "BSC",
  "sonic": "Sonic",
  "scroll": "Scroll",
  "linea": "Linea",
  "mantle": "Mantle"
}
```

- [ ] **Step 2: Add the loader** in `codee/config/config.py` (next to the other `load_*`):
```python
def load_aci_chains() -> dict:
    return _load_json("aci_chains.json")
```

- [ ] **Step 3: Write the failing tests**

`codee/tests/test_aci_merit.py`:
```python
import pytest
from codee.sources.aci.parse import parse_merit_aprs
from codee.sources.aci.client import AciClient

CHAIN_MAP = {"celo": "Celo", "ethereum": "Ethereum"}

PAYLOAD = {"currentAPR": {"actionsAPR": {
    "celo-supply-weth": 2.08,
    "self-celo-supply-weth": 2.08,
    "celo-supply-usdt": 4.23,
    "self-celo-supply-usdt": 4.23,
    "ethereum-sgho": 3.76,                    # no '-supply-' -> not a pool supply key, ignored
    "celo-supply-multiple-borrow-usdt": None, # null -> ignored
    "fantomx-supply-usdc": 9.9,               # unknown chain slug -> ignored
}}}


def test_parse_maps_chain_asset_with_merit_and_self():
    out = parse_merit_aprs(PAYLOAD, CHAIN_MAP)
    assert out[("Celo", "WETH")] == {"merit": 2.08, "self": 2.08}
    assert out[("Celo", "USDT")] == {"merit": 4.23, "self": 4.23}


def test_parse_ignores_non_supply_unknown_and_null():
    out = parse_merit_aprs(PAYLOAD, CHAIN_MAP)
    assert all(k[0] in ("Celo", "Ethereum") for k in out)
    assert ("Ethereum", "SGHO") not in out          # sgho key has no '-supply-'
    assert not any(k[1] == "USDC" for k in out)     # unknown chain slug dropped


def test_parse_empty_payload():
    assert parse_merit_aprs({}, CHAIN_MAP) == {}


async def test_client_returns_empty_on_error_shape():
    class FakeResp:
        async def __aenter__(self): return self
        async def __aexit__(self, *a): pass
        def raise_for_status(self): pass
        async def json(self): return ["not-a-dict"]
    class FakeSession:
        def get(self, url): return FakeResp()
    c = AciClient(session=FakeSession())
    assert await c.fetch_merit_aprs() == {}
```

- [ ] **Step 4: Run — expect FAIL** (modules don't exist)

Run: `PYTHONIOENCODING=utf-8 .venv\Scripts\pytest codee/tests/test_aci_merit.py -v`

- [ ] **Step 5: Implement**

`codee/sources/aci/__init__.py`: empty file.

`codee/sources/aci/client.py`:
```python
"""ACI (Aave Chan Initiative) Merit feed — Aave's OFF-protocol supply incentives
(Merit + Self) that DefiLlama, Merkl and the on-chain RewardsController all miss.
Free public endpoint, no key. Example: Celo WETH = Merit 2.08% + Self 2.08%
(+ protocol 0.02% = the 4.22% the Aave UI shows)."""
import aiohttp

MERIT_URL = "https://apps.aavechan.com/api/merit/aprs"
DEFAULT_TIMEOUT = aiohttp.ClientTimeout(total=20)
USER_AGENT = "codee/0.1"


class AciClient:
    def __init__(self, session: aiohttp.ClientSession | None = None):
        self._session = session
        self._owns_session = session is None

    async def __aenter__(self):
        if self._session is None:
            self._session = aiohttp.ClientSession(timeout=DEFAULT_TIMEOUT, headers={"User-Agent": USER_AGENT})
        return self

    async def __aexit__(self, exc_type, exc, tb):
        if self._owns_session and self._session is not None:
            await self._session.close()
            self._session = None

    async def fetch_merit_aprs(self) -> dict:
        """Raw payload from /api/merit/aprs; {} on non-dict response."""
        assert self._session is not None, "use as async context manager"
        async with self._session.get(MERIT_URL) as resp:
            resp.raise_for_status()
            data = await resp.json()
            return data if isinstance(data, dict) else {}
```

`codee/sources/aci/parse.py`:
```python
"""Pure parsing of the ACI Merit payload. Keys look like:
  '<chain>-supply-<asset>'        -> Merit APR for supplying <asset> on <chain>
  'self-<chain>-supply-<asset>'   -> Self (zkPoH-gated) APR for the same pool
Anything else (sgho keys, borrow combos, null values, unknown chains) is ignored."""
from codee.config.config import normalize_symbol


def parse_merit_aprs(payload: dict, chain_map: dict) -> dict[tuple[str, str], dict]:
    """-> {(defillama_chain, NORMALIZED_ASSET): {'merit': apr, 'self': apr}}"""
    actions = ((payload.get("currentAPR") or {}).get("actionsAPR")) or {}
    out: dict[tuple[str, str], dict] = {}
    for key, apr in actions.items():
        if apr is None:
            continue
        is_self = key.startswith("self-")
        k = key[5:] if is_self else key
        parts = k.split("-supply-")
        if len(parts) != 2 or "-" in parts[1]:      # not a plain supply key (e.g. borrow combos)
            continue
        chain = chain_map.get(parts[0])
        if not chain:
            continue
        sym = normalize_symbol(parts[1])
        entry = out.setdefault((chain, sym), {"merit": 0.0, "self": 0.0})
        entry["self" if is_self else "merit"] = float(apr)
    return out
```

- [ ] **Step 6: Run — expect PASS**

Run: `PYTHONIOENCODING=utf-8 .venv\Scripts\pytest codee/tests/test_aci_merit.py -v`

- [ ] **Step 7: Commit**
```bash
git add codee/sources/aci codee/config/aci_chains.json codee/config/config.py codee/tests/test_aci_merit.py
git commit -m "T4-0B: ACI Merit client + pure parser (off-protocol Aave Merit/Self APRs)"
```

---

### Task 3: Supply-incentive overlay (max of the two aggregators)

**Files:**
- Create: `codee/services/rewards/supply_incentives.py`
- Test: `codee/tests/test_supply_incentives.py`

- [ ] **Step 1: Write the failing test**

`codee/tests/test_supply_incentives.py`:
```python
from codee.services.rewards.supply_incentives import overlay_supply_incentives
from codee.services.rewards.merkl_match import build_rebate_lookup


def _pool(chain, project, symbol, apy_reward=None):
    return {"chain": chain, "project": project, "symbol": symbol,
            "apyBase": 1.0, "apyReward": apy_reward, "tvlUsd": 5e6}


def _lend_opp(chain, proto, symbol, apr):
    return {"chain": {"name": chain}, "protocol": {"id": proto},
            "tokens": [{"symbol": symbol}], "action": "LEND", "apr": apr}


def test_merkl_lend_raises_apy_reward():
    pools = [_pool("MegaETH", "aave-v3", "USDM")]
    lend = build_rebate_lookup([_lend_opp("MegaETH", "aave", "USDM", 4.88)])
    out = overlay_supply_incentives(pools, lend, {})
    assert out[0]["apyReward"] == 4.88
    assert out[0]["reward_source"] == "merkl_lend"


def test_aci_merit_plus_self_raises_apy_reward_and_flags_conditional():
    pools = [_pool("Celo", "aave-v3", "WETH")]
    aci = {("Celo", "WETH"): {"merit": 2.08, "self": 2.08}}
    out = overlay_supply_incentives(pools, {}, aci)
    assert out[0]["apyReward"] == 4.16            # merit + self summed within ACI
    assert out[0]["reward_source"] == "aci_merit"
    assert out[0]["incentive_conditional"] == 1   # self present -> gated


def test_overlap_takes_max_not_sum():
    pools = [_pool("Celo", "aave-v3", "WETH")]
    lend = build_rebate_lookup([_lend_opp("Celo", "aave", "WETH", 3.0)])
    aci = {("Celo", "WETH"): {"merit": 2.08, "self": 2.08}}   # 4.16 > 3.0
    out = overlay_supply_incentives(pools, lend, aci)
    assert out[0]["apyReward"] == 4.16            # max(3.0, 4.16), NOT 7.16


def test_existing_higher_defillama_reward_kept():
    pools = [_pool("Celo", "aave-v3", "WETH", apy_reward=9.0)]
    aci = {("Celo", "WETH"): {"merit": 2.08, "self": 2.08}}
    out = overlay_supply_incentives(pools, {}, aci)
    assert out[0]["apyReward"] == 9.0             # don't lower an existing reward
    assert out[0]["incentive_conditional"] == 1   # self still flags


def test_untouched_pool_unchanged():
    pools = [_pool("BSC", "venus-core-pool", "USDC")]
    out = overlay_supply_incentives(pools, {}, {})
    assert out[0]["apyReward"] is None
    assert "incentive_conditional" not in out[0]
```

- [ ] **Step 2: Run — expect FAIL** (module doesn't exist)

Run: `PYTHONIOENCODING=utf-8 .venv\Scripts\pytest codee/tests/test_supply_incentives.py -v`

- [ ] **Step 3: Implement**

`codee/services/rewards/supply_incentives.py`:
```python
"""Overlay supply-side incentives from the two aggregators onto pool dicts.

Sources:
  - Merkl LEND campaigns: lookup {(chain_lower, proto, SYM): apr} built with the
    SAME build_rebate_lookup used for borrow (reuse — the shape is identical).
  - ACI Merit map: {(defillama_chain, NORM_SYM): {'merit': apr, 'self': apr}} from
    parse_merit_aprs. merit+self are DISTINCT programs -> summed within ACI.

Cross-source rule: take the MAX of (merkl_lend, aci_total) — never sum across
sources (could be the same program surfaced twice). Never LOWER an existing
DefiLlama apyReward. Self present -> incentive_conditional=1 (zkPoH-gated,
$35k/user cap); the dict flag is read by the ingestor's ACI-cache writer and the
router's read-time tag (no DB column).
"""
from codee.config.config import normalize_symbol
from codee.services.rewards.merkl_match import _norm_chain, _norm_proto, _norm_sym


def overlay_supply_incentives(pools: list[dict],
                              merkl_lend: dict[tuple[str, str, str], float],
                              aci_map: dict[tuple[str, str], dict]) -> list[dict]:
    out: list[dict] = []
    for p in pools:
        merged = dict(p)
        chain_l = _norm_chain(p.get("chain"))
        sym_u = _norm_sym(p.get("symbol"))
        full_proto = _norm_proto(p.get("project"))
        proto_prefix = full_proto.split("-")[0] if "-" in full_proto else full_proto

        merkl_apr = 0.0
        for proto in (full_proto, proto_prefix):
            r = merkl_lend.get((chain_l, proto, sym_u))
            if r is not None:
                merkl_apr = r
                break

        aci = aci_map.get((p.get("chain"), normalize_symbol(p.get("symbol"))))
        aci_apr = (aci["merit"] + aci["self"]) if aci else 0.0

        incentive = max(merkl_apr, aci_apr)
        if incentive > 0:
            existing = merged.get("apyReward") or 0
            if incentive > existing:
                merged["apyReward"] = incentive
                merged["reward_source"] = "aci_merit" if aci_apr >= merkl_apr else "merkl_lend"
        if aci and aci.get("self"):
            merged["incentive_conditional"] = 1
        out.append(merged)
    return out
```

- [ ] **Step 4: Run — expect PASS** (all 5 tests)

Run: `PYTHONIOENCODING=utf-8 .venv\Scripts\pytest codee/tests/test_supply_incentives.py -v`

- [ ] **Step 5: Commit**
```bash
git add codee/services/rewards/supply_incentives.py codee/tests/test_supply_incentives.py
git commit -m "T4-0C: supply-incentive overlay (max of Merkl LEND vs ACI merit+self, conditional flag)"
```

---

### Task 4: Wire the aggregators into the ingestor (+ ACI cache for read-time tags)

**Files:**
- Modify: `codee/config/config.py` (Settings field)
- Modify: `codee/services/pools/ingestor.py`
- Test: `codee/tests/test_pools_ingestor.py`

- [ ] **Step 1: Write the failing test**

Append to `codee/tests/test_pools_ingestor.py` (StubDefiLlama/StubMerkl/StubBinance already exist; StubMerkl gains a supply list):

```python
class StubMerklFull:
    """Stub with BOTH borrow and supply (LEND) opportunity lists."""
    def __init__(self, borrow_opps, supply_opps):
        self.borrow_opps, self.supply_opps = borrow_opps, supply_opps
    async def __aenter__(self): return self
    async def __aexit__(self, *a): pass
    async def fetch_borrow_opportunities(self, max_pages=5): return self.borrow_opps
    async def fetch_supply_opportunities(self, max_pages=5): return self.supply_opps


class StubAci:
    def __init__(self, payload): self.payload = payload
    async def __aenter__(self): return self
    async def __aexit__(self, *a): pass
    async def fetch_merit_aprs(self): return self.payload


async def test_ingestor_applies_supply_incentives_and_writes_aci_cache(db, tmp_path, monkeypatch):
    import json as _json
    from codee.config.config import settings
    aci_cache = tmp_path / "aci.json"
    monkeypatch.setattr(settings, "ACI_INCENTIVES_CACHE", str(aci_cache), raising=False)
    monkeypatch.setattr(settings, "BINANCE_WITHDRAW_CACHE", str(tmp_path / "bw.json"), raising=False)

    supply = [_supply_pool("w1", "Celo", "aave-v3", "WETH", base=0.02, tvl=2_000_000)]
    borrow = [_borrow_pool("w1")]
    aci_payload = {"currentAPR": {"actionsAPR": {
        "celo-supply-weth": 2.08, "self-celo-supply-weth": 2.08}}}
    ing = PoolsIngestor(db, StubDefiLlama(supply, borrow), StubMerklFull([], []),
                        binance=StubBinance([]), aci=StubAci(aci_payload))
    await ing.run_once(ts=1716800000)

    row = await db.fetch_one(
        "SELECT supply_apy_reward, reward_source FROM pools_snapshot WHERE pool_id='w1'")
    assert row[0] == pytest.approx(4.16)       # merit+self landed in the stored reward
    assert row[1] == "aci_merit"
    saved = _json.loads(aci_cache.read_text())
    assert saved["Celo|WETH"] == {"merit": 2.08, "self": 2.08}
```
(Add `import pytest` at top if missing — it should already be there.)

- [ ] **Step 2: Run — expect FAIL** (`aci=` kwarg unknown / no overlay)

Run: `PYTHONIOENCODING=utf-8 .venv\Scripts\pytest codee/tests/test_pools_ingestor.py::test_ingestor_applies_supply_incentives_and_writes_aci_cache -v`

- [ ] **Step 3: Add the cache-path setting**

In `codee/config/config.py` `Settings` (next to `BINANCE_WITHDRAW_CACHE`):
```python
    ACI_INCENTIVES_CACHE: str = str(CONFIG_DIR.parent / "data" / "aci_incentives.json")
```

- [ ] **Step 4: Wire into the ingestor**

In `codee/services/pools/ingestor.py`:
- imports (extend existing lines, don't duplicate):
```python
from codee.config.config import load_aci_chains
from codee.sources.aci.client import AciClient
from codee.sources.aci.parse import parse_merit_aprs
from codee.services.rewards.supply_incentives import overlay_supply_incentives
```
- constructor gains `aci=None`:
```python
    def __init__(self, db: SqliteClient, defillama=None, merkl=None, binance=None, aci=None):
        ...
        self._aci = aci
```
- in `run_once`, fetch the two new feeds. Extend the merkl context block to also pull LEND, and fetch ACI alongside (guarded — failures must not kill the tick):
```python
        async with defillama, merkl:
            supply_task = asyncio.create_task(defillama.fetch_pools_supply())
            borrow_task = asyncio.create_task(defillama.fetch_pools_borrow())
            merkl_task = asyncio.create_task(merkl.fetch_borrow_opportunities())
            merkl_lend_task = asyncio.create_task(merkl.fetch_supply_opportunities())
            supply, borrow, merkl_opps, merkl_lend = await asyncio.gather(
                supply_task, borrow_task, merkl_task, merkl_lend_task)

        aci_map: dict = {}
        try:
            aci = self._aci or AciClient()
            async with aci:
                aci_payload = await aci.fetch_merit_aprs()
            aci_map = parse_merit_aprs(aci_payload, load_aci_chains())
        except Exception:
            log.exception("[Ingestor] ACI merit fetch failed (non-fatal)")
```
- in `_transform`, apply the supply overlay AFTER `overlay_rebates` (reuse `build_rebate_lookup` for the LEND lookup):
```python
        def _transform():
            _joined = join_supply_borrow(supply, borrow)
            _rebates = build_rebate_lookup(merkl_opps)
            _overlaid = overlay_rebates(_joined, _rebates)
            _lend_lookup = build_rebate_lookup(merkl_lend)
            _overlaid = overlay_supply_incentives(_overlaid, _lend_lookup, aci_map)
            _filtered = self._filter(_overlaid)
            _validated = self._validate(_filtered)
            return _validated, len(_joined), len(_rebates)
```
- after the binance-cache block (before `return n`), persist the ACI map for read-time tagging (guarded):
```python
        try:
            aci_cache = Path(settings.ACI_INCENTIVES_CACHE)
            aci_cache.parent.mkdir(parents=True, exist_ok=True)
            aci_cache.write_text(json.dumps({f"{c}|{s}": v for (c, s), v in aci_map.items()}))
        except Exception:
            log.exception("[Ingestor] ACI cache write failed (non-fatal)")
```

- [ ] **Step 5: Run the FULL ingestor file + full suite**

Run: `PYTHONIOENCODING=utf-8 .venv\Scripts\pytest codee/tests/test_pools_ingestor.py -v` then `codee/tests/ -q`
Expected: ALL PASS. Note: existing tests construct `PoolsIngestor(db, StubDefiLlama(...), StubMerkl(...))` where StubMerkl lacks `fetch_supply_opportunities` — if they fail with AttributeError, add `async def fetch_supply_opportunities(self, max_pages=5): return []` to the existing `StubMerkl` class (single place, top of the test file).

- [ ] **Step 6: Commit**
```bash
git add codee/config/config.py codee/services/pools/ingestor.py codee/tests/test_pools_ingestor.py
git commit -m "T4-0D: ingestor pulls Merkl LEND + ACI merit, overlays supply incentives, caches ACI map"
```

---

### Task 5: Read-time `incentive_conditional` tag on passive routes

**Files:**
- Modify: `codee/services/api/models.py` (PassiveRoute)
- Modify: `codee/services/api/router.py`
- Test: `codee/tests/test_api.py`

- [ ] **Step 1: Write the failing test**

Append to `codee/tests/test_api.py`:
```python
async def test_passive_route_incentive_conditional_from_aci_cache(app, tmp_path, monkeypatch):
    app_, db = app
    import time, json as _json
    from codee.config.config import settings
    cache = tmp_path / "aci.json"
    cache.write_text(_json.dumps({"Celo|WETH": {"merit": 2.08, "self": 2.08},
                                  "Celo|USDC": {"merit": 1.0, "self": 0.0}}))
    monkeypatch.setattr(settings, "ACI_INCENTIVES_CACHE", str(cache), raising=False)
    now = int(time.time())
    await db.execute("""INSERT INTO pools_snapshot (pool_id,chain,project,symbol,tvl_usd,supply_apy_base,updated_at)
                        VALUES ('w1','Celo','aave-v3','WETH',5e6,4.2,?)""", (now,))
    await db.execute("""INSERT INTO pools_snapshot (pool_id,chain,project,symbol,tvl_usd,supply_apy_base,updated_at)
                        VALUES ('u1','Celo','aave-v3','USDC',5e6,2.6,?)""", (now,))
    transport = ASGITransport(app=app_)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        body = (await ac.get("/api/codee/routes/passive")).json()
    weth = next(r for r in body if r["symbol"] == "WETH")
    usdc = next(r for r in body if r["symbol"] == "USDC")
    assert weth["incentive_conditional"] is True    # self > 0
    assert usdc["incentive_conditional"] is False   # merit only, no self
```

- [ ] **Step 2: Run — expect FAIL** (field missing)

Run: `PYTHONIOENCODING=utf-8 .venv\Scripts\pytest codee/tests/test_api.py::test_passive_route_incentive_conditional_from_aci_cache -v`

- [ ] **Step 3: Implement**

`codee/services/api/models.py` — add to `PassiveRoute` (last field):
```python
    incentive_conditional: bool = False
```

`codee/services/api/router.py` — add a loader next to `_load_withdraw_map` (reuses `normalize_symbol`, import it from `codee.config.config` by extending the existing import line):
```python
def _load_aci_map() -> dict[tuple[str, str], dict]:
    """ACI incentive cache: {(chain, NORM_SYM): {'merit':x,'self':y}}. {} if absent."""
    try:
        raw = json.loads(Path(settings.ACI_INCENTIVES_CACHE).read_text())
        return {(k.split("|")[0], k.split("|")[1]): v for k, v in raw.items()}
    except Exception:
        return {}


def _is_conditional(chain: str, symbol: str, aci: dict) -> bool:
    e = aci.get((chain, normalize_symbol(symbol)))
    return bool(e and e.get("self"))
```
In `routes_passive`, load `aci = _load_aci_map()` once (next to `wmap`) and set on each route:
```python
            incentive_conditional=_is_conditional(r.chain, r.symbol, aci),
```

- [ ] **Step 4: Run — expect PASS** (full test_api.py)

Run: `PYTHONIOENCODING=utf-8 .venv\Scripts\pytest codee/tests/test_api.py -v`

- [ ] **Step 5: Commit**
```bash
git add codee/services/api/models.py codee/services/api/router.py codee/tests/test_api.py
git commit -m "T4-0E: passive routes tagged incentive_conditional from ACI cache (read-time, no schema change)"
```

---

# PHASE 1 — Binance deposit map

### Task 6: `build_deposit_chains` + dual-map cache (backward compatible)

**Files:**
- Modify: `codee/sources/binance/withdraw.py`
- Modify: `codee/services/pools/ingestor.py` (cache write shape)
- Modify: `codee/services/api/router.py` (loader handles both shapes)
- Test: `codee/tests/test_binance_withdraw.py`, `codee/tests/test_pools_ingestor.py`, `codee/tests/test_api.py`

- [ ] **Step 1: Write the failing tests**

Append to `codee/tests/test_binance_withdraw.py`:
```python
from codee.sources.binance.withdraw import build_deposit_chains

def test_build_deposit_chains_keys_on_deposit_enable():
    raw = [{"coin": "ETH", "networkList": [
        {"network": "ETH", "withdrawEnable": False, "depositEnable": True},
        {"network": "ARBITRUM", "withdrawEnable": True, "depositEnable": False},
    ]}]
    out = build_deposit_chains(raw, NETMAP, CLASSES)
    assert out["ETH"] == {"Ethereum"}          # deposit-enabled only
```

Append to `codee/tests/test_api.py`:
```python
async def test_withdraw_map_loader_handles_old_and_new_shapes(tmp_path, monkeypatch):
    import json as _json
    from codee.config.config import settings
    from codee.services.api.router import _load_withdraw_map, _load_bridge_maps
    cache = tmp_path / "bw.json"
    # old (flat) shape -> withdraw-only
    cache.write_text(_json.dumps({"ETH": ["Arbitrum"]}))
    monkeypatch.setattr(settings, "BINANCE_WITHDRAW_CACHE", str(cache), raising=False)
    assert _load_withdraw_map() == {"ETH": {"Arbitrum"}}
    assert _load_bridge_maps()["deposit"] == {}
    # new shape -> both maps
    cache.write_text(_json.dumps({"withdraw": {"ETH": ["Arbitrum"]}, "deposit": {"ETH": ["Ethereum"]}}))
    assert _load_withdraw_map() == {"ETH": {"Arbitrum"}}
    assert _load_bridge_maps() == {"withdraw": {"ETH": {"Arbitrum"}}, "deposit": {"ETH": {"Ethereum"}}}
```

And update the EXISTING `test_ingestor_writes_binance_withdraw_cache` in `codee/tests/test_pools_ingestor.py` to the new shape:
```python
    saved = _json.loads(cache.read_text())
    assert "Arbitrum" in saved["withdraw"]["ETH"]
```
(also give its `StubBinance` coin a `"depositEnable": True` network entry and assert `saved["deposit"]["ETH"] == ["ARBITRUM"-mapped chain]` if the network is deposit-enabled — concretely: `coins = [{"coin": "ETH", "networkList": [{"network": "ARBITRUM", "withdrawEnable": True, "depositEnable": True}]}]` then `assert "Arbitrum" in saved["deposit"]["ETH"]`.)

- [ ] **Step 2: Run — expect FAIL**

Run: `PYTHONIOENCODING=utf-8 .venv\Scripts\pytest codee/tests/test_binance_withdraw.py codee/tests/test_api.py::test_withdraw_map_loader_handles_old_and_new_shapes -v`

- [ ] **Step 3: Implement**

`codee/sources/binance/withdraw.py` — add (mirror of `build_withdrawable_chains`, keyed on `depositEnable`):
```python
def build_deposit_chains(coin_list: list[dict], network_map: dict, classes: list[str]) -> dict[str, set]:
    """{class: set(chains where Binance ACCEPTS DEPOSITS of that coin)}. Mirrors
    build_withdrawable_chains but keys on depositEnable (needed for the multi-hop
    bridge gate: deposit on the source chain, withdraw on the destination)."""
    out: dict[str, set] = {c: set() for c in classes}
    wanted = set(classes)
    for c in coin_list:
        coin = c.get("coin")
        if coin not in wanted:
            continue
        for net in (c.get("networkList") or []):
            if not net.get("depositEnable"):
                continue
            chain = network_map.get(net.get("network"))
            if chain:
                out[coin].add(chain)
    return out
```

`codee/services/pools/ingestor.py` — in the binance-cache block, build BOTH maps and write the new shape:
```python
            wmap = build_withdrawable_chains(coins, load_binance_networks(), list(load_asset_classes().keys()))
            dmap = build_deposit_chains(coins, load_binance_networks(), list(load_asset_classes().keys()))
            cache_path = Path(settings.BINANCE_WITHDRAW_CACHE)
            cache_path.parent.mkdir(parents=True, exist_ok=True)
            cache_path.write_text(json.dumps({
                "withdraw": {k: sorted(v) for k, v in wmap.items()},
                "deposit": {k: sorted(v) for k, v in dmap.items()},
            }))
```
(import `build_deposit_chains` alongside `build_withdrawable_chains`.)

`codee/services/api/router.py` — replace `_load_withdraw_map` with a dual loader + a thin wrapper (keeps T3 call-sites working):
```python
def _load_bridge_maps() -> dict[str, dict[str, set]]:
    """{'withdraw': {class:set(chains)}, 'deposit': {...}}. Backward compatible:
    the pre-T4 cache was the flat withdraw-only dict."""
    try:
        raw = json.loads(Path(settings.BINANCE_WITHDRAW_CACHE).read_text())
        if "withdraw" in raw:
            return {"withdraw": {k: set(v) for k, v in raw["withdraw"].items()},
                    "deposit": {k: set(v) for k, v in raw.get("deposit", {}).items()}}
        return {"withdraw": {k: set(v) for k, v in raw.items()}, "deposit": {}}
    except Exception:
        return {"withdraw": {}, "deposit": {}}


def _load_withdraw_map() -> dict[str, set]:
    return _load_bridge_maps()["withdraw"]
```

- [ ] **Step 4: Run the FULL suite** (T3 gate tests must still pass with the wrapper)

Run: `PYTHONIOENCODING=utf-8 .venv\Scripts\pytest codee/tests/ -q`
Expected: ALL PASS.

- [ ] **Step 5: Commit**
```bash
git add codee/sources/binance/withdraw.py codee/services/pools/ingestor.py codee/services/api/router.py codee/tests/test_binance_withdraw.py codee/tests/test_api.py codee/tests/test_pools_ingestor.py
git commit -m "T4-1: Binance deposit map + dual-shape bridge cache (backward compatible)"
```

---

# PHASE 2 — pathfinding (pure analyzer)

### Task 7: `MultiHopPath` + `enumerate_multihop_paths` (beam search)

**Files:**
- Modify: `codee/services/routes/analyzer.py` (append; keep 100% pure)
- Test: `codee/tests/test_analyzer_multihop.py`

- [ ] **Step 1: Write the failing tests**

`codee/tests/test_analyzer_multihop.py`:
```python
import pytest
from codee.services.routes.analyzer import enumerate_multihop_paths, MultiHopPath


def _p(chain, project, symbol, base=0.0, borrow_base=None, ltv=0.80, tvl=5e6):
    return {"pool": f"{chain}-{project}-{symbol}", "chain": chain, "project": project,
            "symbol": symbol, "apyBase": base, "apyReward": 0.0,
            "apyBaseBorrow": borrow_base, "apyRewardBorrow": None,
            "ltv": ltv, "tvlUsd": tvl}


# Fixture graph: USDC@A earns 10%, can borrow ETH@A at 2% (ltv .80 -> per-iter .75),
# ETH supplies at 5% on chain B. Bridge maps allow it. Expected best 2-hop:
#   net = 1*10  - 0.75*2 + 0.75*5 = 12.25
POOLS = [
    _p("ChainA", "aave-v3", "USDC", base=10.0, borrow_base=4.0, ltv=0.80, tvl=4e6),
    _p("ChainA", "aave-v3", "WETH", base=0.5, borrow_base=2.0, ltv=0.80, tvl=3e6),
    _p("ChainB", "aave-v3", "WETH", base=5.0, borrow_base=3.0, ltv=0.80, tvl=2e6),
]
WMAP = {"USDC": {"ChainA"}, "ETH": {"ChainB"}, "USDT": set(), "BTC": set()}
DMAP = {"USDC": {"ChainA"}, "ETH": {"ChainA"}, "USDT": set(), "BTC": set()}
COSTS = {"ChainA": 0.10, "ChainB": 0.20}


def test_two_hop_path_found_with_hand_computed_metric():
    paths = enumerate_multihop_paths(POOLS, WMAP, DMAP, COSTS, capital_class="USDC")
    two = [p for p in paths if p.hops == 2]
    assert two, "expected a 2-hop path"
    best = two[0]
    assert best.nodes == (("ChainA", "aave-v3", "USDC"), ("ChainB", "aave-v3", "WETH"))
    assert best.net_apy == pytest.approx(12.25)      # 10 - .75*2 + .75*5
    assert best.bridge_cost_usd == pytest.approx(0.20)  # dest chain cost
    assert best.min_liquidity_usd == pytest.approx(2e6) # thinnest pool on the path
    assert best.entry_asset_class == "USDC"


def test_one_hop_root_is_emitted():
    paths = enumerate_multihop_paths(POOLS, WMAP, DMAP, COSTS, capital_class="USDC")
    ones = [p for p in paths if p.hops == 1]
    assert ones and ones[0].net_apy == pytest.approx(10.0)


def test_blocked_bridge_kills_the_hop():
    dmap = {"USDC": {"ChainA"}, "ETH": set(), "USDT": set(), "BTC": set()}  # can't deposit ETH
    paths = enumerate_multihop_paths(POOLS, WMAP, dmap, COSTS, capital_class="USDC")
    assert all(p.hops == 1 for p in paths)


def test_root_requires_binance_withdrawable_chain():
    wmap = {"USDC": set(), "ETH": {"ChainB"}, "USDT": set(), "BTC": set()}  # can't withdraw USDC anywhere
    paths = enumerate_multihop_paths(POOLS, wmap, DMAP, COSTS, capital_class="USDC")
    assert paths == []


def test_max_hops_respected_and_same_chain_dest_excluded():
    paths = enumerate_multihop_paths(POOLS, WMAP, DMAP, COSTS, capital_class="USDC", max_hops=1)
    assert all(p.hops == 1 for p in paths)
    # dest == source chain is never allowed (must actually move chains)
    full = enumerate_multihop_paths(POOLS, WMAP, DMAP, COSTS, capital_class="USDC")
    for p in full:
        chains = [n[0] for n in p.nodes]
        assert all(chains[i] != chains[i+1] for i in range(len(chains)-1))


def test_empty_maps_no_paths():
    assert enumerate_multihop_paths(POOLS, {}, {}, COSTS, capital_class="USDC") == []
```

- [ ] **Step 2: Run — expect FAIL** (imports don't exist)

Run: `PYTHONIOENCODING=utf-8 .venv\Scripts\pytest codee/tests/test_analyzer_multihop.py -v`

- [ ] **Step 3: Implement** — append to `codee/services/routes/analyzer.py` (after `cross_chain_carry`; reuse the existing `effective_supply_apy`, `effective_borrow_apr`, `per_iter_ltv`, `normalize_symbol`; extend the config import with `asset_class`):

```python
# --- Multi-hop cross-chain carry (T4 spec) ----------------------------------
from codee.config.config import asset_class   # merge into the existing config import line


@dataclass(frozen=True)
class MultiHopPath:
    nodes: tuple                 # ((chain, project, symbol), ...) one per supply leg
    net_apy: float               # leveraged net carry % on the initial capital
    hops: int                    # len(nodes)
    bridge_cost_usd: float       # sum of dest-chain bridge costs
    min_liquidity_usd: float     # thinnest tvlUsd among ALL pools used (supply + borrow legs)
    entry_asset_class: str | None


def enumerate_multihop_paths(pools: list[dict], withdraw_map: dict, deposit_map: dict,
                             bridge_costs: dict, *, max_hops: int = 4,
                             capital_class: str | None = None,
                             beam_width: int = 300, limit: int = 200) -> list[MultiHopPath]:
    """Beam-search enumeration of supply→borrow→bridge→supply chains (spec §2).

    A hop lives on ONE platform: supply A on (chain,project), borrow B on the SAME
    (chain,project), Binance-bridge B (deposit on source chain AND withdraw on dest
    chain, by B's class), supply B on the dest. Chains always end on a supply; the
    dest chain must differ from the source. Beam search bounds the combinatorial
    blow-up: at each depth only the top `beam_width` partial paths (by net carry)
    are expanded; every partial path is also a terminal candidate. Pure: no I/O.
    """
    # index: (chain, project) -> {normalized_class_asset: pool}
    by_cp: dict[tuple[str, str], dict[str, dict]] = {}
    supply_nodes: dict[str, list[tuple[str, str, dict]]] = defaultdict(list)  # class -> [(chain, proj, pool)]
    for p in pools:
        cls = asset_class(p.get("symbol"))
        if cls is None:
            continue
        key = (p.get("chain"), p.get("project"))
        by_cp.setdefault(key, {})[normalize_symbol(p.get("symbol"))] = p
        supply_nodes[cls].append((p.get("chain"), p.get("project"), p))

    def node_id(chain, proj, pool):
        return (chain, proj, normalize_symbol(pool.get("symbol")))

    # state: (visited frozenset, nodes tuple, last(chain,proj,pool), S, net, bridge$, minliq, entry_cls)
    frontier = []
    emitted: list[MultiHopPath] = []
    for (chain, proj), assets in by_cp.items():
        for sym, pool in assets.items():
            cls = asset_class(sym)
            if capital_class is not None and cls != capital_class:
                continue
            if chain not in withdraw_map.get(cls, set()):
                continue                      # can't withdraw the starting capital here
            net = effective_supply_apy(pool)
            nid = node_id(chain, proj, pool)
            frontier.append((frozenset([nid]), (nid,), (chain, proj, pool),
                             1.0, net, 0.0, float(pool.get("tvlUsd") or 0), cls))

    for _depth in range(1, max_hops):         # expansions: hop 2 .. max_hops
        frontier.sort(key=lambda s: s[4], reverse=True)
        frontier = frontier[:beam_width]
        nxt = []
        for visited, nodes, (chain, proj, pool), S, net, bridge, minliq, entry in frontier:
            emitted.append(MultiHopPath(nodes, net, len(nodes), bridge, minliq, entry))
            r = per_iter_ltv(pool.get("ltv"))
            if r <= 0:
                continue
            d = S * r
            platform_assets = by_cp.get((chain, proj), {})
            for bsym, bpool in platform_assets.items():
                if bpool.get("apyBaseBorrow") is None:
                    continue
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
                    new_net = net - d * bor + d * effective_supply_apy(spool)
                    new_liq = min(minliq, float(bpool.get("tvlUsd") or 0),
                                  float(spool.get("tvlUsd") or 0))
                    nxt.append((visited | {nid}, nodes + (nid,), (c2, p2, spool),
                                d, new_net, bridge + float(bridge_costs.get(c2, 1.0)),
                                new_liq, entry))
        frontier = nxt

    for visited, nodes, _last, S, net, bridge, minliq, entry in frontier:  # deepest level
        emitted.append(MultiHopPath(nodes, net, len(nodes), bridge, minliq, entry))

    emitted.sort(key=lambda p: p.net_apy, reverse=True)
    return emitted[:limit]
```

- [ ] **Step 4: Run — expect PASS** (all 6 tests) + golden test unaffected

Run: `PYTHONIOENCODING=utf-8 .venv\Scripts\pytest codee/tests/test_analyzer_multihop.py codee/tests/test_golden.py -v`

- [ ] **Step 5: Commit**
```bash
git add codee/services/routes/analyzer.py codee/tests/test_analyzer_multihop.py
git commit -m "T4-2: pure multi-hop pathfinding (beam search, leveraged carry, Binance bridge gate)"
```

---

# PHASE 3 — API

### Task 8: `MultiHopRoute` model + `/routes/multihop` endpoint

**Files:**
- Modify: `codee/services/api/models.py`
- Modify: `codee/services/api/router.py`
- Test: `codee/tests/test_api.py`

- [ ] **Step 1: Write the failing test**

Append to `codee/tests/test_api.py`:
```python
async def test_multihop_endpoint_returns_paths(app, tmp_path, monkeypatch):
    app_, db = app
    import time, json as _json
    from codee.config.config import settings
    bw = tmp_path / "bw.json"
    bw.write_text(_json.dumps({"withdraw": {"USDC": ["ChainA"], "ETH": ["ChainB"]},
                               "deposit":  {"USDC": ["ChainA"], "ETH": ["ChainA"]}}))
    monkeypatch.setattr(settings, "BINANCE_WITHDRAW_CACHE", str(bw), raising=False)
    monkeypatch.setattr(settings, "ACI_INCENTIVES_CACHE", str(tmp_path / "none.json"), raising=False)
    now = int(time.time())
    rows = [("a1", "ChainA", "aave-v3", "USDC", 4e6, 10.0, 4.0, 0.80),
            ("a2", "ChainA", "aave-v3", "WETH", 3e6, 0.5, 2.0, 0.80),
            ("b1", "ChainB", "aave-v3", "WETH", 2e6, 5.0, 3.0, 0.80)]
    for pid, ch, pr, sym, tvl, sup, bor, ltv in rows:
        await db.execute("""INSERT INTO pools_snapshot
            (pool_id,chain,project,symbol,tvl_usd,supply_apy_base,borrow_apr_base,ltv,updated_at)
            VALUES (?,?,?,?,?,?,?,?,?)""", (pid, ch, pr, sym, tvl, sup, bor, ltv, now))
    transport = ASGITransport(app=app_)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        resp = await ac.get("/api/codee/routes/multihop?capital=USDC")
    assert resp.status_code == 200
    body = resp.json()
    two = [r for r in body if r["hops"] == 2]
    assert two
    best = two[0]
    assert [n["chain"] for n in best["path"]] == ["ChainA", "ChainB"]
    assert best["net_apy"] == pytest.approx(12.25)
    assert best["entry_asset_classes"] == ["USDC"]
    assert best["incentive_conditional"] is False
```

- [ ] **Step 2: Run — expect FAIL** (endpoint missing)

Run: `PYTHONIOENCODING=utf-8 .venv\Scripts\pytest codee/tests/test_api.py::test_multihop_endpoint_returns_paths -v`

- [ ] **Step 3: Implement**

`codee/services/api/models.py`:
```python
class MultiHopNode(BaseModel):
    chain: str
    project: str
    symbol: str


class MultiHopRoute(BaseModel):
    path: list[MultiHopNode]
    net_apy: float
    hops: int
    bridge_cost_usd: float
    min_liquidity_usd: float
    entry_asset_classes: list[str] = []
    incentive_conditional: bool = False   # any leg has a Self-gated incentive
```

`codee/services/api/router.py`:
- extend the config import with `load_chains` and the models import with `MultiHopNode, MultiHopRoute`; extend the analyzer import with `enumerate_multihop_paths`.
- add the endpoint:
```python
@router.get("/routes/multihop", response_model=list[MultiHopRoute])
async def routes_multihop(db: SqliteClient = Depends(get_db),
                          capital: str | None = Query(None),
                          limit: int = Query(50, le=200)):
    """Multi-hop Binance-routable carry chains, enumerated to the hard 4-hop cap.
    The client filters depth locally on each route's `hops` field."""
    pools = await _load_pools(db)
    maps = _load_bridge_maps()
    aci = _load_aci_map()
    bridge_costs = {c: (cfg.get("bridge_cost_usd") if cfg.get("bridge_cost_usd") is not None else 1.0)
                    for c, cfg in load_chains()["chains"].items()}
    paths = enumerate_multihop_paths(pools, maps["withdraw"], maps["deposit"], bridge_costs,
                                     capital_class=capital, limit=limit)
    return [MultiHopRoute(
        path=[MultiHopNode(chain=c, project=pr, symbol=s) for (c, pr, s) in p.nodes],
        net_apy=p.net_apy, hops=p.hops, bridge_cost_usd=p.bridge_cost_usd,
        min_liquidity_usd=p.min_liquidity_usd,
        entry_asset_classes=[p.entry_asset_class] if p.entry_asset_class else [],
        incentive_conditional=any(_is_conditional(c, s, aci) for (c, _pr, s) in p.nodes),
    ) for p in paths]
```
Note: `MultiHopPath.nodes` symbols are already normalized (from `node_id`) — `_is_conditional` re-normalizes harmlessly.

- [ ] **Step 4: Run — expect PASS** (full test_api.py + full suite)

Run: `PYTHONIOENCODING=utf-8 .venv\Scripts\pytest codee/tests/ -q`

- [ ] **Step 5: Commit**
```bash
git add codee/services/api/models.py codee/services/api/router.py codee/tests/test_api.py
git commit -m "T4-3: /routes/multihop endpoint (paths to 4-hop cap, conditional-incentive tag)"
```

---

# PHASE 4 — frontend

### Task 9: Multi-Hop sub-tab + "Max hops" selector

**Files:**
- Modify: `Volume_tracker/web/index.html` (sub-tab button, VIEWS entry, hops selector, wiring)

No automated test; verify via `local_harness` in Step 6.

- [ ] **Step 1: Add the sub-tab button**

In the Codee sub-tab strip (search for `data-codeetab="crosschain"`), add after the Cross-Chain button:
```html
            <button class="mm-routes-tab" data-codeetab="multihop">Multi-Hop</button>
```

- [ ] **Step 2: Add the hops selector HTML**

In `#codeeLiqFilter`, after the `#codeeWdrawWrap` label, add:
```html
            <span style="margin-left:8px;">Max hops</span>
            <select id="codeeHopsSelect" aria-label="Max hops"
              style="background:var(--bg-secondary);border:1px solid var(--border);border-radius:4px;color:var(--text-1);font-family:'JetBrains Mono',monospace;font-size:11px;padding:3px 8px;outline:none;cursor:pointer;">
              <option value="">All</option>
              <option value="1">1</option>
              <option value="2">2</option>
              <option value="3">3</option>
              <option value="4">4</option>
            </select>
```

- [ ] **Step 3: Add the VIEWS entry**

In the `VIEWS` object, after `crosschain`, add:
```javascript
    multihop: {
      cols: ['Route', 'Net APY', 'Hops', 'Bridge $', 'Liquidity'],
      ralign: [1, 2, 3, 4],
      path: '/routes/multihop?limit=50',
      caveat: 'Theoretical ceiling — APY excludes bridge cost (shown separately), per-leg liquidation risk, and gated incentives (⚠ = conditional).',
      empty: 'No multi-hop routes — check the Binance bridge maps (need server BI keys) or relax filters.',
      liq: (d) => d.min_liquidity_usd,
      asset: (d) => (d.path || []).map(n => n.symbol).join('/'),
      row: (d) => `<td>${(d.path || []).map(n => `${n.symbol}·${n.chain}`).join(' → ')}${d.incentive_conditional ? ' ⚠' : ''}</td>
        <td class="r">${codeeFmtApy(d.net_apy)}</td>
        <td class="r">${d.hops}</td>
        <td class="r">$${Number(d.bridge_cost_usd).toFixed(2)}</td>
        <td class="r">${codeeFmtTvl(d.min_liquidity_usd)}</td>`,
    },
```
(`entry_asset_classes` already powers the Capital selector for these rows; `liq` powers the slider.)

- [ ] **Step 4: State + filter + wiring**

Next to `let codeeWdrawOnly = false;` add:
```javascript
  let codeeMaxHops = '';           // '' = All
```
In `renderCodeeTable`, after the withdrawable filter, add:
```javascript
    if (codeeMaxHops) {
      rows = rows.filter((d) => d.hops == null || d.hops <= Number(codeeMaxHops));
    }
```
(Keeping `hops == null` rows visible means the selector is a no-op on the other views, whose rows have no `hops` field.)

In `codeeInit`, after the wdrawOnly wiring, add:
```javascript
    const hopsSel = document.getElementById('codeeHopsSelect');
    hopsSel.addEventListener('change', () => {
      codeeMaxHops = hopsSel.value;
      if (codeeLastData && activeTab !== 'rewards' && activeTab !== 'history') {
        renderCodeeTable(activeTab, codeeLastData);
      }
    });
```

- [ ] **Step 5: Static check**

`grep -n "codeeHopsSelect\|codeeMaxHops\|multihop" web/index.html` — expect: sub-tab button (1), VIEWS entry (path+key), selector HTML + getElementById, state + filter + handler.

- [ ] **Step 6: Verify via harness**

Run: `PYTHONIOENCODING=utf-8 .venv\Scripts\python -m codee.scripts.local_harness`, open `http://127.0.0.1:8011/`, Codee tab → Multi-Hop sub-tab. Without local BI keys the bridge maps are empty → the empty-state message must show (graceful). To see real paths, seed `codee/data/binance_withdraw.json` AFTER the startup tick with a populated `{"withdraw":{...},"deposit":{...}}` for the chains in your snapshot, reload, and confirm: paths render as `SYM·Chain → SYM·Chain`, the Max hops selector narrows rows, the Capital selector + liquidity slider apply. Stop the harness.

- [ ] **Step 7: Commit**
```bash
git add web/index.html
git commit -m "T4-4: Multi-Hop sub-tab (path rows, Max-hops selector, ceiling caveat)"
```

---

# PHASE 5 — mirror + deploy

### Task 10: Mirror backend to AAVE_STRAT

**Files (in `F:\codefee\AAVE_STRAT`):** all backend changes from Tasks 1–8 (NOT Task 9). Bare imports (`from sources.aci…`, `from config.config…`). Port by inspecting the VT commits (`git -C /f/codefee/Volume_tracker log --oneline` for this branch). Same escalation rule as always: if a file diverges so the edit doesn't map cleanly, report instead of force-fitting.

- [ ] **Step 1:** Apply the equivalent edits (new files copied verbatim minus the `codee.` prefix; modified files get the same hunks).
- [ ] **Step 2:** Run `PYTHONIOENCODING=utf-8 .venv\Scripts\pytest -q` from `F:\codefee\AAVE_STRAT`. Expected: all pass.
- [ ] **Step 3:** Commit:
```bash
git add config services sources tests
git commit -m "T4 (mirror): multi-hop backend — aggregators, deposit map, pathfinding, API"
```

### Task 11: Deploy (gated on explicit user approval)

> Backend `.py` + config changed → **`systemctl restart` required**. Do NOT deploy without the
> user's explicit go-ahead for this production push.

- [ ] **Step 1:** Full suites green in both repos; merge branch → `main` (VT) / `master` (AAVE_STRAT, push).
- [ ] **Step 2:** git-bundle ff from server HEAD; SFTP; fetch + `--ff-only` merge; restart.
- [ ] **Step 3:** Verify: service active; `[Codee] initialized`; health/orders 200; `/routes/multihop` 200 with paths (server has BI keys → real bridge maps); `data/aci_incentives.json` written; a Celo WETH passive row shows reward ≈4.2% with `incentive_conditional=true`; dashboard serves the Multi-Hop tab + hops selector.

---

## Self-review notes

- **Spec coverage:** §0A Merkl LEND (Task 1), §0B ACI (Task 2), overlay incl. max-rule + conditional flag (Task 3), ingest wiring + ACI cache (Task 4), read-time tag (Task 5), §4 deposit map + dual cache (Task 6), §1-3 position model/algorithm/metric (Task 7 — beam search implements the spec's "cap emitted paths" pruning), §5 API (Task 8) + UI with Max-hops selector (Task 9), mirror (10), deploy (11). The spec's "split (protocol/Merkl/Merit/Self)" is surfaced minimally as the conditional flag + reward_source; full per-component split in the UI is deferred (noted — acceptable MVP reading of §0).
- **Type consistency:** `parse_merit_aprs → {(chain, NORM_SYM): {'merit','self'}}` consumed by `overlay_supply_incentives` and the `Celo|WETH` cache encoding consumed by `_load_aci_map`; `_load_bridge_maps()['withdraw'/'deposit']` feed `enumerate_multihop_paths(pools, withdraw_map, deposit_map, bridge_costs, …)`; `MultiHopPath.nodes` tuples `(chain, project, symbol)` serialize to `MultiHopNode`. Consistent.
- **No schema change:** conditional tag + bridge maps + ACI data are JSON caches read per request (existing pattern), so no migration machinery needed.
- **Purity:** analyzer gains only pure code; all I/O stays in sources/ingestor/router.
- **Golden test:** untouched (its own pipeline).
- **Perf guard:** beam_width=300 bounds depth-4 enumeration; if request latency is still high in practice, move the call behind a per-tick cache (noted in spec §2) — measure first.
