# Codee — Phase 1: Design (Data + Dashboard)

**Date:** 2026-05-27
**Author:** Alexandre (Codee) + Claude
**Status:** Spec approved in brainstorming, pending final review before implementation plan
**Project:** `F:\codefee\AAVE_STRAT` (separate from Volume_tracker; future integration optional)

---

## 1. Purpose

Codee is a DeFi yield bot/dashboard. **Phase 1 delivers the data foundation:** it pulls lending rates from DefiLlama on a fixed cadence, computes spreads and routes (passive supply + leveraged loops), persists history, and exposes everything via a REST API consumed by a dashboard.

Phase 1 **does not execute transactions** — it is the intelligence layer that informs capital decisions. On-chain execution, Binance, and alerts are Phases 2-3.

---

## 2. Critical finding that shaped this design (reality check 2026-05-25)

Before finalizing the design, we ran `demo_routes.py` against the live DefiLlama API. The result refutes the central thesis of the context document (`codee_strategy_context.md`):

| Metric | Context (Apr/2026 snapshot) | Live (2026-05-25) |
|---|---|---|
| BSC Venus USDT supply | 8.0% (with XVS rewards) | **2.00% (apyReward = 0)** |
| BSC structural spread | ~5% | **negative (−1.86%)** |
| Global pools with `apyReward > 0` | (many, implied) | **134 of 4,134 (3.2%)** |
| Loops with positive spread | "always BSC/Base" | **2, both on Ethereum** |
| Best opportunity today | leveraged loop ~25% | **passive supply 17.9% (Base yearn USDC)** |

**Conclusions that became requirements:**

1. **Passive supply > leveraged loops in the current market** (17.9% vs 7.3% on the best loop). The context's Strategy 1 (BSC ping-pong) currently **loses money** (−3.27% net APY) *on DefiLlama's base-only numbers*.
2. **The "rewards paused" reading was too strong — see Section 2b.** Live verification on 28-mai showed DefiLlama is *blind to reward APY*, so part of the "no positive loops" result is a data gap, not market reality. Rewards (XVS/Merit) still exist; DefiLlama just doesn't report them.
3. Codee needs to be **discovery-first** (where does spread exist, on any chain), not chain-anchored (ranking BSC).
4. **Detecting the return of the reward regime** is the primary function — `reward_active_pools` rising from 0 is the timing signal.

The context's framework (LAV buckets, loop math, risk ladder) remains valid. The context's **numbers** are illustrative, not current.

---

## 2b. Revisions from live validation + Paul review (28-mai-2026)

After the first draft, we generated a full snapshot (`export_snapshot.py`) and a domain expert (Paul) reviewed it against live protocol UIs. This surfaced findings that change the design. Each is a concrete requirement, not a note.

### A. DefiLlama is blind to rewards on BOTH sides (the big one)

DefiLlama's free API reports `apyReward = 0` and `apyRewardBorrow = 0` even when it has populated the `rewardTokens` array. Verified:
- **Venus USDT (BSC):** payload contains the XVS token address (`0xcf6b…626c63`) but `apyReward = 0`. The Venus UI shows ~5% (≈2% base + ≈3% XVS). We saw only the 2%.
- **Aave USDT borrow (all chains):** every chain shows `apyRewardBorrow = 0`. Paul sees 0–1% net borrow on the UI = base ~3% minus a Merit rebate DefiLlama doesn't count.
- **Whole protocols missing:** Sonic Market V3 ($18.45M) is not indexed; Kinza shows null rewards and wrong TVL ($0.2M).

**Consequence:** DefiLlama is a **discovery** source (which pools/chains exist, TVL, base rates, utilization) — **not** the source of truth for reward APY. The reward component is exactly the edge the strategy needs. A DefiLlama-only Phase 1 ships misleading numbers.

**Requirement:** for shortlisted pools, compute reward APY **on-chain**: `emission_rate × reward_token_price ÷ TVL`. Start with the highest-value protocols (Venus Comptroller `venusSpeeds`, Aave Merit), expand incrementally. This pulls protocol-specific integration forward from Phase 3 into Phase 1b. New field `reward_source ∈ {'defillama','onchain','none'}` so the dashboard flags base-only (understated) numbers.

### B. Utilization safety rules (from Paul, concrete thresholds)

