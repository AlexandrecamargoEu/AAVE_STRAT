# DeFi Stablecoin Lending Strategy — Context for Claude

**Purpose**: This document is the complete context for a DeFi stablecoin lending bot project. Paste it into Claude at the start of any conversation about strategy design, rate analysis, or implementation. It transfers the full mental model so Claude can reason about new questions without you re-explaining the foundations.

**Your role**: You're Alexandre, the implementer. You have 6 months of CEX arbitrage experience and you're now building a DeFi yield bot called Codee. The strategist (the person who originally worked through this analysis) hands you research and asks you to operationalize it. When asking Claude questions, you're working through implementation details, edge cases, and live-data decisions.

**How to use this file**: Drop it into the project's context. Then ask Claude things like:
- "Given today's BSC Venus rates from DefiLlama, which strategy is optimal for $500k over 24h?"
- "USD1 supply rate on Venus just dropped to 6%. Does Strategy 4 still make sense?"
- "Should I rotate $300k from Base to BSC right now? Show the breakeven math."
- "Aave V3 USDC borrow pool on Base just hit 92% utilization. What do I do?"

---

## Part 1: The Foundations (Read First)

### What we're actually doing

We're running leveraged stablecoin lending loops. The core mechanic: supply a stablecoin on a lending protocol, borrow another stablecoin against it, redeploy the borrowed amount as new collateral somewhere else, repeat. Each "loop" multiplies our exposure to the spread between supply rates and borrow rates.

A loop with 90% LTV (loan-to-value) and 5% safety buffer means each $1 of supplied collateral lets us borrow ~$0.855. After 10 iterations, $1 of initial capital becomes ~$6.60 of total supplied position. The net yield = (total supplied × supply APY) − (total borrowed × borrow APR). On a 5% structural spread (e.g., supply 8% / borrow 3%), this 6.6x leverage produces 25%+ gross APY.

### Four sources of profit (always think in these terms)

1. **Base lending spread** — what borrowers organically pay lenders. Currently 1-2% on stables alone. Insufficient by itself.

2. **Incentive token rewards** — protocols pay reward tokens (XVS, KMNO, JUP, MERIT) to attract liquidity or borrow demand. The "effective" supply APY = base + rewards. The "effective" borrow APR = base − rebate. This is where 5%+ spreads come from.

3. **Cross-platform borrow-to-supply arbitrage** — different platforms on the same chain have uncorrelated incentive programs. Borrow cheap on Aave V3 (Merit-rebated), supply expensive on Venus (XVS-rewarded). This is the durable structural edge.

4. **Stablecoin depeg gravity** — USDC/USDT mean-revert after stress events. Smaller component, opportunistic only.

### The fundamental ceiling

For risk-managed strategies in the current rate environment, here are realistic APY ceilings:

| Strategy | Net APY Ceiling | Capacity |
|---|---|---|
| Stable-only active ping-pong | 25-30% | ~$1M before rate impact bites |
| LST passive loops (30+ day holds) | 20-25% | ~$5M (LSTs sit longer, accept lower per-dollar yield) |
| Opportunistic spike trades | 40-80% | Transient, hours-long |
| **Blended portfolio** | **25-28%** | $1M-5M scale |

**The 50% net APY target only exists in specific transient conditions** — HyperLend incentive phase (early 2025 — net 112% briefly), or wide LST staking yields during validator-reward spikes. We are not realistically targeting 50% sustained.

### Why BSC dominates structurally (April 2026)

BSC has the widest stablecoin spread (~5%) because two independent DAO incentive programs run there simultaneously:

- **Venus pays XVS rebates** on the borrow side (~−2.5% effective). They do this to retain users in a saturated market where Aave V3 entered to compete for share.
- **Aave V3 pays Merit rebates** on borrows on BSC (~−2.0%). The Aave DAO views BSC as strategically important for Asian retail flow.

These two facts are uncoordinated. They compound. That's why Venus USDT supplies 8% while Aave V3 USDC borrows cost only 3% net — a 5% structural spread that no single chain captures within its own ecosystem.

Solana, by contrast, has converged spreads (~1.6%) because Kamino and Jupiter compete for the same Solana-native capital with similar incentive programs. The structural opportunity is just smaller.

### Why this is fragile

The 5% BSC spread depends on:
- XVS price holding (rebates are paid in XVS tokens at market price)
- Aave Merit allocations continuing to favor BSC (quarterly DAO vote)
- Neither Venus nor Aave changing emission policy

All three could shift. The bot needs to monitor: XVS price daily, Merit allocations weekly, governance forum proposals for either platform.

---

## Part 2: Operating Parameters

### Standard test parameters

