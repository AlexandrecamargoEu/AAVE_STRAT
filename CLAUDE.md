# CLAUDE.md — Codee

Context for any AI agent or developer working on this project. Loaded automatically by Claude Code.

---

## What this is

**Codee** is a DeFi yield bot. It finds inefficiencies in decentralized lending markets — places where you can supply a stablecoin for a high rate or borrow it cheaply — across many chains and protocols, and surfaces them so capital can be deployed to capture the spread.

**Current state: Phase 1a complete.** This is the *data + dashboard* foundation. It does NOT execute transactions — it's a radar that tells you *where* yield is and *when not* to act. Execution is manual for now (you copy a pool, go to the protocol UI, deposit). Automation is Phase 3.

The profit model, in one line: **DeFi lending is fragmented across ~20 chains, ~50 protocols, ~30 stablecoins, with incentive programs that turn on/off constantly. Nobody watches all of it manually. Codee is the radar that spots the mispricings; you (or later, the bot) capture them.**

Three capture strategies, simplest to most advanced:
1. **Passive supply** — just deposit on the highest-yielding safe pool.
2. **Same-chain loop** — leveraged ping-pong between two platforms on one chain (mostly dormant right now — see "Reality check" below).
3. **Cross-chain carry** — supply expensive on chain A, borrow cheap on chain B. Where the opportunity actually is today.

---

## How to run

```bash
# One-time setup
python -m venv .venv
.venv\Scripts\pip install -r requirements.txt
copy .env.example .env
.venv\Scripts\python scripts\bootstrap_db.py     # creates DB + first ingest (needs network)

# Run (single process: API + dashboard + 60-min ingestor loop)
.venv\Scripts\python main.py
# Dashboard:  http://127.0.0.1:8000/
# API:        http://127.0.0.1:8000/api/codee/*

# Tests (all offline, fixture-based)
.venv\Scripts\pytest

# Optional: backfill 90d history per pool (~4-8 min, needs network)
.venv\Scripts\python scripts\backfill_history.py
```

**Platform:** Windows. Use `.venv\Scripts\` (not `bin/`). Python 3.13.

---

## Architecture

Three layers, joined by a single `asyncio.gather` in `main.py`. Dependency direction is strict and cycle-free: `config → sources → services → api → web`.

```
INGESTION              STORAGE + DERIVATION         PRESENTATION
sources/               db/ + services/pools/        services/api/ + web/
  defillama/client.py    sqlite_client.py             router.py (FastAPI)
  merkl/client.py        models.py                    models.py (Pydantic)
                         ingestor.py  ◄── orchestrator index.html (dashboard)
services/rewards/        snapshot.py
  lav.py                 aggregator.py
  merkl_match.py       services/pools/validators.py
services/routes/
  analyzer.py  ◄── PURE math, no I/O, no state
