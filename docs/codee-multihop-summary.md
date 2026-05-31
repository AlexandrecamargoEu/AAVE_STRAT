# Codee — Multi-hop cross-chain carry (summary for review)

*A short, non-technical summary of the planned feature, for Paul's review. The full
implementation spec lives separately; this covers only the idea, the modeling choices, and the
honest limitations — the things worth a domain sanity-check before we build.*

---

## Objective

Today Codee's cross-chain view only does **one hop** (supply an asset on chain A, borrow the
same asset cheaply on chain B). You asked for the **multi-hop** version — chains like:

> USDC on Sonic (supply) → borrow WETH → move WETH to Celo (supply) → borrow USDT → move to
> Avalanche (supply) → borrow BTC → …

This feature finds and ranks those chains automatically.

## How a chain works

Each "hop" is one lending position: you **supply** an asset as collateral, **borrow** a
different asset against it on the same platform, **move** the borrowed asset to another chain,
and supply it there. The borrowed amount funds the next hop, so the position shrinks each hop by
the loan-to-value ratio (you can't borrow 100% of your collateral). The chain **ends on a
supply** — you never leave a borrow open at the end (that would be an unhedged short, not carry).

We score each chain by the **net yield on your starting capital** — the sum of what every supply
leg earns minus what every borrow leg costs, accounting for the shrinking position size.

## Key modeling choices (please sanity-check these)

1. **Moving assets = via Binance.** A hop is only allowed if Binance lets you withdraw the
   borrowed asset to the next chain (and deposit it from the current one). This keeps every route
   actually executable and cheap (≤ ~$1), instead of theoretical routes through bridges we can't
   cost. Trade-off: it limits chains to assets/chains Binance supports.

2. **Assets limited to USDC / USDT / ETH / BTC.** These are the most liquid and the most
   bridgeable — and they cover your example exactly (WETH = ETH, BTC.B = BTC). Exotic tokens are
   excluded for now (they're where execution usually breaks anyway).

3. **Up to 3 hops** (your example is 3). More hops = more bridge cost and more liquidation
   surface, with diminishing carry.

4. **Starts from your Binance withdrawal asset** (USDC/USDT/ETH/BTC) — the capital you actually
   start with on Binance.

## What you'll see

Each route shown as a path — e.g. `USDC·Sonic → ETH·Celo → USDT·Avalanche` — with: net APY on
your capital, number of hops, total bridge cost ($), and the thinnest liquidity along the path.

## Honest limitations (the important part)

- **It's a ceiling, not a guarantee.** The net APY is shown *before* bridge cost (bridge $ is a
  separate column), and ignores slippage and gas beyond the bridge fee.
- **Liquidation risk is per-position, not netted.** Even though borrowing an asset and
  re-supplying it elsewhere is delta-neutral overall, each individual position can still be
  liquidated if that asset's price moves — holding it on another chain does NOT protect the leg
  that borrowed it. A 3-hop chain is 3 separate positions to keep healthy.
- **Some supply yields may be understated.** DefiLlama (our data source) misses certain on-chain
  incentives (e.g. Aave's Merit program). Your "Celo WETH 4.2%" was a case of this — we read
  0.015%. So real yields on some legs can be higher than what we show.

## Open questions for you

- Is restricting to **USDC/USDT/ETH/BTC** acceptable, or do you want major stables (DAI, FRAX…)
  bridgeable too?
- Is **3 hops** the right ceiling, or would you go to 4?
- Does the **per-leg liquidation** caveat match how you'd actually run these — i.e. would you
  execute a 3-hop chain, or is 2 hops the realistic max?