The Sonic USDC 15% pool was at **99.7% utilization** — only ~$20k withdrawable of $3.54M. High APY there is the pool paying you to be trapped (exit-liquidity risk, context doc Part 5).

**Requirement:**
- Compute `available_liquidity = total_supply_usd − total_borrow_usd` and `utilization` per pool.
- Safety rule: **no-entry signal if UR > 92%; force-exit signal at UR ≥ 96%** (per-pool configurable defaults).
- `quality_flag` gains a `high_utilization` value; dashboard surfaces UR + available liquidity prominently.

### C. Exit-liquidity / time-to-exit discount (generalizes LAV)

Two illiquidity sources, same mechanism: (1) can you sell the reward token (XVS) without crashing it; (2) can you withdraw the position at all (utilization). Paul: if exit takes days, discount expected received value ~20%.

**Requirement:** make the discount a **function of (time-to-exit + sell-liquidity)**, not a fixed LAV bucket. Applies to both the reward token value and the principal's withdrawability.

### D. Delta-neutral cross-asset loops are valid (Paul corrected my flag)

Borrowing BTC and depositing the *same* BTC on another platform is **net-zero price exposure** — debt and collateral move together. So loops may legitimately include volatile assets when delta-neutral. My "directional BTC risk" flag was wrong for this structure.

**Residual risks that remain (must be modeled):** the two legs sit on different chains with **independent liquidation engines** — a fast BTC move can liquidate the debt leg before collateral is bridged over; bridge latency; collateral-factor mismatch leaves a small residual. **Leverage caps at ~2–3x** for volatile-collateral legs (collateral factor <100% + buffer).

**Requirement:** the loop analyzer must **not hard-reject** BTC/ETH legs. It supports delta-neutral cross-asset loops, tagged with their residual risks and a 2–3x leverage cap. (Pure-stable loops remain the default/safest.)

### E. Cross-chain routes are where the opportunity is

Our snapshot only enumerated same-chain loops. Paul's best examples are cross-chain (deposit on Sonic, borrow on a cheap chain; BTC moved across chains; "2 Aave chains with USDT borrow 0–1%, deposit 3–5% elsewhere").

**Decision:** full cross-chain route enumeration needs bridge cost + time modeling (and eventually Binance) → that stays **Phase 2**. But the **data model must not assume same-chain** — `analyzer` route objects carry per-leg chain, and the schema already stores per-pool chain. We avoid baking in a same-chain assumption we'd have to rip out.

### F. Per-platform reward-scheme documentation (LAV expansion)

Paul: "write out each platform's shitcoin scheme — how long to sell XVS, how often paid, withdrawal penalties." This **is** the LAV bucket work, made concrete.

**Requirement:** `config/projects.json` gains per-reward-token fields: `payout_frequency`, `lockup_vesting`, `sell_liquidity_score`, `withdrawal_penalty`. Document the big platforms first (Venus/XVS, Aave/Merit, the top BSC ones).

### G. Wider stablecoin set

Expanding the accepted stables from 6 to ~26 (added USDS, PYUSD, GHO, CRVUSD, RLUSD, AUSD, USDe, etc.) grew in-scope pools from 13 → 108. `config/stable_symbols.json` uses the wider set.

### Net effect on phasing

- **Phase 1a** (ships first): DefiLlama discovery + base rates + history + dashboard, with explicit "base only / likely understated" flags and the utilization safety rules. Honest about what it doesn't yet know.
- **Phase 1b**: on-chain reward reader for the top protocols (Venus, Aave Merit) → correct numbers. This is the difference between a misleading tool and a useful one.
- **Phase 2** (unchanged scope, reinforced priority): cross-chain routes, delta-neutral volatile loops, broader protocol coverage, Binance bridging.

---

## 3. Phase 1 scope

**Phase 1a (data + dashboard, base rates):** DefiLlama ingestion (2 endpoints), sanity validation incl. utilization safety rules, SQLite persistence with history, 7d/30d aggregates, passive + loop ranking, REST API, Streamlit dashboard, reward token prices + LAV classification. Dashboard flags base-only numbers as "likely understated" where DefiLlama reports no reward.