- **Position sizes tested**: $100k, $250k, $1M, $5M
- **Hold windows**: 5h (intraday), 10h (overnight), 30d (LST sidecar), 90d (deep yield)
- **Safety buffer**: 5% below max LTV (so 95% LTV → 90.25% effective)
- **Gas filter**: ≤$0.10/tx (excludes ETH L1, TRON; includes BNB, Solana, L2s, Sui)
- **Acceptable stables (>$1M pool TVL)**: USDT, USDC, USD1, USDe, FDUSD, U
- **Reject**: cross-asset chains involving BTC/ETH/SOL (directional risk + asymmetric liquidation)

### Buffer methodology

The 5% buffer is not just a safety margin — it's an active management threshold. When health factor (HF) on any platform drops below 1.05, the bot adds collateral from a reserve pool. When HF drops below 1.02, it unwinds the position rather than topping up. The buffer assumes a stablecoin depeg of up to 5% is recoverable; greater depegs trigger exit.

### Capacity ceilings per chain (April 2026)

| Chain | Best Route | Capacity Sweet Spot | Hard Cap |
|---|---|---|---|
| BSC | Venus ↔ Aave V3 | $500k-$2M | ~$5M (rate impact >15%) |
| Base | Aave V3 ↔ Morpho | $500k-$2M | ~$3M |
| Sui | NAVI ↔ Suilend | $100k-$500k | ~$1M (smaller pools) |
| Solana | Kamino ↔ Jupiter | $250k-$1M | ~$3M |
| Optimism | Aave V3 ↔ Morpho | $200k-$1M | ~$2M |
| Arbitrum | Aave V3 ↔ Fluid | $200k-$1M | ~$2M |
| **Avalanche** | **SKIP** | (negative structural spread today) | n/a |

---

## Part 3: The Four Strategies (Simple → Complex)

This is the strategy ladder, ordered from simplest to most complex. Each adds operational complexity and one or more new risks. **The added complexity must be priced into the required premium over the prior strategy.**

### Strategy 1: Inner-Chain Ping-Pong (Baseline)

**Mechanic**: Pick one chain, two platforms on that chain, two stablecoins. Loop between them entirely on-chain.

Example (BSC):
1. Supply $1M USDT on Venus → borrow USDC on Venus at 90% LTV
2. Walk USDC to Aave V3 → supply USDC → borrow USDT
3. Walk USDT back to Venus → supply more
4. Repeat 10 iterations

**Result at $1M, 10h, 90% LTV**: Gross APY 25.82%, net 10h $287, net APY 25.15%, breakeven 0.31h.

**Risk surface**:
- Smart contract risk on Venus + Aave V3 (~0.5-1%/year baseline)
- USDT/USDC depeg above 5% (rare)
- Pool utilization spike during stress events (exit liquidity)
- No Binance dependency, no cross-chain dependency

**When to use**: Always. This is the default. It's the highest yield per unit of risk available.

### Strategy 2: Binance No-Swap Cross-Chain Ping-Pong

**Mechanic**: Use Binance as a settlement layer between chains. Alternate USDC and USDT so no swap is needed on Binance — just withdrawal and re-deposit.

Example (BSC ↔ Base):
1. Supply $1M USDC on Aave V3 Base → borrow USDT on Base
2. Send USDT to Binance → withdraw USDT to BSC ($0.29 fee)
3. Supply USDT on Venus BSC → borrow USDC
4. Send USDC to Binance → withdraw USDC to Base ($0 fee, free promo)
5. Repeat 6 cycles

**Result at $1M, 10h**: Gross APY 20.38%, net 10h $229, net APY 20.05%.

**Why lower than Strategy 1**: Fewer iterations (6 vs 10) because each cross-chain hop has a small withdrawal fee that eats the next iteration. Lower leverage (4.2x vs 6.6x). Time spent in transit (~36 minutes total) is yield-free.

**New risks added vs Strategy 1**:
- **Binance counterparty risk** during the 30-36 minutes per cycle that capital is on Binance. If Binance freezes withdrawals (Mt. Gox 2014, FTX 2022, Celsius 2022), in-transit capital is stuck. Required premium: ~2% APY.
- **Withdrawal limit risk** — Binance enforces daily withdrawal caps ($1-8M depending on KYC tier). Hitting the cap mid-cycle strands capital. Required premium: ~1% APY.
- **Operational complexity** — Binance API integration, address whitelisting (24h), partial-fill handling. Required premium: ~1-2% APY.

**Total required premium**: 4-5%. Current delivery: −5% (worse than baseline). **Strategy 2 is therefore not yield-competitive at 10h windows.** Only use it for chain risk diversification when that diversification is independently valuable.

### Strategy 3: Binance With 1bp Swap

