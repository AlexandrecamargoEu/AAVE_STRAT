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
2. **Rewards are genuinely low right now — see Section 2b.A.** A PoC against Venus's own API (28-mai) confirmed DefiLlama's `apyReward = 0` for Venus is *correct* (Venus pays 0 XVS on stables today). So "no positive loops" is mostly market reality, not a DefiLlama gap. The real coverage gaps are unindexed protocols (Sonic) and off-chain programs (Aave Merit, unverified).
3. Codee needs to be **discovery-first** (where does spread exist, on any chain), not chain-anchored (ranking BSC).
4. **Detecting the return of the reward regime** is the primary function — `reward_active_pools` rising from 0 is the timing signal.

The context's framework (LAV buckets, loop math, risk ladder) remains valid. The context's **numbers** are illustrative, not current.

---

## 2b. Revisions from live validation + Paul review (28-mai-2026)

After the first draft, we generated a full snapshot (`export_snapshot.py`) and a domain expert (Paul) reviewed it against live protocol UIs. This surfaced findings that change the design. Each is a concrete requirement, not a note.

### A. DefiLlama reward coverage — what's actually a gap (corrected by PoC 28-mai)

Initial read was "DefiLlama is blind to rewards because `rewardTokens` is populated but `apyReward = 0`." **A PoC against Venus's own API refuted that.** A populated `rewardTokens` list only means a reward token is *configured*, not that it's *currently emitted*.

What the PoC (`poc_venus_reward.py`, via `api.venus.io/markets/core-pool`) found:
- **Venus USDT (BSC):** `supplyApy = 2.06%`, `supplyXvsApy = 0`, `borrowApy = 3.92%`. Of all 48 core-pool markets, **only the XVS market itself pays any XVS** (0.84%). No stablecoin market pays XVS right now (`supplierDailyXvsMantissa = 0`). **So DefiLlama's `apyReward = 0` for Venus is CORRECT** — not a gap. The earlier "Venus pays ~3% XVS that DefiLlama hides" claim was an inference error.

So `apyReward = 0` can mean two different things, and we must distinguish them:
1. **The protocol genuinely pays no reward now** (Venus today) — DefiLlama is right.
2. **The protocol/reward isn't tracked by DefiLlama** — a real gap. Two sub-cases below.

The real, verified gaps:
- **DefiLlama misses BORROW-side incentives (the precise gap).** Cross-checked DefiLlama vs the **Merkl API** (`api.merkl.xyz/v4/opportunities`) on the same pool, Mantle aave-v3:
  | | Supply reward | Borrow rebate |
  |---|---|---|
  | Merkl (truth) | USDC +4.48% | USDC **−1.37%** |
  | DefiLlama | USDC +4.46% ✓ | **None** ✗ |
  DefiLlama gets supply rewards right (matches Merkl) but reports `apyRewardBorrow = None` even where Merkl pays a 1.37–1.75% borrow rebate. **This is exactly what makes loops look worse than reality:** each borrow leg is ~1.4% too expensive in our calc; a two-leg ping-pong understates spread by ~2.8% — enough to flip several "negative" loops positive. This confirms Paul's "Aave USDT borrow 0–1%" — it's base minus a Merkl rebate DefiLlama can't see.
- **Whole protocols not indexed:** Sonic Market V3 ($18.45M) is absent from DefiLlama (only tiny silo/aave pools on the Sonic chain). Confirmed.
- **Venus XVS is NOT a gap** — it's genuinely 0 now (above).

**Consequence (revised):** clean two-source architecture, both free APIs:
- **DefiLlama** → pool discovery, TVL, base rates, **supply** rewards, utilization.
- **Merkl** (`api.merkl.xyz/v4/opportunities?action=BORROW&status=LIVE`) → **borrow-side** incentives/rebates that DefiLlama misses. Match to pools by (chain, protocol, asset).
- **Protocol APIs** (e.g. Venus) → optional enrichment (richer per-pool fields, catch rewards when emissions return). Lower urgency.