**Phase 1b (correct reward numbers):** on-chain reward APY reader for the top protocols (Venus Comptroller, Aave Merit) — `emission_rate × token_price ÷ TVL`. Adds `reward_source` per pool. This is what turns a misleading tool into a useful one (see Section 2b.A).

**Out of scope (future phases):**
- On-chain *execution* (supply/borrow/repay transactions) — Phase 3
- Cross-chain route enumeration + bridge cost/time modeling — Phase 2 (data model stays cross-chain-ready, see 2b.E)
- Delta-neutral volatile-collateral loops (BTC/ETH legs) — Phase 2 (analyzer won't hard-reject them, see 2b.D)
- Binance API / bridging — Phase 3
- Telegram/Slack alerts — Phase 2 (health endpoint already exposes the data)
- Sub-hour RPC polling — Phase 4
- Backtesting — Phase 4
- `liquidation_threshold`, `oracle_source`, `e_mode_enabled` (require deeper on-chain reads) — Phase 2/3

**Read-only on-chain reads ARE in Phase 1b** (reward emission rates). This is distinct from Phase 3 execution (signing transactions) — Phase 1b only *reads* contracts.

---

## 4. Stack

| Layer | Technology | Reason |
|---|---|---|
| Backend | Python 3.13 + FastAPI + APScheduler | DeFi/quant ecosystem; APScheduler for in-process cron |
| ORM/DB | SQLAlchemy + SQLite (aiosqlite) | Fast prototyping; abstraction to migrate to QuestDB later |
| Dashboard | Streamlit (now) → existing HTML dash (later) | Streamlit consumes the API; future migration only swaps the front-end |
| Tests | pytest + pytest-asyncio + httpx | TDD during implementation |

**Architectural decision:** the dashboard **never** accesses the DB directly — only `/api/codee/*`. This guarantees the Streamlit→HTML migration does not rewrite logic.

---

## 5. Architecture (3 layers + orchestration)

```
INGESTION   →   STORAGE + DERIVATION   →   PRESENTATION
(sources/)      (db/ + services/*/)        (api/ + web/)
```

- **Ingestion:** DefiLlama poller (60min), reward token prices (15min).
- **Storage + derivation:** SQLite via SQLAlchemy; sanity validation; 7d/30d aggregates.
- **Presentation:** FastAPI `/api/codee/*` (JSON); Streamlit consumes the API.

**Orchestration:** `main.py` runs `asyncio.gather` over all loops (Volume_tracker pattern). FastAPI runs in the same event loop via uvicorn.Server. Streamlit runs in a separate process.

### Folder structure

```
AAVE_STRAT/
├── main.py                          # asyncio.gather over all loops
├── requirements.txt / pyproject.toml
├── .env.example
├── config/
│   ├── config.py                    # Config class, reads .env
│   ├── chains.json                  # gas_per_tx, excluded flag, RPC url per chain
│   ├── stable_symbols.json          # wider stables set (~26, see 2b.G)
│   ├── lav_buckets.json             # token symbol -> A/B/C
│   └── projects.json                # project -> reward token + scheme fields (see 2b.F)
├── db/
│   ├── sqlite_client.py             # aiosqlite + SQLAlchemy async
│   ├── models.py                    # declarative tables
│   └── migrations/001_initial_schema.sql
├── sources/
│   ├── defillama/client.py          # /pools + /lendBorrow + /chart (DISCOVERY only)
│   ├── coingecko/client.py          # reward token prices
│   ├── dexscreener/client.py        # fallback prices
│   └── onchain/                     # [Phase 1b] reward emission readers (read-only)
│       ├── base.py                  # RewardReader protocol/interface
│       ├── venus.py                 # Comptroller venusSpeeds × XVS price ÷ TVL
│       └── aave_merit.py            # Merit rebate reader
├── services/
│   ├── pools/
│   │   ├── ingestor.py              # async run() 60min: fetch+JOIN+validate+persist
│   │   ├── validators.py            # sanity rules + utilization safety -> quality_flag
│   │   ├── aggregator.py            # 7d/30d rolling
│   │   └── snapshot.py              # upsert snapshot + insert history
│   ├── rewards/
│   │   ├── ingestor.py              # async run() 15min: prices
│   │   ├── onchain_apy.py           # [Phase 1b] reward APY via sources/onchain/
│   │   └── lav.py                   # bucket + discount = f(exit_time, sell_liquidity)
│   ├── routes/
│   │   └── analyzer.py              # PURE: effective rates, loops (cross-chain-ready), ranking
│   └── api/
│       ├── router.py                # FastAPI endpoints
│       └── models.py                # Pydantic response schemas
├── web/
│   └── dashboard.py                 # Streamlit
├── scripts/
│   ├── bootstrap_db.py              # schema + configs + triggers backfill
│   └── backfill_history.py          # /chart/{uuid} for 90d
└── tests/
    ├── fixtures/                    # captured DefiLlama payloads + onchain reads (offline)
    ├── test_defillama_client.py
    ├── test_validators.py           # incl. utilization thresholds
    ├── test_pools_ingestor.py
    ├── test_onchain_reward.py       # [Phase 1b] emission math vs known UI value
    ├── test_analyzer.py             # heart of the suite
    └── test_api.py
```

### Dependency direction (no cycles)

```
config → sources → services → api → web
                ↓
               db ←──────┘
```

- `sources/`: I/O only (HTTP + read-only RPC for `onchain/`). No DB, no config (injected). The `onchain/` readers only *read* contracts — no signing, distinct from Phase 3 execution.
- `services/pools` + `services/rewards`: use `sources/`, write to `db/`.
- `services/routes/analyzer.py`: **100% pure** — reads from `db/`, no I/O, no state. Testable without network.
- `services/api`: reads `db/` or calls `analyzer`. Returns JSON.
- `web/dashboard.py`: only consumes `/api/codee/*`.

Swapping SQLite→QuestDB touches only `db/`. Swapping Streamlit→HTML touches only `web/`.

---

## 6. Data flow

### Snapshot pipeline

```
[cron 60min] pools_ingestor.run()
  → GET /pools + GET /lendBorrow  (parallel via asyncio.gather)
  → JOIN by pool UUID
  → filters (TVL>=$1M, stable, chain not excluded)
  → VALIDATE (validators.py → quality_flag per pool)
  → snapshot.py: BEGIN; UPSERT pools_snapshot; INSERT pools_history; COMMIT
  → aggregator.py (chained): recompute rate_aggregates 7d/30d
```

### Cadence

| Loop | Cadence | Offset | Reason |
|---|---|---|---|
| pools_ingestor | 60 min | T=0 | DefiLlama refreshes hourly — faster = duplicate |
| rewards_ingestor | 15 min | T=2.5 | CoinGecko moves faster; reward≈0 today makes 15min generous |
| aggregator | on-trigger | post-ingest | 7d/30d rolling |

Configurable via `.env` (`SNAPSHOT_INTERVAL_MIN`). Tighten to 15/5 when rewards/loops return.

### Policy: "fail open, never lie"

Never serve synthetic/estimated data. On failure, serve the last good snapshot + timestamp. If snapshot > 3h old: dashboard shows a **red banner**, health goes `degraded`.

### Error handling

| Failure | Response |
|---|---|
| DefiLlama timeout/5xx | Skip tick, keep last good snapshot |
| Schema drift | Clear ValidationError, ingest what's parseable, flag in health |
| `/lendBorrow` fails, `/pools` ok | Persist supply only, borrow fields NULL |
| Pool disappears from feed | `status='inactive'` (no DELETE — preserves history) |
| CoinGecko 429 | Exponential backoff → DexScreener fallback |
| Unknown LAV bucket | Default bucket B (12.5%), flag `lav_uncertain=true` ("B?") |
| Data anomaly (validators) | `quality_flag` set, pool highlighted in dashboard, not dropped |

---

## 7. Database schema

**Central decision: store RAW rates, compute effective on-read.** `pools_snapshot`/`pools_history` store `supply_apy_base`/`supply_apy_reward` separately. The `effective_*` (with LAV) is computed in `analyzer.py` at request time. Reclassifying a token recomputes all history for free.

Full DDL in Appendix A.

**Tables:**
- `pools_snapshot` — current state, 1 row/pool, UPSERT. Includes `quality_flag` (now incl. `high_utilization`), `lav_uncertain`, `status`, `reward_source` (`'defillama'|'onchain'|'none'`, see 2b.A), `available_liquidity` (= supply − borrow, see 2b.B), and the `/lendBorrow` fields (`total_supply_usd`, `debt_ceiling_usd`, `borrowable`, `borrow_factor`, `underlying_tokens`).
- `pools_history` — append-only. PK `(pool_id, ts, source)` where `source ∈ {'live','chart_daily'}` lets daily backfill + live snapshots coexist.
- `reward_token_prices` — price + LAV classification, current + historical.
- `rate_aggregates` — 7d/30d rolling averages. **Exception to the raw rule**: stores effective (disposable, recomputed post-ingest and on LAV config change).

**Principle: capture every field the source gives at ingest, even if unused** — history cannot be backfilled retroactively.

**Retention:** no purge in Phase 1 (disk is cheap, long history is needed to detect regime change). Purge comes with the QuestDB migration.

---

## 8. Validation & testing

### Pyramid (inverted weight — math is where bugs cost money)

```
API tests (router)        ~15%
Integration (DB)          ~25%
Contract (sources)        ~20%
Unit: analyzer.py (math)  ~40%
```

**Absolute rule:** tests never touch the network. DefiLlama payloads captured once into `tests/fixtures/`, suite runs offline.

### Coverage by level

- **Unit `analyzer.py`** (target ≥95%): effective supply/borrow APY with LAV (buckets A/B/C); borrow floor at 0; **leverage formula pinned by test** (pin 5.46x for 0.855/10iter — resolves the 5.46 vs 6.60 discrepancy in the context); 4-leg loop enumeration; edge cases (negative spread doesn't crash, pool without borrow, reward 0).
- **Contract `defillama/client.py`**: parse fixtures; JOIN by UUID; schema drift.
- **Integration `ingestor`/`aggregator`** (SQLite tmpfile): idempotency (2x ingest → 1 snapshot, 2 history rows); inactive pool not deleted; recompute post-LAV-change.
- **API `router.py`** (TestClient): cold start → 503 `warming_up`; invalid param → 422; staleness flag.

### Additional validations (decided during brainstorm)

**Mandatory in Phase 1:**
1. **Data sanity layer** (`validators.py` + `quality_flag`): detects absurd supply APY (e.g. >1000%), TVL crash (>X% inter-snapshot drop), impossible utilization (>100%), invalid negative rates. Flags, **never drops silently**. Flagged pool appears highlighted in the dashboard.
2. **Utilization safety rules** (2b.B): flag `high_utilization` when UR > 92% (no-entry signal); UR ≥ 96% is a force-exit signal. Both per-pool configurable. `available_liquidity` surfaced in API + dashboard.
3. **Golden regression**: 2026-05-25 payload frozen as fixture; locks that the ranking produces the known numbers (17.9% passive, 7.3% loop). Catches math regressions.
4. **Join coverage assertion**: alerts if `join_rate` drops below ~50% of the historical norm (silent `/lendBorrow` breakage).
5. **[Phase 1b] On-chain reward sanity**: computed reward APY for a known pool (Venus USDT) must land within tolerance of the live UI value — guards the emission math.

**Recommended (Phase 1.5, documented):**
4. Property-based testing (hypothesis): `net_apy ≤ gross_apy`, `effective_borrow_apr ≥ 0`, leverage monotonic.
5. Cross-validate the 7d aggregate against `/chart`.
6. UTC/timestamp consistency (history monotonic, evenly spaced — guards against midnight-drift bugs).
7. Decimal vs float: float is fine in Phase 1; money math becomes Decimal in Phase 3.

---

## 9. Deploy & observability

### Dev (now — local Windows)

```
python -m venv .venv && .venv\Scripts\activate
pip install -r requirements.txt
copy .env.example .env
python scripts\bootstrap_db.py      # schema + 90d backfill
python main.py                      # terminal 1: scheduler + API
streamlit run web\dashboard.py      # terminal 2: dashboard
```

Two processes: restarting the dashboard (frequent while iterating on UI) doesn't kill ingestion. They talk only over HTTP.

### Production (future — once proven)

Volume_tracker pattern: server `199.247.3.163`, git bundle, systemd (`codee.service` + `codee-dashboard.service`). **Not Phase 1** — local Windows while we validate the thesis.

### Observability

- **Logging:** Python `logging` module (not `print`), readable style (`[Pools] ingested 4123, 234 in-scope, join_rate 87%`), console + rotating file.
- **Health endpoint** `GET /api/codee/health`: `status`, `last_snapshot_at`, `snapshot_age_s`, `stale`, `pool_count_total/in_scope`, `join_rate`, `lav_coverage_pct`, `quality_flags{}`, **`reward_active_pools`** (regime signal), `last_error`.

No APM/Prometheus in Phase 1 — health + logs suffice for 1 local user.

---

## 10. Daily operation

Dashboard with 4 tabs + regime cards at the top:
- **Top:** `reward_active_pools`, best passive, best loop, snapshot age, join_rate.
- **Tab 1 — Passive supply:** ranking by net APY, any chain.
- **Tab 2 — Loops:** positive spread only (today likely empty = valid signal).
- **Tab 3 — Reward health:** active programs, LAV coverage.
- **Tab 4 — History:** 7d/30d/90d evolution per pool.

Adjustable inputs: `principal` ($250k default), `hold_h` (7d default).

**Primary question Codee answers:** *"Did the regime change? Did rewards/spreads return enough to make leverage worthwhile — or is it still passive / do nothing?"* Until `reward_active_pools` rises from 0 and Tab 2 fills, Codee prevents running the context's Strategy 1 on autopilot.

---

## 11. Size estimate

Phase 1a ~2,000 lines of production + ~400 tests. Phase 1b adds ~400-600 (on-chain readers are protocol-specific; each adapter ~100-150 lines).

| Module | ~Lines |
|---|---|
| sources/defillama/client.py | 80 |
| sources/onchain/* (base + venus + aave_merit) [Phase 1b] | 400 |
| services/pools/* (ingestor, validators incl. UR rules, aggregator, snapshot) | 450 |
| services/rewards/* (prices, lav, onchain_apy [1b]) | 250 |
| services/routes/analyzer.py | 200 |
| services/api/* | 200 |
| db/* | 150 |
| web/dashboard.py | 300 |
| main.py | 80 |
| tests | 450 |

---

## 12. Open questions (resolve during implementation)

1. **Definitive leverage formula** — 5.46x (0.855/10iter, our calculation) vs 6.60x (context). Pinned in a test; confirm with strategist which is intended (does the buffer reduce per-iteration LTV, or is it a separate reserve?).
2. **Validator thresholds** — what % TVL crash triggers a flag? What APY is "absurd"? UR no-entry/exit defaults are 92%/96% (Paul) — confirm per-pool overrides. Calibrate with real data.
3. **`join_rate` baseline** — what is the historical norm for setting the alert? Measure in the first weeks.
4. **LAV classification of new tokens** — ember, bitway, avantis show up as "B?". Classify as we investigate each program (feeds the per-platform scheme doc, 2b.F).
5. **Reward token resolution** — DefiLlama's `rewardTokens` are addresses; mapping address → symbol → CoinGecko price requires a table. Define the source of truth.
6. **[Phase 1b] On-chain emission read per protocol** — each protocol exposes emission differently (Venus `venusSpeeds`, Aave Merit via its rewards controller / off-chain API). Confirm the read path + RPC provider per protocol. Which 2-3 protocols first? (Venus + Aave Merit are the highest value.)
7. **DefiLlama Pro** — does the paid tier actually report reward APY for Venus/Aave? If yes, it may be cheaper than maintaining on-chain readers. Verify before committing to either (don't assume Pro fixes an adapter gap).
8. **Cross-chain route model** — when Phase 2 enumerates cross-chain loops, the bridge cost + time + the exit-discount (2b.C) all feed net APY. Confirm the bridge cost source (Binance withdrawal fees table vs live).

---

## Appendix A — Full DDL

```sql
-- pools_snapshot — current state, 1 row per pool, UPSERT
CREATE TABLE pools_snapshot (
    pool_id           TEXT PRIMARY KEY,
    chain             TEXT NOT NULL,
    project           TEXT NOT NULL,
    symbol            TEXT NOT NULL,
    pool_meta         TEXT,
    tvl_usd           REAL NOT NULL,
    total_supply_usd  REAL,
    total_borrow_usd  REAL,
    available_liquidity REAL,                      -- supply - borrow (2b.B exit-liquidity)
    debt_ceiling_usd  REAL,
    utilization       REAL,
    supply_apy_base   REAL NOT NULL DEFAULT 0,
    supply_apy_reward REAL NOT NULL DEFAULT 0,
    reward_source     TEXT NOT NULL DEFAULT 'defillama',  -- 'defillama'|'onchain'|'none' (2b.A)
    borrow_apr_base   REAL,
    borrow_apr_reward REAL,
    ltv               REAL,
    borrow_factor     REAL,
    borrowable        INTEGER,
    reward_tokens     TEXT,
    underlying_tokens TEXT,
    lav_uncertain     INTEGER NOT NULL DEFAULT 0,
    quality_flag      TEXT NOT NULL DEFAULT 'ok',    -- 'ok'|'suspect_apy'|'tvl_crash'|'impossible_util'|'high_utilization'
    status            TEXT NOT NULL DEFAULT 'active',
    updated_at        INTEGER NOT NULL
);
CREATE INDEX idx_snapshot_chain    ON pools_snapshot(chain);
CREATE INDEX idx_snapshot_symbol   ON pools_snapshot(symbol);
CREATE INDEX idx_snapshot_util     ON pools_snapshot(utilization);
CREATE INDEX idx_snapshot_loopable ON pools_snapshot(chain, symbol) WHERE borrow_apr_base IS NOT NULL;

-- pools_history — append-only
CREATE TABLE pools_history (
    pool_id           TEXT NOT NULL,
    ts                INTEGER NOT NULL,
    source            TEXT NOT NULL,             -- 'live' | 'chart_daily'
    tvl_usd           REAL,
    total_supply_usd  REAL,
    total_borrow_usd  REAL,
    available_liquidity REAL,
    debt_ceiling_usd  REAL,
    supply_apy_base   REAL,
    supply_apy_reward REAL,
    reward_source     TEXT,                       -- which source produced supply_apy_reward
    borrow_apr_base   REAL,
    borrow_apr_reward REAL,
    utilization       REAL,
    quality_flag      TEXT NOT NULL DEFAULT 'ok',
    PRIMARY KEY (pool_id, ts, source)
);
CREATE INDEX idx_history_pool_ts ON pools_history(pool_id, ts);
CREATE INDEX idx_history_ts      ON pools_history(ts);

-- reward_token_prices
CREATE TABLE reward_token_prices (
    token_id         TEXT NOT NULL,
    symbol           TEXT NOT NULL,
    ts               INTEGER NOT NULL,
    price_usd        REAL NOT NULL,
    source           TEXT NOT NULL,              -- 'coingecko' | 'dexscreener'
    lav_bucket       TEXT,                        -- 'A'|'B'|'C'|NULL
    lav_discount_pct REAL NOT NULL DEFAULT 0.125,
    PRIMARY KEY (token_id, ts)
);
CREATE INDEX idx_prices_symbol_ts ON reward_token_prices(symbol, ts);

-- rate_aggregates — rolling averages (stores effective, recomputable)
CREATE TABLE rate_aggregates (
    pool_id                  TEXT NOT NULL,
    window                   TEXT NOT NULL,       -- '7d' | '30d'
    supply_apy_effective_avg REAL,
    borrow_apr_effective_avg REAL,
    utilization_avg          REAL,
    tvl_avg                  REAL,
    sample_count             INTEGER NOT NULL,
    computed_at              INTEGER NOT NULL,
    PRIMARY KEY (pool_id, window)
);
```

## Appendix B — API endpoints

```
GET /api/codee/health                                    -> system status
GET /api/codee/pools/snapshot                            -> current pools (paginated)
GET /api/codee/pools/{pool_id}/history?d=30              -> time series per pool
GET /api/codee/routes/passive?principal=&hold_h=         -> passive supply ranking
GET /api/codee/routes/loops?principal=&hold_h=           -> loop ranking (positive spread)
GET /api/codee/rewards/coverage                          -> classified tokens vs "B?"
GET /api/codee/chains/summary                            -> avg spread per chain (7d/30d)
```

## Appendix C — References

- `codee_strategy_context.md` — context/strategy document (framework valid, numbers stale)
- `demo_routes.py` — pipeline proof-of-concept (fetch→JOIN→filter→rank), validates the design
- DefiLlama API: `yields.llama.fi/pools` (supply), `yields.llama.fi/lendBorrow` (borrow), `yields.llama.fi/chart/{uuid}` (history)