**Mechanic**: Same as Strategy 2, but allow USDC↔USDT swaps on Binance at 1 bp (the special stablecoin-pair fee, **not** the 7.5 bp standard rate). This lets you pick the best asset to supply on each chain regardless of cycle parity.

**Result at $1M, 10h**: ~20.09% net APY, essentially tied with Strategy 2.

The 1bp swap is small enough that it rarely changes the optimal route. **Use Strategy 3's swap capability for rotation only**, not for continuous looping.

### Strategy 3a: Rotation Tool (the Real Use Case)

Where the 1bp Binance fee genuinely shines is **single-direction rotation between chains** when rates shift.

Cost to rotate $333k via Binance: ~$35 (1bp swap + $0.10 withdraw + $0.20 gas). Breakeven analysis:

| New chain APY premium | Breakeven hours |
|---|---|
| +1% APY | 92h (~4 days) |
| +2% APY | 46h (~2 days) |
| +5% APY | 18.5h (~0.8 days) |

**Rotate when**: a chain offers ≥5% APY premium AND the premium has persisted for 3+ days. Don't react to intraday spikes.

### Strategy 4: USD1 via Venus + Binance 0-Fee Promo

**Mechanic**: BNB Chain runs a "0 Fee Carnival" promo through March 31, 2026 making Binance withdrawals of USD1, USDC, and U to BSC completely free. Venus offers ~9.5% supply on USD1 (incentive-attraction phase). This unlocks routes where the structural spread is wider than USDC/USDT.

Example route:
1. USDT → USD1 swap on Binance (1bp)
2. Withdraw USD1 to BSC (free)
3. Supply USD1 on Venus at 9.5% → borrow USDC on Aave V3 at 3.0%
4. Send USDC to Binance (free withdraw back)
5. Withdraw USDC to Base (free)
6. Supply USDC on Morpho/Aave at 6.5% → borrow USDT at 2.0%
7. Send USDT to Binance, swap USDT→USD1 (1bp)
8. Withdraw USD1 to BSC (free), repeat

**Result at $1M, 10h**: Gross APY 29.29% (high!), but net 10h **−$227** (negative). Why? The two 1bp swaps per cycle × 4 cycles × ~$1M average = ~$558 in swap fees. 10h yield can't recover that.

**Result at $1M, 30 days**: net ~$23,810, net APY 29%. **Strategy 4 only works at multi-day holds.**

**New risks vs Strategy 1**:
- **USD1 issuer risk** — USD1 launched April 22, 2025 by World Liberty Financial. Reserves claimed to be US Treasuries but audit transparency is nascent vs USDC/USDT. A USD1 depeg could be 10-30%, much worse than USDC/USDT history. Required premium: 5-10% APY.
- **Promo expiration risk** — 0-fee Binance withdraws end March 31, 2026. After that, the cost structure changes overnight. Required premium: track date, exit before expiry.
- **Asset concentration** — collateral concentrates in USD1 vs the diversified USDT/USDC of Strategy 1. Required premium: 1-2% APY.

**Total required premium**: 8-12%. Currently delivers 4% gross premium (29% vs 25%) at 30d hold, **net negative at 10h**. **Use Strategy 4 only as a 30+ day position play, not for active rotation.**

### Strategy comparison (summary)

| # | Strategy | Net APY (10h) | Risk Premium vs S1 | When to Use |
|---|---|---|---|---|
| 1 | Inner-chain BSC Venus↔Aave V3 | **25.15%** | baseline | Always (default) |
| 2 | Binance no-swap cross-chain | 20.05% | −5.10% | Chain diversification only |
| 3 | Binance with 1bp swap | 20.09% | −5.06% | Rotation tool, not active strategy |
| 4 | USD1 via Venus + 0-fee promo | -19.92% (10h) / +29% (30d) | varies by duration | 30+ day passive holds only |

### LST Sidecar (parallel strategy, longer time horizon)

Outside the four core strategies, a **liquid staking token loop** earns 20-25% net APY over 30+ day holds:

JitoSOL/SOL on Solana, Kamino: supply JitoSOL (earning 7.5% staking + 1% pool yield = 8.5%), borrow SOL at 1.2%. Loop 6 times via DEX swap (SOL→JitoSOL, 10 bps each). At 30 days: ~21% net APY. At 90 days: 26%. Asymptotes to 28%.

**Use as sidecar**: allocate 10-20% of bankroll to LST loops as "set and check weekly" income on top of the active stable strategy. Blended performance on $250k bankroll = ~24.4% net APY combining $200k stable + $50k LST.

---

## Part 4: Live Data Architecture (Codee's Job)

The above strategies are **structurally correct**. The specific numbers move daily with utilization, incentive token prices, and DAO governance. Codee's role is to feed Claude live data so it can make decisions in real time rather than from snapshots.

