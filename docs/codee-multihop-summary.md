# Codee — Multi-hop cross-chain carry (for review)

## Objective
Today the cross-chain view only does **one hop**. This adds the **multi-hop** version you asked
for — chains like: USDC@Sonic (supply) → borrow WETH → Celo (supply) → borrow USDT → Avalanche
(supply) → … — found and ranked automatically by net yield on your starting capital.

## How it works
Each hop: supply an asset as collateral, borrow a different asset against it, move that borrowed
asset to another chain, supply it there. The borrowed amount funds the next hop (so the position
shrinks each hop by the LTV).

## Two key design questions — and the decision

**1. What counts as a valid "hop" — how do we move the borrowed asset between chains?**
**Decision: via Binance only.** An edge exists only if Binance lets you *deposit* the borrowed
asset on the current chain and *withdraw* it on the next. Why: it's the only bridge we can both
price (≤ ~$1, from our per-chain cost table) and guarantee is executable. Trade-off: limits
routes to Binance-supported assets/chains — which is also why assets are capped to the liquid
majors **USDC / USDT / ETH / BTC** (they cover your example: WETH = ETH, BTC.B = BTC).

**2. Where does the chain start, and what about the last borrowed asset (left open = price risk)?**
**Decision: starts from your Binance withdrawal asset (USDC/USDT/ETH/BTC); ends on a supply.**
The chain never leaves a borrow open at the end — an open final borrow is an unhedged short, not
carry. So no dangling position from the tail. Depth capped at **3 hops** (your example).

Ranked by **net leveraged carry on your capital** (Σ supply yields − Σ borrow costs, with the
shrinking position size); bridge cost shown separately.

## Limitations (please sanity-check)
- **It's a ceiling, not a guarantee** — APY shown before bridge cost/slippage.
- **Liquidation risk is per-position.** Borrowing an asset and re-supplying it elsewhere is
  delta-neutral overall, but each leg can still be liquidated if that asset moves — a 3-hop chain
  is 3 separate positions to keep healthy.
- **Some supply yields are understated** — our data (DefiLlama) misses incentives like Aave Merit
  (your "Celo WETH 4.2%" read as 0.015% for us).
