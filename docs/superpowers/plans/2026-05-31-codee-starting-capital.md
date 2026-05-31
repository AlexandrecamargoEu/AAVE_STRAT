# Codee Starting-Capital Anchor Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Let the user pick a Binance starting asset (USDC/USDT/ETH/BTC) and see only routes that enter with that asset on a chain Binance can withdraw to.

**Architecture:** Phase A adds an asset-class config + universe expansion to ETH/BTC + a client-side anchor selector (filters by `entry_asset_classes`). Phase B adds a signed Binance `capital/config` source that produces a `class → {withdrawable chains}` map, cached to JSON each ingest tick, and a per-route `binance_withdrawable` flag + a "withdrawable only" toggle. The analyzer stays pure; the Binance gate is computed in the router/ingestor layer.

**Tech Stack:** Python 3.13, FastAPI, pydantic v2, aiohttp, hmac/hashlib (Binance signing), pytest (offline fixtures); vanilla JS in `web/index.html`.

**Where:** Backend in `F:\codefee\Volume_tracker\codee\…` (branch created at execution), **mirrored** to `F:\codefee\AAVE_STRAT\…` (bare imports, NO frontend). Frontend in `Volume_tracker\web\index.html` only. Run tests from `F:\codefee\Volume_tracker`: `PYTHONIOENCODING=utf-8 .venv\Scripts\pytest codee/tests/ -q`. (`PYTHONIOENCODING=utf-8` matters — fixtures contain the `₮`/`USD₮` glyph.)

**Refinement vs spec:** the spec's per-route `entry_asset_class` (string) is implemented as `entry_asset_classes: list[str]` (uniform across views; loops carry both legs' classes). Everything else matches the spec.

---

# PHASE A — asset classes + universe + anchor selector

### Task A1: Asset-class config + `asset_class()` helper

**Files:**
- Create: `codee/config/asset_classes.json`
- Modify: `codee/config/config.py`
- Test: `codee/tests/test_config.py`

- [ ] **Step 1: Create the config file**

`codee/config/asset_classes.json`:
```json
{
  "USDC": ["USDC", "USDC.E", "USDC.B"],
  "USDT": ["USDT", "USDT0"],
  "ETH":  ["ETH", "WETH"],
  "BTC":  ["BTC", "WBTC", "BTCB", "BTC.B", "CBBTC"]
}
```

- [ ] **Step 2: Write the failing test**

Append to `codee/tests/test_config.py`:
```python
def test_asset_class_maps_tickers_to_binance_classes():
    from codee.config.config import asset_class
    assert asset_class("WETH") == "ETH"
    assert asset_class("ETH") == "ETH"
    assert asset_class("WBTC") == "BTC"
    assert asset_class("BTCB") == "BTC"
    assert asset_class("BTC.B") == "BTC"
    assert asset_class("USD₮") == "USDT"     # glyph normalizes (T0) then matches
    assert asset_class("USDC.E") == "USDC"
    assert asset_class("DAI") is None         # a stable, but NOT a starting-capital class
    assert asset_class(None) is None
```

- [ ] **Step 3: Run it — expect FAIL**

Run: `PYTHONIOENCODING=utf-8 .venv\Scripts\pytest codee/tests/test_config.py::test_asset_class_maps_tickers_to_binance_classes -v`
Expected: FAIL — `cannot import name 'asset_class'`.

- [ ] **Step 4: Implement loader + helper**