### Required data fields per platform/pool

**Live (current snapshot, refresh every 30 min)**:
- `chain`, `protocol`, `pool_id` (DefiLlama UUID), `asset_symbol`
- `tvl_usd` (only track pools ≥$1M)
- `borrowed_usd`, `available_usd`, `utilization_pct`
- `supply_apy_base`, `supply_apy_reward`, `supply_apy_total`
- `borrow_apr_base`, `borrow_apr_reward`, `borrow_apr_net` (base minus rebate, floored at 0)
- `reward_tokens[]` with `symbol`, `price_usd`, `liquidity_score` (LAV bucket A/B/C)

**Historic (one row per pool per 30-min snapshot, going back as far as we can)**:
- All of the above fields
- `timestamp` (UTC)

**Derived (computed from the above)**:
- `effective_supply_apy` = `supply_apy_base + supply_apy_reward × LAV_discount`
  - LAV bucket A (immediate, like AAVE/KMNO/JUP/COMP): discount = 0% (full credit)
  - LAV bucket B (7-21 day cooldown, like SPK/LISTA/FELIX): discount = 10-15%
  - LAV bucket C (long lockup/uncertain, like HPL/MFI): discount = 20-50%
- `effective_borrow_apr` = max(0, `borrow_apr_base - borrow_apr_reward × LAV_discount`)
- `structural_spread` per chain = max effective supply across platforms − min effective borrow across platforms (for the same asset class)
- `30d_avg`, `7d_avg`, `current` for each rate field

### Data sources

**Primary: DefiLlama public API** (no auth required, CORS-enabled):

- `GET https://yields.llama.fi/pools` — snapshot of all pools (~12,000 entries). Returns `apyBase`, `apyReward`, `apyBaseBorrow`, `apyRewardBorrow`, `tvlUsd`, `totalBorrowUsd`, `chain`, `project`, `symbol`, `poolMeta`, `pool` (UUID).
- `GET https://yields.llama.fi/chart/{pool_uuid}` — daily history per pool for ~90 days. Returns array of `{timestamp, apyBase, apyReward, tvlUsd}`.

DefiLlama refreshes data hourly. For sub-hour granularity, we need to scrape it ourselves (next bullet).

**Secondary: direct on-chain RPC reads** for sub-hourly polling:

- Aave V3 / Venus / Compound use `ReserveData` calls — query `liquidityRate` and `variableBorrowRate` via the protocol's data provider contract.
- Morpho uses `MarketParams` queries against its Blue contracts.
- Kamino/Jupiter Solana use SDK calls; rate fields are deterministic from utilization.

Sub-hour polling lets us catch rate spikes that DefiLlama would smooth out, but it requires running RPC infrastructure. **Phase 2 priority — start with DefiLlama hourly until basic system works.**

**Tertiary: reward token prices** from CoinGecko or DexScreener for the LAV adjustment. Refresh every 5 minutes (these can move 10%+ in an hour).

### Database schema (PostgreSQL or similar)

```
TABLE pools_snapshot           — current state, one row per pool, updated every 30 min
  pool_id (PK)
  chain, protocol, symbol, pool_meta
  tvl_usd, borrowed_usd, utilization
  supply_apy_base, supply_apy_reward
  borrow_apr_base, borrow_apr_reward
  reward_tokens (jsonb array)
  updated_at

TABLE pools_history            — append-only, one row per pool per snapshot
  pool_id, timestamp (composite PK)
  [all the above fields]

TABLE reward_token_prices      — current and historic token prices
  token_symbol, timestamp (composite PK)
  price_usd, lav_bucket, lav_discount_pct

TABLE rate_aggregates          — derived rolling averages
  pool_id, window (current/7d/30d), timestamp
  avg_supply_apy_effective
  avg_borrow_apr_effective
  avg_utilization
  spread_to_best_borrow_same_chain
```

### Snapshot cadence

- **Every 30 minutes**: snapshot all pools, write to `pools_history`, update `pools_snapshot`
- **Every 5 minutes**: refresh reward token prices
- **Every 30 minutes after the snapshot**: recompute aggregates (current, 7d avg, 30d avg)
- **Every 1 hour**: alert if any tracked pool's utilization crosses 85% (Telegram/Slack)
- **Every 1 hour**: alert if any tracked pool's effective spread shifts >2% vs the 7d average

### What this enables

Once the data is live and queryable, you can ask Claude things like:

> "Show me the top 5 ping-pong routes today, ranked by 7-day average net APY, requiring TVL >$1M and utilization <80%."

> "Has Venus USDT supply rate been above 7% for the last 30 days? Show the daily history."