**Requirement (revised):** Merkl borrow-rebate ingestion is a **Phase 1 source** (`sources/merkl/`), not optional — without it the loop spreads are systematically understated, which was the core "no positive loops" artifact. The on-chain emission reader is **dropped** from Phase 1 (Venus has nothing to read today; Merkl covers the Aave incentives via API). Keep `reward_source ∈ {'defillama','merkl','protocol_api','none'}`.

> Lessons logged: (1) never infer a hidden reward from a populated `rewardTokens` field — verify against the protocol/Merkl. (2) DefiLlama's blind spot is specifically the **borrow side**; supply rewards are fine. The two PoCs (Venus API + Merkl cross-check) cost an hour and turned a vague "DefiLlama is blind" into a precise, sourced, fixable gap.

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

**Decision:** full cross-chain route enumeration needs bridge cost + time modeling → **Phase 2**. The Phase 1a cross-chain *radar* (per-asset spread ceiling) goes in now. The **data model must not assume same-chain** — `analyzer` route objects carry per-leg chain, and the schema already stores per-pool chain. We avoid baking in a same-chain assumption we'd have to rip out.

**Bridge rules (Paul confirmed 28-mai):** the executability gate is **bridge cost ≤ $1**. Binance is the canonical bridge — withdraw to chain A, redeposit, withdraw to chain B — so the chains that matter for *executable* cross-chain are those Binance supports for the relevant stable. Chains without Binance withdrawal (or with bridge cost > $1) are visible in the radar as ceilings but flagged uneconomical. `config/chains.json` carries `bridge_cost_usd` per chain (sentinel ∞ for unsupported). When Phase 2 enumerates executable routes, this gate filters.

**Evidence (`demo_loops_with_merkl.py`, 28-mai):** overlaying Merkl borrow rebates onto same-chain loops improved spreads (best loop 7.33% → 9.33% gross APY) but flipped **0** loops positive — the big rebates land on chains (Mantle, Plasma, Cronos) with no same-chain partner pool. The **cross-chain carry ceiling** (max supply anywhere − min net-borrow anywhere, with Merkl) tells the real story: USDC **+13.2%** (Canto 13.5% supply / Cronos 0.28% borrow), USDT **+4.6%**, GHO **+5.2%**, USDE **+5.0%**. These are pre-bridge-cost, pre-LAV ceilings — but they confirm Paul's thesis: the live opportunity is cross-chain carry, not same-chain loops. Phase 1 same-chain ranking is the monitoring foundation; Phase 2 cross-chain is the product.

### F. Per-platform reward-scheme documentation (LAV expansion)

Paul: "write out each platform's shitcoin scheme — how long to sell XVS, how often paid, withdrawal penalties." This **is** the LAV bucket work, made concrete.

**Requirement:** `config/projects.json` gains per-reward-token fields: `payout_frequency`, `lockup_vesting`, `sell_liquidity_score`, `withdrawal_penalty`. Document the big platforms first (Venus/XVS, Aave/Merit, the top BSC ones).

### G. Wider stablecoin set

Expanding the accepted stables from 6 to ~26 (added USDS, PYUSD, GHO, CRVUSD, RLUSD, AUSD, USDe, etc.) grew in-scope pools from 13 → 108. `config/stable_symbols.json` uses the wider set.

### H. Leverage is per-pool, not a constant (Paul confirmed 28-mai)

My initial 5.46x (0.855 per iter × 10) was wrong as a global constant. Paul: *"each platform has a different LTV% per asset, which we'll need to discount 5% from"*.

**Rule:** for each pool, take the platform's actual LTV from DefiLlama's `/lendBorrow` (`ltv` field, or Venus API `collateralFactorMantissa`) and subtract 5% buffer to get the per-iteration effective LTV. Leverage for a same-chain ping-pong is bounded by the **lower** of the two platforms' effective LTVs (the binding constraint). E.g. Aave USDC LTV 0.75 + Venus USDT LTV 0.80 → loop binding LTV = 0.75 − 0.05 = 0.70 per iter → 10-iter leverage ≈ 3.50x. A different pair could give 5.5x. **The number is per-route, not a global.**

