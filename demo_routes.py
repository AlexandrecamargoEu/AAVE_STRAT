"""
Codee demo v3: GLOBAL discovery — no chain whitelist, no project whitelist.
Surface where opportunity actually exists in live data, regardless of strategy doc assumptions.

Two ranked views:
  1. PASSIVE SUPPLY — supply X on best chain/platform, no loop. Sort by effective APY.
  2. LEVERAGED PING-PONG — supply X on A, borrow Y on A, supply Y on B, borrow X on B.

Both views apply LAV discount and account for gas in net APY.
"""
import json
import urllib.request
from collections import defaultdict
from itertools import combinations

# ====================================================================
# CONFIG (would live in config/ files)
# ====================================================================

STABLE_SYMBOLS = {
    "USDT", "USDC", "USD1", "USDE", "FDUSD", "DAI", "USDS",
    "USDC.E", "USDC.B", "PYUSD", "GHO", "CRVUSD", "FRAX", "TUSD",
    "LUSD", "SUSDE", "AUSD",
}
MIN_TVL_USD = 1_000_000
MIN_LOOP_SPREAD_PCT = -10.0   # show all routes including negative for visibility

# LAV bucket per project. Unknown projects default to bucket B (mid-risk).
PROJECT_LAV_BUCKET = {
    "aave-v3": "A", "venus-core-pool": "A", "morpho-blue": "A",
    "compound-v3": "A", "kamino-lend": "A", "navi-protocol": "A",
    "suilend": "A", "fluid-lending": "A", "spark": "A",
    "dolomite": "A", "euler-v2": "A", "scallop-lend": "B",
    "lista-lending": "B", "lendle-pooled-markets": "B",
    "takara-lend": "B", "kinetic": "B", "canto-lending": "C",
    "neverland": "C",
}
BUCKET_DISCOUNT = {"A": 0.0, "B": 0.125, "C": 0.35}
DEFAULT_BUCKET = "B"  # unknown -> conservative-ish discount

# Position parameters
PRINCIPAL_USD = 250_000
HOLD_HOURS = 24 * 7   # 1 week — fair window to compare passive vs loop

LTV_PER_ITER = 0.855
N_ITER = 10
LEVERAGE = sum(LTV_PER_ITER ** i for i in range(N_ITER))

# Gas per chain — used to penalize net APY
GAS_PER_TX = {
    "BSC": 0.10, "Base": 0.03, "Sui": 0.01, "Solana": 0.005,
    "Optimism": 0.04, "Arbitrum": 0.04, "Avalanche": 0.05,
    "Ethereum": 1.20, "Polygon": 0.02, "Mantle": 0.05,
    "Linea": 0.05, "Scroll": 0.05, "Sei": 0.01, "Flare": 0.01,
    "Monad": 0.01, "Canto": 0.05, "Tron": 0.80, "Tempo": 0.01,
}
LOOP_TX_COUNT = N_ITER * 2
PASSIVE_TX_COUNT = 2  # supply + (eventual) withdraw


def _fetch_json(url):
    req = urllib.request.Request(url, headers={"User-Agent": "codee-demo/0.3"})
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.loads(r.read())


def fetch_pools():
    print("Fetching DefiLlama /pools (supply) ...")
    pools_supply = _fetch_json("https://yields.llama.fi/pools")["data"]
    print(f"  -> {len(pools_supply):,} supply rows")

    print("Fetching DefiLlama /lendBorrow (borrow) ...")
    raw_borrow = _fetch_json("https://yields.llama.fi/lendBorrow")
    pools_borrow = raw_borrow if isinstance(raw_borrow, list) else raw_borrow.get("data", [])
    print(f"  -> {len(pools_borrow):,} borrow rows")

    borrow_by_pool = {b["pool"]: b for b in pools_borrow}
    merged = []
    for p in pools_supply:
        b = borrow_by_pool.get(p.get("pool"))
        if b is not None:
            p["apyBaseBorrow"] = b.get("apyBaseBorrow")
            p["apyRewardBorrow"] = b.get("apyRewardBorrow")
            p["ltv"] = b.get("ltv")
            p["totalBorrowUsd"] = b.get("totalBorrowUsd")
        merged.append(p)
    print(f"  -> {sum(1 for p in merged if p.get('apyBaseBorrow') is not None):,} pools with full lending data\n")
    return merged