> "If I rotate $500k from BSC to Base right now, what's my expected breakeven given current rates and a $52 rotation cost?"

> "Alert me when USD1 supply on Venus drops below 8% — that's our exit signal for Strategy 4."

> "Compare current spreads to the same time last week. What changed?"

Claude can answer all of these if the data is in the database and Codee exposes it as a query interface.

---

## Part 5: Risk Framework (Always Surface These)

### Risk inventory

Every strategy carries some combination of these risks. The strategy ladder is defined by which risks each layer adds.

**Tier 1 — Always present (Strategy 1 baseline)**:
- **Smart contract exploit risk** on each protocol you use. Historical loss rate for established protocols (Aave, Venus, Compound, Morpho): ~0.5-1% of TVL per year. For newer protocols (Lista, NAVI, Suilend): higher, possibly 2-3%.
- **Oracle manipulation risk** — if the price oracle a lending platform uses gets manipulated, your collateral can be priced incorrectly and liquidated unfairly. Aave uses Chainlink (mature). Smaller platforms use less-battle-tested oracles.
- **Liquidation cascade risk** — during sharp stable depegs, liquidator bots compete for your collateral at 5-10% penalty. The 5% buffer protects against depegs up to ~5% relative move between USDC/USDT.
- **Pool utilization exit risk** — during stress events, pools hit 100% utilization and you can't withdraw until borrowers repay. Historical example: April 20, 2026 Aave KelpDAO incident — looped positions stuck for days at 15-25% exit premiums.

**Tier 2 — Added by Strategy 2/3 (Binance bridging)**:
- **CEX counterparty risk** during transit (~3-6 min per leg). If Binance freezes withdrawals, in-transit funds are stuck.
- **CEX withdrawal limits** at $1-8M/day per account tier. Strategy can stall at scale.
- **API/operational failures** — withdrawal address typos cause permanent loss. Whitelist propagation delays. Stuck withdrawals require manual support (24-72h response).

**Tier 3 — Added by Strategy 4 (USD1)**:
- **Newer stablecoin issuer risk** — USD1 reserves transparency is less established than USDC/USDT. Depeg events could be 10-30% rather than 1-3%.
- **Promo dependency** — strategy economics depend on a marketing promo that expires.
- **Concentration risk** — collateral is in one asset rather than diversified.

**Tier 4 — Added by LST loops**:
- **LST depeg risk** — JitoSOL/wstETH/haSUI can depeg 5-15% in stress events (historical precedent: stETH 6% discount during Three Arrows / Celsius unwind, 2022).
- **Staking slashing risk** — small but real; validator misbehavior reduces the LST's underlying SOL/ETH.
- **Long position commitment** — you can't exit a profitable LST loop in 1 day; you committed to multi-week holds for the strategy to clear breakeven.

### How to reason about premium

If a strategy adds a risk tier without correspondingly higher gross APY, it's strictly worse than the lower-tier strategy. **Don't run higher-risk strategies for lateral or worse yield.**

The way to verify: compute the strategy's expected APY net of fees, subtract the baseline (Strategy 1) APY, and compare to the required premium for the added risks. If the delta is positive and large enough to cover the premium, the strategy is yield-justified. Otherwise, skip.

Strategy 4 at 30-day hold delivers +4% gross premium (29% vs 25% baseline). Required premium for USD1 risks: 8-12%. **Even at 30 days, Strategy 4 currently underpays for its risk.** Only run it if USD1's audit/reserve transparency improves OR Venus's USD1 supply rate climbs to 12%+.

---

## Part 6: Key Numbers Reference

These are April 2026 snapshots and **must be verified against live data before acting**. They're here so Claude can reason about them in conversation.

### Per-chain best routes ($250k, 10h, 90% LTV, 5% buffer)

| Chain | Top Route | Lev | Gross APY | 10h Net | Net APY | Breakeven |
|---|---|---|---|---|---|---|
| **BSC** | Venus USDT↔Aave V3 USDC | 6.60x | 25.82% | $71.40 | **25.02%** | 0.31h |
| **Base** | Aave V3 USDT↔Morpho USDC | 6.60x | 22.95% | $63.22 | 22.15% | 0.35h |
| **Sui** | NAVI USDC↔Suilend USDT | 4.15x | 21.33% | $58.60 | 20.53% | 0.37h |
| **Optimism** | Aave V3 USDT↔Morpho USDC | 6.60x | 18.72% | $52.55 | 18.45% | 0.42h |
| **Arbitrum** | Aave V3 USDT↔Fluid USDC | 6.60x | 16.97% | $47.66 | 16.70% | 0.49h |
| **Solana** | Kamino USDC↔Jupiter USDT | 6.60x | 11.75% | $31.26 | 10.95% | 0.68h |
| Avalanche | Benqi↔Aave V3 (FLAT) | 3.47x | 3.02% | $6.33 | 2.22% | 2.65h |