**Impact on `analyzer.py`:** the leverage function becomes `compute_leverage(eff_ltv: float, n_iter: int) -> float`. Pinned tests check the formula across multiple inputs (e.g. 0.85/10 ≈ 5.46x, 0.70/10 ≈ 3.50x), not a single number. Each route in the ranking shows its own leverage in the output.

Resolves open question #1 in Section 12.

### I. Chain/stable allow list — start permissive, exclude as we learn (Paul confirmed 28-mai)

Paul: *"don't exclude ETH L1 or Tron, both are relatively cheap chains now... start with all considered."* So:
- `config/chains.json` starts with **no blacklist** — every chain DefiLlama indexes is allowed in discovery. We add to the blacklist as we observe issues (untrusted contracts, bridge cost > $1, etc.).
- Per-chain field `bridge_cost_usd`: cost to move a stable on/off via Binance (Binance is the canonical bridge — see Paul's #1). Chains Binance doesn't support get a sentinel (e.g. ∞) so the cross-chain analyzer flags them uneconomical (gate: bridge cost ≤ $1 to consider for execution; the radar still shows them as ceilings).
- `config/stable_symbols.json` stays wide. Exclusions case-by-case after observing depeg/risk.

### J. High APY = needs_review, not suspect (Paul confirmed 28-mai)

Paul: *"sometimes APY does go to crazy levels temporarily so big % might be real. We need to check the >50% cases each time they come up."*

`validators.py` rule change: above 50% supply APY, flag `quality_flag = 'needs_review'`, **don't filter out**. Dashboard highlights these for manual inspection. The "suspect_apy" semantics (DefiLlama bug) only applies to clear nonsense (e.g. APY > 10,000% or impossible combinations like APY > 100% with utilization < 10%).

### Net effect on phasing

- **Phase 1a** (ships first): DefiLlama (discovery + base + supply rewards) **+ Merkl (borrow rebates)** + history + dashboard + utilization safety rules. With both sources, loop spreads are correct, not understated.
- **Phase 1b** (optional): protocol-API enrichment (Venus etc.) for richer per-pool fields + catching rewards when emissions return. Not on the critical path.
- **Phase 2** (unchanged scope, reinforced priority): cross-chain routes, delta-neutral volatile loops, broader protocol coverage, Binance bridging.

---

## 3. Phase 1 scope

**Phase 1a (data + dashboard):** DefiLlama ingestion (2 endpoints) **+ Merkl ingestion** for borrow-side rebates (see 2b.A — without it loop spreads are systematically understated), sanity validation incl. utilization safety rules, SQLite persistence with history, 7d/30d aggregates, passive + same-chain loop ranking, **cross-chain carry radar** (per-asset: best supply anywhere vs cheapest net-borrow anywhere, with Merkl — a ranking, no bridge modeling; labeled a pre-bridge-cost/pre-LAV ceiling), REST API, Streamlit dashboard, LAV classification (bucket-based). `reward_source` per pool shows provenance (`defillama`/`merkl`/`none`).

*Dropped from Phase 1a (was vestigial):* the CoinGecko/DexScreener reward-token **price feed** — it was load-bearing only under the abandoned "compute reward APY ourselves" plan. DefiLlama gives `apyReward` and Merkl gives the rebate APR directly, and the LAV discount is bucket-based (fixed %), so no live token price is needed in 1a. Moves to **Phase 2** (where the "reward token crashed >20%" alert needs it).

**Phase 1b (protocol-API enrichment — optional):** the Venus PoC (28-mai) showed DefiLlama's supply reward numbers are correct (Venus genuinely pays 0 XVS now), so no on-chain emission reader is needed. 1b is optional enrichment via protocol APIs (e.g. `api.venus.io`) for richer per-pool fields (live liquidity, collateral factor, liquidation threshold) and to catch rewards when emissions return. Can slide to the 1b/Phase-2 boundary.

**Out of scope (future phases):**
- On-chain *execution* (supply/borrow/repay transactions) — Phase 3
- Cross-chain route enumeration + bridge cost/time modeling — Phase 2 (data model stays cross-chain-ready, see 2b.E)
- Delta-neutral volatile-collateral loops (BTC/ETH legs) — Phase 2 (analyzer won't hard-reject them, see 2b.D)
- Binance API / bridging — Phase 3
- Telegram/Slack alerts — Phase 2 (health endpoint already exposes the data)
- Sub-hour RPC polling — Phase 4
- Backtesting — Phase 4
- `liquidation_threshold`, `oracle_source`, `e_mode_enabled` (require deeper on-chain reads or protocol APIs) — Phase 1b/2

**No on-chain reads in Phase 1** — both data sources (DefiLlama + Merkl) are free HTTP APIs. Protocol APIs (Phase 1b) are also HTTP. On-chain reads only appear if/when we add direct RPC in Phase 4.

---

## 4. Stack

| Layer | Technology | Reason |
|---|---|---|
| Backend | Python 3.13 + FastAPI + APScheduler | DeFi/quant ecosystem; APScheduler for in-process cron |
| ORM/DB | SQLAlchemy + SQLite (aiosqlite) | Fast prototyping; abstraction to migrate to QuestDB later |
| Dashboard | HTML/JS frontend, built via `frontend-design` skill, served as static by FastAPI | Polished UI from day 1 (no Streamlit interim step); consumes the same REST API; updated 28-mai on Alexandre's call |
| Tests | pytest + pytest-asyncio + httpx | TDD during implementation |

**Architectural decision:** the dashboard **never** accesses the DB directly — only `/api/codee/*`. Front-end is a static HTML/JS bundle in `web/` mounted by FastAPI; built by invoking the `frontend-design` skill with the brief in plan Task 18. No build pipeline (Phase 1a constraint — keep iteration cheap; can introduce one later if the UI grows).

---

## 5. Architecture (3 layers + orchestration)

```
INGESTION   →   STORAGE + DERIVATION   →   PRESENTATION
(sources/)      (db/ + services/*/)        (api/ + web/)
```

- **Ingestion:** single 60min poller fetching DefiLlama (discovery + base + supply rewards) and Merkl (borrow rebates) together. (No price feed in 1a — Phase 2.)
- **Storage + derivation:** SQLite via SQLAlchemy; sanity validation; 7d/30d aggregates.
- **Presentation:** FastAPI `/api/codee/*` (JSON) + static files served from `web/`. Front-end is HTML/JS produced by the `frontend-design` skill in plan Task 18.

**Orchestration:** `main.py` runs `asyncio.gather` over the ingestor and uvicorn (which serves both the API and the static `web/`). Single process — no separate dashboard process.

### Folder structure

```
AAVE_STRAT/
├── main.py                          # asyncio.gather over all loops
├── requirements.txt / pyproject.toml
├── .env.example
├── config/
│   ├── config.py                    # Config class, reads .env
│   ├── chains.json                  # gas_per_tx, bridge_cost_usd (Binance withdraw), excluded flag (default false — 2b.I)
│   ├── stable_symbols.json          # wider stables set (~26, see 2b.G)
│   ├── lav_buckets.json             # token symbol -> A/B/C
│   └── projects.json                # project -> reward token + scheme fields (see 2b.F)
├── db/
│   ├── sqlite_client.py             # aiosqlite + SQLAlchemy async
│   ├── models.py                    # declarative tables
│   └── migrations/001_initial_schema.sql
├── sources/
│   ├── defillama/client.py          # /pools + /lendBorrow + /chart (discovery, base, supply rewards)
│   ├── merkl/client.py              # /v4/opportunities — BORROW-side rebates DefiLlama misses (2b.A)
│   ├── coingecko/client.py          # [Phase 2] reward token prices (for crash alerts)
│   └── protocol_api/                # [Phase 1b, optional] richer per-pool enrichment
│       └── venus.py                 # api.venus.io: liquidity, collateral factor, liq threshold
├── services/
│   ├── pools/
│   │   ├── ingestor.py              # async run() 60min: fetch+JOIN+merkl-overlay+validate+persist
│   │   ├── validators.py            # sanity rules + utilization safety -> quality_flag
│   │   ├── aggregator.py            # 7d/30d rolling
│   │   └── snapshot.py              # upsert snapshot + insert history
│   ├── rewards/
│   │   ├── merkl_match.py           # match Merkl borrow rebates to pools by (chain,protocol,asset)
│   │   └── lav.py                   # bucket discount (fixed %); exit-discount = f(exit_time, liquidity)
│   ├── routes/
│   │   └── analyzer.py              # PURE: effective rates, same-chain loops, cross-chain carry radar, ranking
│   └── api/
│       ├── router.py                # FastAPI endpoints
│       └── models.py                # Pydantic response schemas
├── web/                             # static front-end produced by frontend-design skill (Task 18)
│   ├── index.html
│   ├── app.js                       # or main.js — name decided by the skill
│   └── styles.css                   # or Tailwind CDN; skill picks
├── scripts/
│   ├── bootstrap_db.py              # schema + configs + triggers backfill
│   └── backfill_history.py          # /chart/{uuid} for 90d
└── tests/
    ├── fixtures/                    # captured DefiLlama + Merkl payloads (offline)
    ├── test_defillama_client.py
    ├── test_merkl_match.py          # borrow rebate matched to right pool
    ├── test_validators.py           # incl. utilization thresholds
    ├── test_pools_ingestor.py
    ├── test_analyzer.py             # heart of the suite
    └── test_api.py
```

### Dependency direction (no cycles)

```
config → sources → services → api → web
                ↓
               db ←──────┘
```

- `sources/`: HTTP only (DefiLlama, Merkl, CoinGecko, protocol APIs). No DB, no config (injected). No contract signing anywhere in Phase 1.
- `services/pools` + `services/rewards`: use `sources/`, write to `db/`.
- `services/routes/analyzer.py`: **100% pure** — reads from `db/`, no I/O, no state. Testable without network.
- `services/api`: reads `db/` or calls `analyzer`. Returns JSON.
- `web/` (static HTML/JS): only consumes `/api/codee/*`.

Swapping SQLite→QuestDB touches only `db/`. The front-end is already HTML/JS — no future migration step.

---

## 6. Data flow

### Snapshot pipeline

```
[cron 60min] pools_ingestor.run()
  → GET defillama /pools + /lendBorrow + merkl /v4/opportunities  (parallel via asyncio.gather)
  → JOIN defillama supply+borrow by pool UUID
  → merkl_match: overlay borrow rebates onto matched pools (set borrow_apr_reward, reward_source='merkl')
  → filters (TVL>=$1M, stable, chain not explicitly excluded — default no exclusions per 2b.I)
  → VALIDATE (validators.py → quality_flag per pool, incl. high_utilization)
  → snapshot.py: BEGIN; UPSERT pools_snapshot; INSERT pools_history; COMMIT
  → aggregator.py (chained): recompute rate_aggregates 7d/30d
```

### Cadence

| Loop | Cadence | Offset | Reason |
|---|---|---|---|
| pools_ingestor (DefiLlama + Merkl) | 60 min | T=0 | DefiLlama refreshes hourly — faster = duplicate; Merkl fetched in the same tick |
| aggregator | on-trigger | post-ingest | 7d/30d rolling |

Single ingestion loop in Phase 1a (no separate price feed — dropped, see scope). Configurable via `.env` (`SNAPSHOT_INTERVAL_MIN`). Tighten when rewards/loops return. The Phase 2 reward-price feed (CoinGecko, 15 min) re-introduces a second loop.

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
- `pools_snapshot` — current state, 1 row/pool, UPSERT. Includes `quality_flag` (now incl. `high_utilization`), `lav_uncertain`, `status`, `reward_source` (`'defillama'|'merkl'|'protocol_api'|'none'`, see 2b.A), `borrow_apr_reward` now populated from Merkl where DefiLlama returns null, `available_liquidity` (= supply − borrow, see 2b.B), and the `/lendBorrow` fields (`total_supply_usd`, `debt_ceiling_usd`, `borrowable`, `borrow_factor`, `underlying_tokens`).
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

- **Unit `analyzer.py`** (target ≥95%): effective supply/borrow APY with LAV (buckets A/B/C); borrow floor at 0; **leverage formula tested across inputs** (per-pool from platform LTV − 5% buffer, 2b.H — e.g. 0.855/10 → 5.46x, 0.70/10 → 3.50x); 4-leg loop enumeration with binding LTV across the two legs; cross-chain carry ranking; edge cases (negative spread doesn't crash, pool without borrow, reward 0).
- **Contract `defillama/client.py`**: parse fixtures; JOIN by UUID; schema drift.
- **Integration `ingestor`/`aggregator`** (SQLite tmpfile): idempotency (2x ingest → 1 snapshot, 2 history rows); inactive pool not deleted; recompute post-LAV-change.
- **API `router.py`** (TestClient): cold start → 503 `warming_up`; invalid param → 422; staleness flag.

### Additional validations (decided during brainstorm)

**Mandatory in Phase 1:**
1. **Data sanity layer** (`validators.py` + `quality_flag`): detects clear nonsense (e.g. APY >10,000%, utilization >100%, invalid negative rates) → `quality_flag='impossible'`; flags **high-APY (>50%) as `needs_review`** (per Paul, 2b.J — high APY is often real, don't filter, surface); TVL crash (>X% inter-snapshot drop) → `tvl_crash`. **Never drops silently** — flagged pools highlighted in the dashboard for manual inspection.
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
                                    # dashboard at http://127.0.0.1:8000/  (served by FastAPI from web/)
```

Single process. Front-end edits don't require a backend restart — refresh the browser to pick up changes to `web/`.

### Production (future — once proven)

Volume_tracker pattern: server `199.247.3.163`, git bundle, systemd (`codee.service` + `codee-dashboard.service`). **Not Phase 1** — local Windows while we validate the thesis.

### Observability

- **Logging:** Python `logging` module (not `print`), readable style (`[Pools] ingested 4123, 234 in-scope, join_rate 87%`), console + rotating file.
- **Health endpoint** `GET /api/codee/health`: `status`, `last_snapshot_at`, `snapshot_age_s`, `stale`, `pool_count_total/in_scope`, `join_rate`, `lav_coverage_pct`, `quality_flags{}`, **`reward_active_pools`** (regime signal), `last_error`.

No APM/Prometheus in Phase 1 — health + logs suffice for 1 local user.

---

## 10. Daily operation

Dashboard with 5 tabs + regime cards at the top:
- **Top:** `reward_active_pools`, best passive, best cross-chain carry, snapshot age, join_rate.
- **Tab 1 — Passive supply:** ranking by net APY, any chain.
- **Tab 2 — Same-chain loops:** positive spread only (today likely empty = valid signal).
- **Tab 3 — Cross-chain carry:** per-asset best supply anywhere vs cheapest net-borrow anywhere (with Merkl). Labeled a pre-bridge-cost/pre-LAV ceiling — *the most valuable signal in the current regime* (USDC ~+13%, USDT ~+4.6% as of 28-mai). Each row shows the two chains + the caveat that executing it is Phase 2.
- **Tab 4 — Reward health:** active programs, LAV coverage, Merkl rebate coverage.
- **Tab 5 — History:** 7d/30d/90d evolution per pool.

Adjustable inputs: `principal` ($250k default), `hold_h` (7d default).

**Primary question Codee answers:** *"Did the regime change? Did rewards/spreads return enough to make leverage worthwhile — or is it still passive / do nothing?"* Until `reward_active_pools` rises from 0 and Tab 2 fills, Codee prevents running the context's Strategy 1 on autopilot.

---

## 11. Size estimate

Phase 1a ~2,100 lines of production + ~450 tests. Phase 1b (optional protocol-API enrichment) adds ~150 per protocol.

| Module | ~Lines |
|---|---|
| sources/defillama/client.py | 80 |
| sources/merkl/client.py | 80 |
| sources/protocol_api/* [Phase 1b, optional] | 150 |
| services/pools/* (ingestor, validators incl. UR rules, aggregator, snapshot) | 450 |
| services/rewards/* (prices, lav, merkl_match) | 250 |
| services/routes/analyzer.py | 200 |
| services/api/* | 200 |
| db/* | 150 |
| web/ (HTML/JS, built via frontend-design) | ~600 |
| main.py | 80 |
| tests | 450 |

---

## 12. Open questions (resolve during implementation)

1. **Leverage formula — RESOLVED (Paul 28-mai, see 2b.H):** per-pool, using each platform's LTV from DefiLlama minus 5% buffer; binding LTV = lower of the two legs.
2. **Validator thresholds** — TVL crash % and lower-bound for "obvious nonsense" APY (e.g. >10,000%). UR no-entry/exit defaults 92%/96% (Paul). High-APY (>50%) is `needs_review`, not filtered (Paul, 2b.J). Calibrate other thresholds with real data.
3. **`join_rate` baseline** — what is the historical norm for setting the alert? Measure in the first weeks.
4. **LAV classification of reward tokens** — research from each platform's own docs (payout cadence, vesting/lockup, withdrawal penalty are static facts published by the protocol). The **dynamic** part (sell liquidity / DEX depth) is deferred to Phase 2 when we wire DEX data; Phase 1a uses a conservative default for the liquidity component. *Not a Paul dependency — internal task.*
5. **Chain/stable allow list — RESOLVED (Paul 28-mai, see 2b.I):** start permissive, exclude case-by-case as we learn.
6. **Merkl ↔ DefiLlama pool matching** — Merkl identifies opportunities by (chainId, action, name/identifier); DefiLlama by pool UUID. Need a reliable match on (chain, protocol, asset, action). Some Merkl opps say "looping required" — confirm which ones map cleanly to a plain supply/borrow pool. (This is the one new integration risk Phase 1 carries.)
7. **Merkl reward token LAV** — Merkl borrow rebates are paid in tokens with their own liquidity/vesting. Apply the same LAV discount; classify the reward tokens Merkl uses (folds into #4).
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
    reward_source     TEXT NOT NULL DEFAULT 'defillama',  -- 'defillama'|'merkl'|'protocol_api'|'none' (2b.A)
    borrow_apr_base   REAL,
    borrow_apr_reward REAL,
    ltv               REAL,
    borrow_factor     REAL,
    borrowable        INTEGER,
    reward_tokens     TEXT,
    underlying_tokens TEXT,
    lav_uncertain     INTEGER NOT NULL DEFAULT 0,
    quality_flag      TEXT NOT NULL DEFAULT 'ok',    -- 'ok'|'needs_review'|'impossible'|'tvl_crash'|'high_utilization'
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

-- reward_token_prices  [Phase 2 — not populated in 1a; price feed dropped from 1a]
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
GET /api/codee/routes/loops?principal=&hold_h=           -> same-chain loop ranking (positive spread)
GET /api/codee/routes/crosschain?principal=&hold_h=      -> cross-chain carry radar (pre-bridge ceiling)
GET /api/codee/rewards/coverage                          -> classified tokens vs "B?", Merkl rebate coverage
GET /api/codee/chains/summary                            -> avg spread per chain (7d/30d)
```

## Appendix C — References

- `codee_strategy_context.md` — context/strategy document (framework valid, numbers stale)
- `demo_routes.py` — pipeline proof-of-concept (fetch→JOIN→filter→rank)
- `export_snapshot.py` — full shareable snapshot (all pools, spreads, loops, passive, rewards)
- `poc_venus_reward.py` — proved Venus XVS genuinely 0 (DefiLlama correct, 2b.A)
- `demo_loops_with_merkl.py` — Merkl borrow-rebate overlay + cross-chain carry ceiling (2b.A, 2b.E)
- DefiLlama API: `yields.llama.fi/pools` (supply), `yields.llama.fi/lendBorrow` (borrow), `yields.llama.fi/chart/{uuid}` (history)
- Merkl API: `api.merkl.xyz/v4/opportunities` (borrow-side incentives DefiLlama misses)
- Venus API: `api.venus.io/markets/core-pool` (per-market supply/borrow/XVS, liquidity, collateral factor)