def discount(project):
    bucket = PROJECT_LAV_BUCKET.get(project.lower(), DEFAULT_BUCKET)
    return BUCKET_DISCOUNT[bucket]


def lav_label(project):
    return PROJECT_LAV_BUCKET.get(project.lower(), f"{DEFAULT_BUCKET}?")


def is_stable_pool(p):
    if (p.get("symbol") or "").upper() not in STABLE_SYMBOLS:
        return False
    if (p.get("tvlUsd") or 0) < MIN_TVL_USD:
        return False
    return True


def effective_supply_apy(p):
    base = p.get("apyBase") or 0.0
    reward = p.get("apyReward") or 0.0
    return base + reward * (1 - discount(p["project"]))


def effective_borrow_apr(p):
    base = p.get("apyBaseBorrow") or 0.0
    rebate = p.get("apyRewardBorrow") or 0.0
    return max(0.0, base - rebate * (1 - discount(p["project"])))


def rank_passive_supply(pools):
    """Just supply on one platform, no loop. Rank by net APY accounting for gas."""
    eligible = [p for p in pools if is_stable_pool(p)]
    results = []
    for p in eligible:
        sup_apy = effective_supply_apy(p)
        if sup_apy <= 0:
            continue
        hourly = PRINCIPAL_USD * (sup_apy / 100) / 8760
        gross = hourly * HOLD_HOURS
        gas = GAS_PER_TX.get(p["chain"], 0.10) * PASSIVE_TX_COUNT
        net = gross - gas
        net_apy = (net / PRINCIPAL_USD) * (8760 / HOLD_HOURS) * 100 if HOLD_HOURS else 0
        results.append({
            "chain": p["chain"], "project": p["project"], "symbol": p["symbol"],
            "lav": lav_label(p["project"]),
            "base": p.get("apyBase") or 0, "reward": p.get("apyReward") or 0,
            "eff_apy": sup_apy, "net_apy": net_apy,
            "net_yield": net, "tvl": p["tvlUsd"], "gas": gas,
        })
    return sorted(results, key=lambda x: x["net_apy"], reverse=True)


def rank_loops(pools):
    """Find ping-pong (supply X on A, borrow Y on A, supply Y on B, borrow X on B)."""
    loopable = [p for p in pools if is_stable_pool(p) and p.get("apyBaseBorrow") is not None]

    by_chain = defaultdict(dict)
    for p in loopable:
        by_chain[p["chain"]][(p["project"], p["symbol"].upper())] = p

    results = []
    for chain, pools_on_chain in by_chain.items():
        platforms = sorted({k[0] for k in pools_on_chain.keys()})
        assets = sorted({k[1] for k in pools_on_chain.keys()})
        if len(platforms) < 2 or len(assets) < 2:
            continue

        for plat_A, plat_B in combinations(platforms, 2):
            for asset_X, asset_Y in combinations(assets, 2):
                sX_A = pools_on_chain.get((plat_A, asset_X))
                bY_A = pools_on_chain.get((plat_A, asset_Y))
                sY_B = pools_on_chain.get((plat_B, asset_Y))
                bX_B = pools_on_chain.get((plat_B, asset_X))
                if not all([sX_A, bY_A, sY_B, bX_B]):
                    continue

                sup_A = effective_supply_apy(sX_A)
                sup_B = effective_supply_apy(sY_B)
                bor_A = effective_borrow_apr(bY_A)
                bor_B = effective_borrow_apr(bX_B)

                avg_sup = (sup_A + sup_B) / 2
                avg_bor = (bor_A + bor_B) / 2
                spread = avg_sup - avg_bor

                if spread < MIN_LOOP_SPREAD_PCT:
                    continue

                gross_apy = LEVERAGE * avg_sup - (LEVERAGE - 1) * avg_bor
                hourly = PRINCIPAL_USD * (gross_apy / 100) / 8760
                gas = GAS_PER_TX.get(chain, 0.10) * LOOP_TX_COUNT
                gross_t = hourly * HOLD_HOURS
                net = gross_t - gas
                net_apy = (net / PRINCIPAL_USD) * (8760 / HOLD_HOURS) * 100 if HOLD_HOURS else 0
                min_tvl = min(p["tvlUsd"] for p in [sX_A, bY_A, sY_B, bX_B])

                results.append({
                    "chain": chain, "plat_A": plat_A, "X": asset_X,
                    "plat_B": plat_B, "Y": asset_Y,
                    "spread": spread, "gross_apy": gross_apy,
                    "net_apy": net_apy, "net_yield": net,
                    "min_tvl": min_tvl,
                })

    return sorted(results, key=lambda x: x["net_apy"], reverse=True)