### Within-chain cross-platform spreads (best supply minus cheapest borrow)

| Chain | Max Spread | Source Combo |
|---|---|---|
| BSC | 5.0% | Venus USDT 8% supply − Aave V3 USDC 3% borrow |
| Base | 5.0% | Morpho USDC 7% supply − Aave V3 USDT 2% borrow |
| Sui | 4.5% | Suilend USDT 10% supply − NAVI USDT 5.5% borrow |
| Optimism | 4.0% | Morpho USDC 6.5% − Aave V3 USDT 2.5% |
| Arbitrum | 3.5% | Fluid USDC 6.0% − Aave V3 USDT 2.5% |
| Solana | 1.6% | Jupiter USDC 7.8% − Kamino USDT 6.2% |
| Avalanche | 0.0% | (negative, skip) |

### Cross-chain spreads (Binance bridging, best supply elsewhere minus cheapest borrow elsewhere)

| Route | Spread |
|---|---|
| Supply USDT on Sui (Suilend 10%) + Borrow USDT on Base (Aave V3 2%) | **8.0%** |
| Supply USDC on Sui (NAVI 8%) + Borrow USDC on Base (Aave V3 2%) | 6.0% |
| Supply USDT on BSC (Venus 8%) + Borrow USDT on Base (Aave V3 2%) | 6.0% |
| Supply USD1 on BSC Venus (9.5%) + Borrow USDC on Aave V3 Base (2%) | 7.5% |

### Binance withdrawal fees (April 2026)

| Chain | USDT | USDC | USD1 | U | FDUSD |
|---|---|---|---|---|---|
| BSC | $0.29 | **$0.00** (promo until Mar 31 2026) | **$0.00** | **$0.00** | $0.29 |
| Solana | $0.10 | $0.00 | n/a | n/a | n/a |
| Sui | $0.50 | $0.50 | n/a | n/a | n/a |
| Base | $0.10 | $0.00 | n/a | n/a | n/a |
| Arbitrum | $0.10 | $0.10 | n/a | n/a | n/a |
| Optimism | $0.10 | $0.10 | n/a | n/a | n/a |

### Binance trading fees

- USDC/USDT pair: **1 bp taker, 0% maker** (special stablecoin pair rate, not the standard 7.5 bp)
- USDT/USD1: 1 bp
- USDT/FDUSD: 1 bp
- USDT/USDe: 1 bp

### Gas costs per transaction (April 2026)

| Chain | Approx gas per tx |
|---|---|
| BSC | $0.10 |
| Solana | $0.005 |
| Sui | $0.01 |
| Base | $0.03 |
| Arbitrum | $0.04 |
| Optimism | $0.04 |
| Avalanche | $0.05 |
| ETH L1 | $1.20 (exclude) |
| TRON | $0.80 (exclude) |

### Reward token LAV (liquid-at-vesting) buckets

- **Bucket A (immediate, full credit)**: AAVE, KMNO, JUP, COMP, NAVX, SLND, MORPHO
- **Bucket B (7-21d cooldown, 10-15% discount)**: SPK, LISTA, FELIX
- **Bucket C (long lockup, 20-50% discount)**: HPL, AVAL quarterly, MFI

### Key events to monitor

- **March 31, 2026**: BNB Chain 0-Fee Carnival expiration. If extended, Strategy 4 economics persist. If not, Strategy 4 cost structure breaks.
- **Quarterly**: Aave DAO Merit allocation reviews. If BSC Merit allocation drops, BSC spreads compress.
- **Monthly**: Venus XVS emissions governance. Watch for stablecoin market reallocation.
- **April 20, 2026**: Anniversary of Aave KelpDAO incident. The pattern (utilization spike → exit lockup) can recur with any unbacked-collateral discovery.

---

## Part 7: Decision Frameworks (When-Then Rules)

When asking Claude about strategy decisions, use these heuristics as anchors.

### "Should I deploy capital now?"

1. Pull current rates from Codee
2. Compute structural spread per chain
3. If BSC spread ≥4.5% and BSC pool utilization <80% → deploy Strategy 1 on BSC
4. If BSC spread <4.5% but Base spread ≥4.5% → deploy Strategy 1 on Base
5. If no chain has spread ≥4.0% → hold cash, wait

### "Should I rotate between chains?"

1. Compute APY delta between current chain and target chain
2. If delta ≥5% AND has persisted ≥3 days → rotate via Binance ($35-100 per $333k)
3. If delta 2-5% AND has persisted ≥7 days → rotate
4. If delta <2% OR transient → stay

