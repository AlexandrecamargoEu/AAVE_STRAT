# Codee — Multi-hop cross-chain carry (for review)

## Objective
Today the cross-chain view only does **one hop**. This adds the **multi-hop** version you asked
for — chains like: USDC@Sonic (supply) → borrow WETH → Celo (supply) → borrow USDT → Avalanche
(supply) → … — found and ranked automatically by net yield on your starting capital.

## How it works
Each hop: supply an asset as collateral, borrow a different asset against it, move that borrowed
asset to another chain, supply it there. The borrowed amount funds the next hop (so the position
shrinks each hop by the LTV). The chain ends on a supply — never an open borrow.

## Decisions taken
- **Moving assets = via Binance only** (withdraw to the next chain / deposit from the current).
  Keeps every route actually executable and cheap (≤ ~$1) instead of theoretical.
- **Assets limited to USDC / USDT / ETH / BTC** — most liquid/bridgeable, and they cover your
  example (WETH = ETH, BTC.B = BTC).
- **Up to 3 hops**, starting from your Binance withdrawal asset.
- **Ranked by net leveraged carry on your capital** (Σ supply yields − Σ borrow costs, with the
  shrinking position size). Bridge cost shown separately.

## Limitations (please sanity-check)
- **It's a ceiling, not a guarantee** — APY shown before bridge cost/slippage.
- **Liquidation risk is per-position.** Borrowing an asset and re-supplying it elsewhere is
  delta-neutral overall, but each leg can still be liquidated if that asset moves — a 3-hop chain
  is 3 separate positions to keep healthy.
- **Some supply yields are understated** — our data (DefiLlama) misses incentives like Aave Merit
  (your "Celo WETH 4.2%" read as 0.015% for us).

## My two doubts for you
1. Is restricting to **USDC/USDT/ETH/BTC** fine, or should major stables (DAI, FRAX…) be in too?
2. Is **3 hops** realistic to actually execute, or is **2** the practical max given the per-leg
   liquidation risk?