def main():
    pools = fetch_pools()
    print(f"=== Codee global discovery: ${PRINCIPAL_USD:,} over {HOLD_HOURS}h ({HOLD_HOURS/24:.1f}d) ===")
    print(f"LAV discount: A=0%, B=12.5%, C=35%, unknown=B?\n")

    # === PASSIVE SUPPLY VIEW ===
    passive = rank_passive_supply(pools)
    print(f"--- TOP 15 PASSIVE SUPPLY (no loop, just deposit) ---")
    print(f"{'#':>2} {'Chain':<10} {'Project':<22} {'Sym':<7} {'LAV':<3} {'Base':>7} {'Reward':>7} {'Eff':>7} {'Net APY':>8} {'TVL':>10}")
    for i, r in enumerate(passive[:15], 1):
        print(f"{i:>2} {r['chain'][:10]:<10} {r['project'][:22]:<22} {r['symbol'][:7]:<7} {r['lav']:<3} "
              f"{r['base']:>6.2f}% {r['reward']:>6.2f}% {r['eff_apy']:>6.2f}% {r['net_apy']:>7.2f}% "
              f"${r['tvl']/1e6:>7.1f}M")

    # === LEVERAGED LOOP VIEW ===
    loops = rank_loops(pools)
    print(f"\n--- TOP 15 LEVERAGED PING-PONG LOOPS ({LEVERAGE:.2f}x leverage) ---")
    if not loops:
        print("(no loops found across any chain)")
    else:
        print(f"{'#':>2} {'Chain':<10} {'Plat A -> Plat B':<40} {'X/Y':<10} {'Spread':>7} {'Gross':>7} {'Net APY':>8} {'MinTVL':>10}")
        for i, r in enumerate(loops[:15], 1):
            print(f"{i:>2} {r['chain'][:10]:<10} {(r['plat_A'][:18] + ' -> ' + r['plat_B'][:16])[:40]:<40} "
                  f"{(r['X'] + '/' + r['Y'])[:10]:<10} {r['spread']:>6.2f}% {r['gross_apy']:>6.2f}% "
                  f"{r['net_apy']:>7.2f}% ${r['min_tvl']/1e6:>7.1f}M")

    # === SUMMARY ===
    print(f"\n--- SUMMARY ---")
    print(f"Best passive net APY:  {passive[0]['net_apy']:.2f}%  ({passive[0]['chain']} {passive[0]['project']} {passive[0]['symbol']})" if passive else "no passive opportunities")
    if loops:
        positive_loops = [r for r in loops if r["spread"] > 0]
        print(f"Loops with positive spread: {len(positive_loops)}/{len(loops)} enumerated")
        if positive_loops:
            print(f"Best loop net APY:     {positive_loops[0]['net_apy']:.2f}%  ({positive_loops[0]['chain']} {positive_loops[0]['plat_A']}->{positive_loops[0]['plat_B']})")


if __name__ == "__main__":
    main()