### "Should I add the LST sidecar?"

1. Confirm you have funds you can lock for ≥30 days
2. Check JitoSOL/wstETH/haSUI staking yield + pool yield >10% combined
3. Check LST depeg history past 90 days (if any depeg >5%, skip)
4. Allocate 10-20% of bankroll, set 30-day review

### "Should I run Strategy 4 (USD1)?"

1. Check holding window — only run if ≥30 days committed
2. Check USD1 reserve attestation status (must be ≤30 days old)
3. Check Venus USD1 supply rate ≥9% (otherwise breakeven extends)
4. Check Binance 0-Fee Carnival still active (otherwise cost structure breaks)
5. Limit position to ≤$200k (USD1 pool depth concern)

### "What do I do during a stress event?"

A stress event = any of: stablecoin depeg >2%, pool utilization >90%, oracle issue, exploit rumor.

1. **Stop all new deployments immediately**
2. **Unwind largest position first** (most exposure to compounding stress)
3. **Move proceeds to Binance** (faster than waiting for chain confirmation during congestion)
4. **Hold in stablecoin pair (USDC/USDT) on Binance** until stress passes
5. **Document what triggered**, update Codee's alert thresholds

### "What do I do when rates change suddenly?"

If a chain's spread compresses >2% in 24 hours:
- Don't unwind reflexively — small compressions reverse within days
- Check if a competing platform launched (often the cause)
- Wait 48 hours for the new equilibrium
- If still compressed at 48h, rotate

If a chain's spread expands >2% in 24 hours:
- This is opportunity. Check if it's a temporary spike (high utilization) or structural (new incentive program)
- Spike: deploy small ($100k) to test, exit when spike collapses
- Structural: scale up to capacity

---

## Part 8: How to Talk to Claude About This

When asking Claude questions, give it the live data it needs. Don't make it guess.

**Good prompt format**:

> Here's today's snapshot from Codee:
> - BSC Venus USDT supply: 7.8% (was 8.0% last week)
> - BSC Aave V3 USDC borrow: 3.2% (was 3.0% last week)
> - Aave V3 BSC USDC pool: $385M supplied, $295M borrowed, 76% util
> - Question: Should I deploy $500k now, wait, or rotate to Base?

Claude can reason with this. It can compute the new spread (4.6% vs 5.0% last week), apply the decision framework, and recommend deploying because the spread is still above 4.5% and utilization is below 80%.

**Bad prompt format**:

> What should I do today?

Claude has no data to act on. It will give generic answers.

### Useful prompts to keep handy

- "Given current Codee data, rank the top 5 deployable routes for $1M, 24h hold."
- "Compare today's BSC spread to 7d avg and 30d avg. Is this a buy signal or warning?"
- "Compute the breakeven for rotating $500k from Base to BSC at current rates."
- "What's the maximum safe deposit size for the BSC Venus USDT pool today before rate impact exceeds 0.3%?"
- "If USDC depegs to $0.97 right now, what's our liquidation exposure across all open positions?"
- "Show me every pool where current supply APY is >15% above the 30d average — flag possible spikes."

---

## Part 9: TODO Backlog (Implementation Priorities)

Ordered from highest-value to lowest. Do them top-down.

### Phase 1 — Foundation (Week 1-2)
1. **DefiLlama API integration**: pull `/pools` and `/chart/{uuid}` for tracked platforms, store in `pools_snapshot` and `pools_history`. ETA 2 days.
2. **30-min snapshot job**: cron job, write to history table. ETA 1 day.
3. **Aggregate computation**: 7d and 30d rolling averages per pool. ETA 1 day.
4. **Live dashboard**: web UI showing current rates, structural spread per chain, top-ranked routes. ETA 3 days.

### Phase 2 — Decision Support (Week 3-4)
5. **Pairwise loop simulator**: takes current rates as input, returns net APY for all ping-pong combinations. Already drafted in Python — translate to Codee's stack. ETA 2 days.
6. **Risk score per pool**: composite score combining TVL, utilization, smart contract age, reward token LAV. ETA 2 days.
7. **Alert system**: Telegram/Slack push on threshold breaches (utilization >85%, spread shift >2%, reward token price >20% daily move). ETA 2 days.

### Phase 3 — Execution (Week 5-8)
8. **Binance API read-only**: account balance, withdrawal history, current limits. ETA 1 day.
9. **Binance API trading**: 1bp swap execution, withdrawal initiation with whitelisted addresses. **Test with $100 first.** ETA 1 week including test cycles.
10. **On-chain bot execution**: Aave/Venus/Morpho/Kamino/Jupiter contract interactions for supply/borrow/repay/withdraw. ETA 2 weeks.
11. **Position monitor**: real-time HF tracking per platform, top-up triggers, defensive exit logic. ETA 1 week.