```

**Key design rules (do not violate without reason):**
- `services/routes/analyzer.py` is **100% pure** — no I/O, no DB, no async, no state. All ranking math lives here so it's testable without network. Effective rates are computed on read from raw stored rates.
- **Store raw rates, compute effective on read.** `pools_snapshot`/`pools_history` keep `supply_apy_base` + `supply_apy_reward` separate. The LAV-discounted "effective" rate is computed in `analyzer.py` at query time — so reclassifying a reward token recomputes all history for free.
- The dashboard (`web/index.html`) **only consumes `/api/codee/*`** — never touches the DB. It's plain HTML/JS + Chart.js CDN, no build step.
- Sources are **HTTP-only**. No contract signing anywhere in Phase 1a.
- `pools_history` is append-only; pools that vanish from the feed get `status='inactive'`, never DELETE (preserves history).
- Single ingestion loop, 60 min cadence (matches DefiLlama's refresh — faster just duplicates).

---

## The critical findings (read before changing data logic)

These were discovered by validating against live data during the build. They shaped the whole design.

1. **DefiLlama needs TWO endpoints, joined by `pool` UUID.** `/pools` gives the supply side (`apyBase`, `apyReward`); `/lendBorrow` gives the borrow side (`apyBaseBorrow`, `ltv`, `totalSupplyUsd`). Neither alone is complete.

2. **DefiLlama is blind to BORROW-side incentives — use Merkl for those.** Cross-checked on Mantle aave-v3 USDC: DefiLlama reports the supply reward correctly (~4.46% ≈ Merkl's 4.48%) but reports `apyRewardBorrow=None` while Merkl pays a 1.37% borrow rebate. Each loop borrow leg is ~1.4% too expensive without Merkl → understates spread by ~2.8% per loop. `sources/merkl/` + `services/rewards/merkl_match.py` fill this gap.

3. **`apyReward=0` usually means the protocol genuinely pays 0 now — NOT that DefiLlama is hiding it.** A populated `rewardTokens` list only means a reward token is *configured*, not currently *emitted*. Verified via Venus's own API: Venus pays 0 XVS on stablecoins right now. **Never infer a hidden reward from the `rewardTokens` field — verify against the protocol's API.**

4. **Leverage is per-pool, not a constant.** Each platform has a different LTV per asset. `per_iter_ltv = platform_ltv - 0.05 buffer`; same-chain loop leverage uses the *lower* of the two legs' LTVs (binding constraint).

---

## Reality check (revisit every ~30 days)

As of the build (late May 2026), live data refuted the original strategy doc's central thesis:
- **Leveraged same-chain loops are mostly dead** — the XVS/Merit reward programs that made BSC Venus↔Aave spreads ~5% are paused/migrated. The "BSC ping-pong = default" rule of thumb is currently a *loss-making* trade.
- **Passive supply > loops today.** Best opportunities are cross-chain carry (e.g. USDT0 supply 17% on Hyperliquid vs borrow 2.4% on Mantle) and high passive yields (Dolomite USDC ~10%, etc.).
- The dashboard's **`reward_active_pools` card is the regime signal** — when it climbs from near-zero, incentive programs are returning and loops come back into play.

If you're answering a "should I deploy on chain X" question: **check live data, not the strategy doc.** The doc's framework (LAV buckets, loop math, risk tiers) is valid; its specific rate numbers are stale.

---

## Conventions

- **Quality flags** (`validators.py`, `QualityFlag` enum): `ok` | `needs_review` (APY > 50% — surface, don't filter) | `high_utilization` (UR > 92% — exit-liquidity risk) | `tvl_crash` (>50% inter-snapshot drop) | `impossible` (>10,000% APY, UR > 100%, negative — clear nonsense). Severity: impossible > tvl_crash > high_utilization > needs_review > ok. **Never silently drop a pool — flag and surface it.**
- **No chain blacklist by default** (Paul's call) — ETH L1 and Tron are NOT excluded; start permissive, exclude case-by-case in `config/chains.json`.
- **LAV buckets** (`config/lav_buckets.json`): A=0% discount (liquid: AAVE/COMP/...), B=12.5% (cooldown: XVS/LISTA/...), C=35% (lockup). Unknown token → bucket B + `lav_uncertain=1` flag (renders "B?" in UI).
- **Cross-chain spreads are "pre-bridge ceilings"** — theoretical upper bounds before bridge cost/slippage. The dashboard says this loudly. Bridge gate (≤$1, via Binance) is Phase 2.
- TDD: tests first. All tests offline against captured fixtures in `tests/fixtures/`. The golden regression test (`tests/test_golden.py`) locks ranking output against a captured payload — if it fails, investigate the math diff before updating the locked values.

---

## Files NOT in the repo (gitignored, local-only)

These exist on the maintainer's machine but are deliberately kept out of version control:
- `codee_strategy_context.md` — proprietary strategy doc (the full framework + specific routes)
- `analise.md` — chat correspondence with Paul (the domain expert/strategist)
- `image*.png` — screenshots

If you need strategy context and these aren't present, ask the maintainer — don't reconstruct from memory.

---

## What's next (deferred work)

**Phase 1b (optional polish):**
- Run `backfill_history.py` to populate the History tab with 90d trends
- Persist `last_error` (currently always None — ingestor failures only hit logs)
- Batch commits in `snapshot.py`/`aggregator.py` (currently N×2 commits/tick)
- Property-based tests (hypothesis) for analyzer invariants
- Protocol-API enrichment (e.g. `api.venus.io`) for live liquidity / collateral factor

**Phase 2:**
- Cross-chain executable routes with real bridge cost modeling (Binance as canonical bridge, ≤$1 gate)
- Reward token price feed (CoinGecko/DexScreener) + "reward crashed >20%" alerts
- Telegram/Slack alerts on regime/spread thresholds
- Delta-neutral volatile-collateral loops (BTC/ETH legs, net-zero price exposure)

**Phase 3:**
- On-chain execution (Binance API + Aave/Venus/Morpho/Kamino contracts), HF monitoring, defensive exits

---

## Reference docs

- `docs/superpowers/specs/2026-05-27-codee-fase1-design.md` — full design spec (architecture, schema, all decisions with rationale)
- `docs/superpowers/plans/2026-05-28-codee-fase1a.md` — the 20-task implementation plan
- PoC scripts (kept as reference): `demo_routes.py`, `export_snapshot.py`, `poc_venus_reward.py`, `demo_loops_with_merkl.py`