In `codee/config/config.py`, add a loader next to the other `load_*` functions:
```python
def load_asset_classes() -> dict:
    return _load_json("asset_classes.json")
```
And, after `normalize_symbol`, add (uses `@lru_cache` to build a reverse index once):
```python
from functools import lru_cache

@lru_cache(maxsize=1)
def _ticker_to_class() -> dict[str, str]:
    rev = {}
    for cls, tickers in load_asset_classes().items():
        for t in tickers:
            rev[normalize_symbol(t)] = cls
    return rev


def asset_class(symbol: str | None) -> str | None:
    """Binance starting-capital class (USDC/USDT/ETH/BTC) for a ticker, or None.
    Matches on the normalized symbol (folds the ₮ glyph, etc.)."""
    if not symbol:
        return None
    return _ticker_to_class().get(normalize_symbol(symbol))
```
(`lru_cache` import may already be present at top — if so, don't duplicate it; just use it.)

- [ ] **Step 5: Run it — expect PASS**

Run: `PYTHONIOENCODING=utf-8 .venv\Scripts\pytest codee/tests/test_config.py -v`
Expected: PASS (new test + all existing).

- [ ] **Step 6: Commit**
```bash
git add codee/config/asset_classes.json codee/config/config.py codee/tests/test_config.py
git commit -m "T3a: asset_classes config + asset_class() helper (Binance starting-capital classes)"
```

---

### Task A2: Universe expansion — ingest ETH/BTC pools

**Files:**
- Modify: `codee/services/pools/ingestor.py` (`_filter`, ~line 108-110; import ~line 13)
- Test: `codee/tests/test_pools_ingestor.py`

- [ ] **Step 1: Write the failing test**

Append to `codee/tests/test_pools_ingestor.py`:
```python
async def test_ingestor_keeps_eth_and_btc_class_pools(db):
    """ETH/BTC starting-capital classes are now in scope, alongside stablecoins."""
    supply = [
        _supply_pool("e1", "Arbitrum", "aave-v3", "WETH", base=2.0, tvl=5_000_000),
        _supply_pool("b1", "Avalanche", "aave-v3", "BTC.B", base=0.5, tvl=5_000_000),
        _supply_pool("x1", "BSC", "pancake", "CAKE", base=9.0, tvl=5_000_000),  # not a class -> dropped
    ]
    borrow = [_borrow_pool("e1"), _borrow_pool("b1"), _borrow_pool("x1")]
    ing = PoolsIngestor(db, StubDefiLlama(supply, borrow), StubMerkl([]))
    n = await ing.run_once(ts=1716800000)
    assert n == 2  # WETH + BTC.B kept; CAKE dropped
    rows = await db.fetch_all("SELECT symbol FROM pools_snapshot ORDER BY pool_id")
    assert rows == [("BTC.B",), ("WETH",)]
```

- [ ] **Step 2: Run it — expect FAIL**

Run: `PYTHONIOENCODING=utf-8 .venv\Scripts\pytest codee/tests/test_pools_ingestor.py::test_ingestor_keeps_eth_and_btc_class_pools -v`
Expected: FAIL — WETH/BTC.B dropped (only stables pass today), so `n == 0`.

- [ ] **Step 3: Widen the symbol gate**

In `codee/services/pools/ingestor.py`, update the import (line ~13) to also import `asset_class`:
```python
from codee.config.config import settings, load_chains, load_stable_symbols, load_projects, normalize_symbol, asset_class
```
In `_filter`, replace the symbol membership check:
```python
            sym = normalize_symbol(p.get("symbol"))   # folds USD₮ -> USDT etc.
            if sym not in stables and asset_class(p.get("symbol")) is None:
                continue
```

- [ ] **Step 4: Run it — expect PASS**

Run: `PYTHONIOENCODING=utf-8 .venv\Scripts\pytest codee/tests/test_pools_ingestor.py -v`
Expected: PASS (new + existing, incl. the USD₮ glyph test).

- [ ] **Step 5: Commit**
```bash
git add codee/services/pools/ingestor.py codee/tests/test_pools_ingestor.py
git commit -m "T3a: expand ingestion universe to ETH/BTC starting-capital classes"
```

---

### Task A3: `entry_asset_classes` on the API routes

**Files:**
- Modify: `codee/services/api/models.py` (PassiveRoute, LoopRoute, CrossChainRoute)
- Modify: `codee/services/api/router.py` (routes_passive, routes_loops, routes_crosschain)
- Test: `codee/tests/test_api.py`

- [ ] **Step 1: Write the failing test**

Append to `codee/tests/test_api.py`:
```python
async def test_passive_route_includes_entry_asset_classes(app):
    app_, db = app
    import time
    now = int(time.time())
    await db.execute(
        """INSERT INTO pools_snapshot (pool_id, chain, project, symbol, tvl_usd,
           supply_apy_base, updated_at) VALUES (?, 'Arbitrum', 'aave-v3', 'WETH', 5e6, 2.0, ?)""",
        ("e1", now))
    await db.execute(
        """INSERT INTO pools_snapshot (pool_id, chain, project, symbol, tvl_usd,
           supply_apy_base, updated_at) VALUES (?, 'BSC', 'aave-v3', 'DAI', 5e6, 3.0, ?)""",
        ("d1", now))
    transport = ASGITransport(app=app_)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        resp = await ac.get("/api/codee/routes/passive")
    body = resp.json()
    weth = next(r for r in body if r["symbol"] == "WETH")
    dai = next(r for r in body if r["symbol"] == "DAI")
    assert weth["entry_asset_classes"] == ["ETH"]
    assert dai["entry_asset_classes"] == []   # DAI is not a starting-capital class
```

- [ ] **Step 2: Run it — expect FAIL**

Run: `PYTHONIOENCODING=utf-8 .venv\Scripts\pytest codee/tests/test_api.py::test_passive_route_includes_entry_asset_classes -v`
Expected: FAIL — `entry_asset_classes` not in response.

- [ ] **Step 3: Add the field to all three models**

In `codee/services/api/models.py`, add to `PassiveRoute`, `LoopRoute`, and `CrossChainRoute` (each as the last field):
```python
    entry_asset_classes: list[str] = []
```

- [ ] **Step 4: Populate in the router**

In `codee/services/api/router.py`, add the import:
```python
from codee.config.config import settings, asset_class
```
(merge with the existing `from codee.config.config import settings` line — don't duplicate.)

Add a tiny helper near the top of the module:
```python
def _classes(*symbols: str | None) -> list[str]:
    """Distinct Binance starting-capital classes among the given tickers, order-stable."""
    out: list[str] = []
    for s in symbols:
        c = asset_class(s)
        if c and c not in out:
            out.append(c)
    return out
```
Then set `entry_asset_classes` on each constructed route:
- `routes_passive` → `PassiveRoute(..., entry_asset_classes=_classes(r.symbol))`
- `routes_loops` → `LoopRoute(..., entry_asset_classes=_classes(r.asset_x, r.asset_y))`
- `routes_crosschain` → `CrossChainRoute(..., entry_asset_classes=_classes(r.symbol))`

- [ ] **Step 5: Run it — expect PASS**

Run: `PYTHONIOENCODING=utf-8 .venv\Scripts\pytest codee/tests/test_api.py -v`
Expected: PASS (all API tests).

- [ ] **Step 6: Commit**
```bash
git add codee/services/api/models.py codee/services/api/router.py codee/tests/test_api.py
git commit -m "T3a: expose entry_asset_classes on passive/loops/crosschain routes"
```

---

### Task A4: Frontend — starting-capital anchor selector

**Files:**
- Modify: `Volume_tracker/web/index.html` — filter row (`#codeeLiqFilter`, ~line 2649) + Codee JS IIFE (`VIEWS`, `renderCodeeTable`, `codeeInit`).

No automated test (monolithic VT dashboard); verify via `local_harness` in the final Phase-A step.

- [ ] **Step 1: Add the selector HTML**

In `web/index.html`, inside `#codeeLiqFilter`, after the asset `<input id="codeeAssetFilter" …>` element, add:
```html
            <span style="margin-left:8px;">Capital</span>
            <select id="codeeCapitalSelect" aria-label="Starting capital"
              style="background:var(--bg-secondary);border:1px solid var(--border);border-radius:4px;color:var(--text-1);font-family:'JetBrains Mono',monospace;font-size:11px;padding:3px 8px;outline:none;cursor:pointer;">
              <option value="">All</option>
              <option value="USDC">USDC</option>
              <option value="USDT">USDT</option>
              <option value="ETH">ETH</option>
              <option value="BTC">BTC</option>
            </select>
            <span id="codeeVolatileNote" style="display:none;color:var(--text-3);font-style:italic;">volatile collateral — price exposure</span>
```

- [ ] **Step 2: Add state + filter logic**

In the Codee IIFE, next to `let codeeAssetFilter = '';`, add:
```javascript
  let codeeCapital = '';           // selected starting-capital class ('' = All)
```
In `renderCodeeTable`, after the asset-filter block, add a class filter (uses the per-route `entry_asset_classes`):
```javascript
    if (codeeCapital) {
      rows = rows.filter((d) => (d.entry_asset_classes || []).includes(codeeCapital));
    }
```

- [ ] **Step 3: Wire the selector in `codeeInit`**

After the asset-input wiring in `window.codeeInit`, add:
```javascript
    const capSel = document.getElementById('codeeCapitalSelect');
    const volNote = document.getElementById('codeeVolatileNote');
    capSel.addEventListener('change', () => {
      codeeCapital = capSel.value;
      volNote.style.display = (codeeCapital === 'ETH' || codeeCapital === 'BTC') ? 'inline' : 'none';
      if (codeeLastData && activeTab !== 'rewards' && activeTab !== 'history') {
        renderCodeeTable(activeTab, codeeLastData);
      }
    });
```

- [ ] **Step 4: Verify via harness**

Run: `PYTHONIOENCODING=utf-8 .venv\Scripts\python -m codee.scripts.local_harness`
Open `http://127.0.0.1:8011/`, Codee tab. Confirm: the Capital dropdown exists; selecting **ETH** narrows tables to rows whose `entry_asset_classes` include ETH (and shows the volatile note); **BTC** likewise; **All** clears it; Rewards/History hide the controls. (WETH/WBTC pools should now appear since the server harness ingests them.) Stop the harness when done.

- [ ] **Step 5: Commit**
```bash
git add web/index.html
git commit -m "T3a: starting-capital anchor selector (client-side filter by entry_asset_classes)"
```

---

# PHASE B — Binance-withdrawable gate

### Task B1: Binance network→chain map + pure `build_withdrawable_chains`

**Files:**
- Create: `codee/config/binance_networks.json`
- Create: `codee/sources/binance/__init__.py` (empty)
- Create: `codee/sources/binance/withdraw.py` (pure parsing)
- Modify: `codee/config/config.py` (`load_binance_networks`)
- Test: `codee/tests/test_binance_withdraw.py`

- [ ] **Step 1: Create the network map config**

`codee/config/binance_networks.json` (Binance network code → DefiLlama chain name):
```json
{
  "ETH": "Ethereum",
  "ARBITRUM": "Arbitrum",
  "OPTIMISM": "OP Mainnet",
  "MATIC": "Polygon",
  "BSC": "BSC",
  "BASE": "Base",
  "AVAXC": "Avalanche",
  "ZKSYNCERA": "zkSync Era",
  "LINEA": "Linea",
  "SCROLL": "Scroll",
  "MANTLE": "Mantle",
  "CELO": "Celo",
  "SONIC": "Sonic",
  "OPBNB": "op_bnb"
}
```

- [ ] **Step 2: Add the loader**

In `codee/config/config.py`:
```python
def load_binance_networks() -> dict:
    return _load_json("binance_networks.json")
```

- [ ] **Step 3: Write the failing test**

`codee/tests/test_binance_withdraw.py`:
```python
from codee.sources.binance.withdraw import build_withdrawable_chains

NETMAP = {"ETH": "Ethereum", "ARBITRUM": "Arbitrum", "BSC": "BSC"}
CLASSES = ["USDC", "USDT", "ETH", "BTC"]

def _coin(coin, nets):
    return {"coin": coin, "networkList": [{"network": n, "withdrawEnable": en} for n, en in nets]}

def test_build_maps_withdrawable_networks_to_chains():
    raw = [
        _coin("USDC", [("ETH", True), ("ARBITRUM", True), ("BSC", False)]),
        _coin("ETH",  [("ETH", True), ("ARBITRUM", True)]),
        _coin("DOGE", [("BSC", True)]),          # not a class -> ignored
    ]
    out = build_withdrawable_chains(raw, NETMAP, CLASSES)
    assert out["USDC"] == {"Ethereum", "Arbitrum"}   # BSC excluded (withdrawEnable False)
    assert out["ETH"] == {"Ethereum", "Arbitrum"}
    assert out["USDT"] == set() and out["BTC"] == set()

def test_build_ignores_unmapped_network_codes():
    raw = [_coin("USDC", [("ETH", True), ("FANTOM", True)])]   # FANTOM not in NETMAP
    out = build_withdrawable_chains(raw, NETMAP, CLASSES)
    assert out["USDC"] == {"Ethereum"}

def test_build_empty_on_empty_input():
    assert build_withdrawable_chains([], NETMAP, CLASSES) == {"USDC": set(), "USDT": set(), "ETH": set(), "BTC": set()}
```

- [ ] **Step 4: Run it — expect FAIL**

Run: `PYTHONIOENCODING=utf-8 .venv\Scripts\pytest codee/tests/test_binance_withdraw.py -v`
Expected: FAIL — module `codee.sources.binance.withdraw` doesn't exist.

- [ ] **Step 5: Implement the pure builder**

Create `codee/sources/binance/__init__.py` (empty). Create `codee/sources/binance/withdraw.py`:
```python
"""Pure parsing of Binance capital/config into a {class: {chain}} withdrawable map.
No I/O — the signed fetch lives in client.py; this is testable offline."""


def build_withdrawable_chains(coin_list: list[dict], network_map: dict, classes: list[str]) -> dict[str, set]:
    """coin_list: raw /sapi/v1/capital/config/getall entries.
    network_map: Binance network code -> DefiLlama chain name.
    classes: the starting-capital classes (Binance base-coin symbols USDC/USDT/ETH/BTC).
    Returns {class: set(withdrawable DefiLlama chains)}; unmapped codes & withdraw-disabled
    networks are skipped; coins not in `classes` are ignored."""
    out: dict[str, set] = {c: set() for c in classes}
    wanted = set(classes)
    for c in coin_list:
        coin = c.get("coin")
        if coin not in wanted:
            continue
        for net in (c.get("networkList") or []):
            if not net.get("withdrawEnable"):
                continue
            chain = network_map.get(net.get("network"))
            if chain:
                out[coin].add(chain)
    return out
```

- [ ] **Step 6: Run it — expect PASS**

Run: `PYTHONIOENCODING=utf-8 .venv\Scripts\pytest codee/tests/test_binance_withdraw.py -v`
Expected: PASS.

- [ ] **Step 7: Commit**
```bash
git add codee/config/binance_networks.json codee/config/config.py codee/sources/binance/__init__.py codee/sources/binance/withdraw.py codee/tests/test_binance_withdraw.py
git commit -m "T3b: binance network->chain map + pure build_withdrawable_chains"
```

---

### Task B2: Binance signed client (reads BI_API_KEY/SECRET from env)

**Files:**
- Create: `codee/sources/binance/client.py`
- Test: `codee/tests/test_binance_client.py`

- [ ] **Step 1: Write the failing test** (no network — assert signing + no-creds no-op)

`codee/tests/test_binance_client.py`:
```python
import pytest
from codee.sources.binance.client import BinanceClient


async def test_fetch_returns_empty_without_credentials():
    c = BinanceClient(api_key="", api_secret="")
    async with c:
        assert await c.fetch_capital_config() == []


def test_sign_appends_hmac_signature():
    c = BinanceClient(api_key="k", api_secret="secret")
    signed = c._sign({"timestamp": 1, "recvWindow": 5000})
    assert "signature=" in signed
    assert signed.startswith("timestamp=1&recvWindow=5000")
    # deterministic HMAC-SHA256 of the query under key 'secret'
    import hmac, hashlib
    expect = hmac.new(b"secret", b"timestamp=1&recvWindow=5000", hashlib.sha256).hexdigest()
    assert signed.endswith("&signature=" + expect)
```

- [ ] **Step 2: Run it — expect FAIL**

Run: `PYTHONIOENCODING=utf-8 .venv\Scripts\pytest codee/tests/test_binance_client.py -v`
Expected: FAIL — module doesn't exist.

- [ ] **Step 3: Implement the client**

`codee/sources/binance/client.py`:
```python
"""Binance signed client for /sapi/v1/capital/config/getall (withdraw networks per coin).
Credentials come from BI_API_KEY / BI_API_SECRET in the environment — the SAME vars
Volume_tracker uses. Codee does not import VT code; it only reads the shared env. With no
creds, fetch_capital_config() returns [] so the gate degrades gracefully."""
import hashlib
import hmac
import os
import time
from urllib.parse import urlencode

import aiohttp

BASE_URL = "https://api.binance.com"
CONFIG_PATH = "/sapi/v1/capital/config/getall"
DEFAULT_TIMEOUT = aiohttp.ClientTimeout(total=20)


class BinanceClient:
    def __init__(self, api_key: str | None = None, api_secret: str | None = None,
                 session: aiohttp.ClientSession | None = None):
        self.api_key = os.getenv("BI_API_KEY", "") if api_key is None else api_key
        self.api_secret = os.getenv("BI_API_SECRET", "") if api_secret is None else api_secret
        self._session = session
        self._owns_session = session is None

    async def __aenter__(self):
        if self._session is None:
            self._session = aiohttp.ClientSession(timeout=DEFAULT_TIMEOUT)
        return self

    async def __aexit__(self, exc_type, exc, tb):
        if self._owns_session and self._session is not None:
            await self._session.close()
            self._session = None

    def _sign(self, params: dict) -> str:
        qs = urlencode(params)
        sig = hmac.new(self.api_secret.encode(), qs.encode(), hashlib.sha256).hexdigest()
        return f"{qs}&signature={sig}"

    async def fetch_capital_config(self) -> list[dict]:
        """Raw coin list from capital/config/getall; [] if no creds or on error shape."""
        if not self.api_key or not self.api_secret:
            return []
        assert self._session is not None, "use as async context manager"
        query = self._sign({"timestamp": int(time.time() * 1000), "recvWindow": 5000})
        url = f"{BASE_URL}{CONFIG_PATH}?{query}"
        async with self._session.get(url, headers={"X-MBX-APIKEY": self.api_key}) as resp:
            resp.raise_for_status()
            data = await resp.json()
            return data if isinstance(data, list) else []
```

- [ ] **Step 4: Run it — expect PASS**

Run: `PYTHONIOENCODING=utf-8 .venv\Scripts\pytest codee/tests/test_binance_client.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**
```bash
git add codee/sources/binance/client.py codee/tests/test_binance_client.py
git commit -m "T3b: Binance signed client for capital/config (env creds, no-op without keys)"
```

---

### Task B3: Ingestor fetches the withdraw map each tick → JSON cache

**Files:**
- Modify: `codee/services/pools/ingestor.py` (`run_once`; constructor)
- Test: `codee/tests/test_pools_ingestor.py`

- [ ] **Step 1: Write the failing test**

Append to `codee/tests/test_pools_ingestor.py` (top-of-file imports already include json/pathlib? add if missing):
```python
class StubBinance:
    def __init__(self, coins): self.coins = coins
    async def __aenter__(self): return self
    async def __aexit__(self, *a): pass
    async def fetch_capital_config(self): return self.coins


async def test_ingestor_writes_binance_withdraw_cache(db, tmp_path, monkeypatch):
    """Each tick fetches capital/config and writes data/binance_withdraw.json (class->chains)."""
    import json as _json
    from codee.config.config import settings
    cache = tmp_path / "binance_withdraw.json"
    monkeypatch.setattr(settings, "BINANCE_WITHDRAW_CACHE", str(cache), raising=False)
    supply = [_supply_pool("e1", "Arbitrum", "aave-v3", "WETH", tvl=5_000_000)]
    borrow = [_borrow_pool("e1")]
    coins = [{"coin": "ETH", "networkList": [{"network": "ARBITRUM", "withdrawEnable": True}]}]
    ing = PoolsIngestor(db, StubDefiLlama(supply, borrow), StubMerkl([]), binance=StubBinance(coins))
    await ing.run_once(ts=1716800000)
    saved = _json.loads(cache.read_text())
    assert "Arbitrum" in saved["ETH"]
```

- [ ] **Step 2: Run it — expect FAIL**

Run: `PYTHONIOENCODING=utf-8 .venv\Scripts\pytest codee/tests/test_pools_ingestor.py::test_ingestor_writes_binance_withdraw_cache -v`
Expected: FAIL — `PoolsIngestor.__init__` has no `binance` param / no cache write.

- [ ] **Step 3: Add the cache path setting**

In `codee/config/config.py` `Settings`, add a field:
```python
    BINANCE_WITHDRAW_CACHE: str = str(CONFIG_DIR.parent / "data" / "binance_withdraw.json")
```

- [ ] **Step 4: Wire the Binance fetch into the ingestor**

In `codee/services/pools/ingestor.py`:
- imports:
```python
import json
from pathlib import Path
from codee.config.config import load_binance_networks, load_asset_classes
from codee.sources.binance.client import BinanceClient
from codee.sources.binance.withdraw import build_withdrawable_chains
```
- constructor:
```python
    def __init__(self, db: SqliteClient, defillama=None, merkl=None, binance=None):
        self.db = db
        self._defillama = defillama
        self._merkl = merkl
        self._binance = binance
```
- in `run_once`, after the DefiLlama/Merkl gather block, add a guarded Binance fetch + cache write (non-fatal, like strategy_history):
```python
        try:
            binance = self._binance or BinanceClient()
            async with binance:
                coins = await binance.fetch_capital_config()
            wmap = build_withdrawable_chains(coins, load_binance_networks(), list(load_asset_classes().keys()))
            cache_path = Path(settings.BINANCE_WITHDRAW_CACHE)
            cache_path.parent.mkdir(parents=True, exist_ok=True)
            cache_path.write_text(json.dumps({k: sorted(v) for k, v in wmap.items()}))
        except Exception:
            log.exception("[Ingestor] binance withdraw-map fetch failed (non-fatal)")
```
(Place it before the `return n`. JSON-serializes sets as sorted lists.)

- [ ] **Step 5: Run it — expect PASS**

Run: `PYTHONIOENCODING=utf-8 .venv\Scripts\pytest codee/tests/test_pools_ingestor.py -v`
Expected: PASS.

- [ ] **Step 6: Commit**
```bash
git add codee/config/config.py codee/services/pools/ingestor.py codee/tests/test_pools_ingestor.py
git commit -m "T3b: ingestor fetches Binance withdraw map each tick -> JSON cache"
```

---

### Task B4: Router computes `binance_withdrawable` per route

**Files:**
- Modify: `codee/services/api/models.py` (3 route models)
- Modify: `codee/services/api/router.py` (load cache + per-route gate)
- Test: `codee/tests/test_api.py`

- [ ] **Step 1: Write the failing test**

Append to `codee/tests/test_api.py`:
```python
async def test_passive_route_binance_withdrawable_flag(app, tmp_path, monkeypatch):
    app_, db = app
    import time, json as _json
    from codee.config.config import settings
    cache = tmp_path / "bw.json"
    cache.write_text(_json.dumps({"ETH": ["Arbitrum"], "USDC": [], "USDT": [], "BTC": []}))
    monkeypatch.setattr(settings, "BINANCE_WITHDRAW_CACHE", str(cache), raising=False)
    now = int(time.time())
    await db.execute("""INSERT INTO pools_snapshot (pool_id,chain,project,symbol,tvl_usd,supply_apy_base,updated_at)
                        VALUES ('e1','Arbitrum','aave-v3','WETH',5e6,2.0,?)""", (now,))
    await db.execute("""INSERT INTO pools_snapshot (pool_id,chain,project,symbol,tvl_usd,supply_apy_base,updated_at)
                        VALUES ('e2','Sonic','aave-v3','WETH',5e6,2.0,?)""", (now,))
    await db.execute("""INSERT INTO pools_snapshot (pool_id,chain,project,symbol,tvl_usd,supply_apy_base,updated_at)
                        VALUES ('d1','BSC','aave-v3','DAI',5e6,3.0,?)""", (now,))
    transport = ASGITransport(app=app_)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        body = (await ac.get("/api/codee/routes/passive")).json()
    eth_arb = next(r for r in body if r["chain"] == "Arbitrum" and r["symbol"] == "WETH")
    eth_sonic = next(r for r in body if r["chain"] == "Sonic" and r["symbol"] == "WETH")
    dai = next(r for r in body if r["symbol"] == "DAI")
    assert eth_arb["binance_withdrawable"] is True     # ETH withdrawable to Arbitrum
    assert eth_sonic["binance_withdrawable"] is False  # ETH not withdrawable to Sonic
    assert dai["binance_withdrawable"] is None         # DAI is not a class
```

- [ ] **Step 2: Run it — expect FAIL**

Run: `PYTHONIOENCODING=utf-8 .venv\Scripts\pytest codee/tests/test_api.py::test_passive_route_binance_withdrawable_flag -v`
Expected: FAIL — no `binance_withdrawable` field.

- [ ] **Step 3: Add the model field**

In `codee/services/api/models.py`, add to all three route models (last field):
```python
    binance_withdrawable: bool | None = None
```

- [ ] **Step 4: Load the cache + compute the gate in the router**

In `codee/services/api/router.py`, add:
```python
import json
from pathlib import Path

def _load_withdraw_map() -> dict[str, set]:
    """Read the Binance withdraw cache (class -> set(chains)). Empty if absent/unreadable."""
    try:
        raw = json.loads(Path(settings.BINANCE_WITHDRAW_CACHE).read_text())
        return {k: set(v) for k, v in raw.items()}
    except Exception:
        return {}

def _withdrawable(classes: list[str], chain: str, wmap: dict[str, set]) -> bool | None:
    """True/False if any class can/can't reach `chain`; None when no class or empty map."""
    if not classes or not wmap:
        return None
    return any(chain in wmap.get(c, set()) for c in classes)
```
Then in each route endpoint, load `wmap = _load_withdraw_map()` once and set:
- passive: `binance_withdrawable=_withdrawable(_classes(r.symbol), r.chain, wmap)`
- crosschain: `binance_withdrawable=_withdrawable(_classes(r.symbol), r.supply_chain, wmap)`
- loops: `binance_withdrawable=_withdrawable(_classes(r.asset_x, r.asset_y), r.chain, wmap)`

- [ ] **Step 5: Run it — expect PASS**

Run: `PYTHONIOENCODING=utf-8 .venv\Scripts\pytest codee/tests/test_api.py -v`
Expected: PASS.

- [ ] **Step 6: Commit**
```bash
git add codee/services/api/models.py codee/services/api/router.py codee/tests/test_api.py
git commit -m "T3b: router computes binance_withdrawable per route from withdraw cache"
```

---

### Task B5: Frontend — "Binance-withdrawable only" toggle + marker

**Files:**
- Modify: `Volume_tracker/web/index.html` (filter row + JS)

- [ ] **Step 1: Add the toggle HTML**

In `#codeeLiqFilter`, after the capital `<select>`, add:
```html
            <label style="display:none;align-items:center;gap:4px;cursor:pointer;" id="codeeWdrawWrap">
              <input type="checkbox" id="codeeWdrawOnly" style="accent-color:var(--accent);"> Binance-withdrawable only
            </label>
```

- [ ] **Step 2: State + filter + marker**

Add state near `let codeeCapital = '';`:
```javascript
  let codeeWdrawOnly = false;
```
In `renderCodeeTable`, after the capital filter, add:
```javascript
    if (codeeWdrawOnly) {
      rows = rows.filter((d) => d.binance_withdrawable !== false);  // keep true + unknown(null)
    }
```

- [ ] **Step 3: Wire the toggle + couple it to the capital selector**

In `codeeInit`, after the capital-select wiring:
```javascript
    const wdrawWrap = document.getElementById('codeeWdrawWrap');
    const wdrawOnly = document.getElementById('codeeWdrawOnly');
    wdrawOnly.addEventListener('change', () => {
      codeeWdrawOnly = wdrawOnly.checked;
      if (codeeLastData && activeTab !== 'rewards' && activeTab !== 'history') {
        renderCodeeTable(activeTab, codeeLastData);
      }
    });
```
Extend the capital `change` handler so picking a class defaults the toggle ON and reveals it:
```javascript
      wdrawWrap.style.display = codeeCapital ? 'inline-flex' : 'none';
      wdrawOnly.checked = !!codeeCapital;
      codeeWdrawOnly = wdrawOnly.checked;
```
(place these inside the existing `capSel.addEventListener('change', …)` before the re-render call.)

- [ ] **Step 4: Verify via harness**

Run: `PYTHONIOENCODING=utf-8 .venv\Scripts\python -m codee.scripts.local_harness`
Codee tab: pick **USDC** → the toggle appears, checked by default; rows with `binance_withdrawable === false` are hidden; unchecking shows them. Pick **All** → toggle hides. (Requires `BI_API_KEY`/`BI_API_SECRET` in the local env for a real map; without them the map is empty → all flags `null` → nothing hidden, which is the correct graceful-degrade. Note this in the commit if creds aren't local.) Stop the harness.

- [ ] **Step 5: Commit**
```bash
git add web/index.html
git commit -m "T3b: 'Binance-withdrawable only' toggle + default-on when a capital class is picked"
```

---

### Task C1: Mirror backend to AAVE_STRAT

**Files (in `F:\codefee\AAVE_STRAT`):** the same backend changes from Tasks A1–A3, B1–B4 (NOT the frontend A4/B5). Bare imports (`from config.config import …`, `from sources.binance…`) — no `codee.` prefix.

- [ ] **Step 1:** Apply the identical edits to `config/config.py`, `config/asset_classes.json`, `config/binance_networks.json`, `services/pools/ingestor.py`, `services/api/models.py`, `services/api/router.py`, `sources/binance/{__init__,withdraw,client}.py`, and the matching test files under `tests/`. Adjust import prefixes only.
- [ ] **Step 2:** Run `PYTHONIOENCODING=utf-8 .venv\Scripts\pytest -q` from `F:\codefee\AAVE_STRAT`. Expected: all pass.
- [ ] **Step 3:** Commit:
```bash
git add config services sources tests
git commit -m "T3 (mirror): starting-capital classes + universe + Binance withdraw gate (backend)"
```

---

### Task C2: Deploy (gated on explicit user approval)

> Backend `.py` + new config files changed → **`systemctl restart` required**. The server env
> must have `BI_API_KEY`/`BI_API_SECRET` (already set for VT — verify with a no-secret check).
> Do NOT deploy without the user's explicit go-ahead for this production push.

- [ ] **Step 1:** Confirm clean tree + full suites green in both repos.
- [ ] **Step 2:** Merge branch → `main` (VT) and `master` (AAVE_STRAT); push AAVE_STRAT.
- [ ] **Step 3:** Verify the server env has the Binance keys (a deploy-time check that doesn't print them, e.g. `test -n "$BI_API_KEY" && echo set`). If absent, the gate degrades to `null` (no rows hidden) — acceptable, but note it.
- [ ] **Step 4:** git-bundle ff from the server HEAD → new HEAD; SFTP; `git fetch` + `git merge --ff-only`; `systemctl restart bigdeposits`.
- [ ] **Step 5:** Verify: service active, `[Codee] initialized`, `/api/codee/health` 200, `/api/orders` 200, `/api/codee/routes/passive` includes `entry_asset_classes` + `binance_withdrawable`, `data/binance_withdraw.json` written (non-empty if keys present), dashboard serves `codeeCapitalSelect`.

---

## Self-review notes

- **Spec coverage:** asset classes (A1), universe (A2), entry classes/anchor (A3+A4), Binance source (B1+B2), per-tick cache (B3), gate flag (B4), toggle+marker+volatile note (A4+B5), repo mirror (C1), deploy (C2). All spec sections mapped.
- **Refinement:** `entry_asset_classes: list[str]` replaces the spec's singular `entry_asset_class` (uniform, handles loops' two legs). Noted in header.
- **Type consistency:** `asset_class()→str|None`, `_classes(*syms)→list[str]`, `build_withdrawable_chains→dict[str,set]`, `_withdrawable→bool|None`, model fields `entry_asset_classes: list[str]` + `binance_withdrawable: bool|None` — consistent across tasks.
- **Purity:** `analyzer.py` untouched; the gate is computed in router/ingestor (which hold the Binance map). `withdraw.py` is pure; `client.py` isolates I/O.
- **Offline tests:** Binance covered by `StubBinance` + a synthetic coin list; no network in the suite. `PYTHONIOENCODING=utf-8` flagged for the ₮ fixtures.
- **Golden test:** unaffected (hardcoded stablecoin + $1M subset).