### Phase 4 — Advanced (Month 3+)
12. **Sub-hourly polling**: direct RPC reads for tracked pools, catch rate spikes DefiLlama smooths out.
13. **LST sidecar strategy**: JitoSOL/SOL loop with weekly rebalance.
14. **Multi-account orchestration**: spread positions across multiple wallets to mitigate per-wallet limits.
15. **Backtesting engine**: replay historic snapshots to validate new strategy ideas before deploying capital.

---

## Part 10: Known Open Questions

These are things the strategist and I haven't fully resolved. If you (Alexandre) work on these, bring findings back into the next version of this context file.

1. **Sub-hour rate volatility**: how often do rates spike >2% within an hour and revert? We need direct RPC polling data to answer. Hypothesis: 2-5 times per week per chain.

2. **Withdrawal queue behavior under stress**: during the April 20 Aave KelpDAO incident, how long were positions stuck and at what premium? We have anecdotal "10-25% premium for days" but not measured. Need to backtest.

3. **Multi-trader compression**: if 3-5 traders run the same BSC strategy with similar size simultaneously, does Aave V3's USDC borrow rate rise enough to break the strategy? We modeled this for one trader at $1M; haven't modeled multi-trader feedback.

4. **USD1 reserve attestation cadence**: World Liberty Financial's audit schedule. If they move to monthly Circle-style attestations, USD1 risk premium drops meaningfully.

5. **Validity of the 5% buffer**: under what depeg scenarios is 5% insufficient? March 2023 USDC depeg hit 8% briefly. If history rhymes, we need 10% buffer. But 10% buffer cuts leverage from 6.6x to ~4.5x, reducing APY by ~7%. Tradeoff worth running.

6. **Sui pool depth growth**: Sui's lending TVL is growing fast. When does it cross $2B aggregate? At that point, Sui spread could either widen (if growth is supplier-side) or compress (if borrower-side). Watch monthly.

7. **Avalanche reactivation conditions**: what would need to happen for Avalanche to re-enter the strategy? Aave Merit reallocation to Avax, or a new lender (Trader Joe Lending, etc.) entering with aggressive incentives. Track quarterly.

---

## Part 11: Glossary

- **APY (annual percentage yield)**: yield compounded annually. Supply rates are usually quoted as APY.
- **APR (annual percentage rate)**: simple annualized rate, no compounding. Borrow rates are usually quoted as APR. For loops over <1 year, APR ≈ APY.
- **LTV (loan-to-value)**: maximum percentage of collateral you can borrow against. 90% LTV means $100 collateral → $90 max borrow.
- **HF (health factor)**: ratio of (collateral × liquidation_threshold) / debt. HF below 1.0 triggers liquidation.
- **eMode (Efficiency Mode)**: Aave V3 feature allowing higher LTV (up to 97% for stablecoins, 93% for LSTs) when supply and borrow are correlated assets.
- **Utilization**: (total borrowed / total supplied) per pool. High utilization (>85%) signals exit liquidity risk.
- **Liquidator**: bot that monitors positions and triggers liquidation when HF <1.0, capturing 5-10% penalty.
- **Ping-pong loop**: cross-platform looping pattern — supply on A, borrow on A, supply on B, borrow on B, repeat.
- **LST (liquid staking token)**: tokenized claim on staked native asset. JitoSOL, wstETH, haSUI.
- **LAV (liquid at vesting)**: classification of how immediately a reward token can be sold at quoted price. A/B/C buckets.
- **Merit**: Aave DAO's incentive distribution program for supply/borrow rewards.
- **MEV (maximal extractable value)**: profits captured by reordering transactions in a block. Relevant for liquidation front-running.
- **Codee**: the dashboard/bot Alexandre is building.
- **Strategy 1/2/3/4**: see Part 3 above.

---

## Part 12: Document Maintenance

This context file should be updated when:

- Any rate moves >1% sustained for 7+ days (refresh Part 6 numbers)
- A new platform crosses $1M TVL on a tracked chain (add to platform list)
- A new strategy is validated (add to Part 3 ladder)
- A risk is observed in production (add to Part 5 inventory)
- An open question is resolved (move from Part 10 to relevant section)

**Last updated**: May 15, 2026
**Maintainer**: Alexandre (Codee)
**Original source**: Conversation with strategist, archived in project transcript

When updating, increment a version number at the top and note what changed in a changelog at the bottom.

---

## Changelog

- **v1.0** (May 15, 2026): Initial context file. Captures the foundational strategy framework, four-strategy ladder, risk hierarchy, live data architecture, and decision frameworks developed through extended strategy work.
