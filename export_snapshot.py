"""
Export a full, shareable snapshot of DefiLlama lending pool data.

Built to answer Paul's question: "snapshot of all results when pinging lending
pool options — no positive results seems almost impossible."

Generates (in snapshots/):
  1. pools_full_<ts>.csv        — every filtered stable lending pool, raw rates
  2. spreads_per_asset_<ts>.csv — MOST GENEROUS spread: best supply vs cheapest
                                   borrow per (chain, asset), across all platforms
  3. loops_all_<ts>.csv         — every ping-pong loop enumerated, sorted by spread
  4. rewards_global_<ts>.csv    — all reward-paying lending pools, any chain
  5. SNAPSHOT_<ts>.md           — human-readable summary for sharing

No chain/project whitelist — shows the complete picture so the data speaks for itself.
"""
import csv
import json
import os
import urllib.request
from collections import defaultdict
from datetime import datetime, timezone
from itertools import combinations

STABLE_SYMBOLS = {
    "USDT", "USDC", "USD1", "USDE", "FDUSD", "DAI", "USDS", "USDC.E", "USDC.B",
    "PYUSD", "GHO", "CRVUSD", "FRAX", "TUSD", "LUSD", "SUSDE", "AUSD", "USDD",
    "USDX", "USDB", "DOLA", "MIM", "USR", "RLUSD", "DEUSD", "USDQ", "USDG",
}
MIN_TVL_USD = 1_000_000

OUT_DIR = "snapshots"
TS = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M")
TS_HUMAN = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")


def _fetch_json(url):
    req = urllib.request.Request(url, headers={"User-Agent": "codee-snapshot/1.0"})
    with urllib.request.urlopen(req, timeout=40) as r:
        return json.loads(r.read())


def fetch_pools():
    print("Fetching /pools (supply) ...")
    supply = _fetch_json("https://yields.llama.fi/pools")["data"]
    print(f"  -> {len(supply):,} supply rows")
    print("Fetching /lendBorrow (borrow) ...")
    raw = _fetch_json("https://yields.llama.fi/lendBorrow")
    borrow = raw if isinstance(raw, list) else raw.get("data", [])
    print(f"  -> {len(borrow):,} borrow rows")

    borrow_by_pool = {b["pool"]: b for b in borrow}
    merged = []
    for p in supply:
        b = borrow_by_pool.get(p.get("pool"))
        if b is not None:
            p["apyBaseBorrow"] = b.get("apyBaseBorrow")
            p["apyRewardBorrow"] = b.get("apyRewardBorrow")
            p["ltv"] = b.get("ltv")
            p["totalSupplyUsd"] = b.get("totalSupplyUsd")
            p["totalBorrowUsd"] = b.get("totalBorrowUsd")
            p["_has_borrow"] = True
        else:
            p["_has_borrow"] = False
        merged.append(p)
    n_full = sum(1 for p in merged if p["_has_borrow"])
    print(f"  -> {n_full:,} pools with supply+borrow joined\n")
    return merged


def is_stable_lending(p):
    return (
        (p.get("symbol") or "").upper() in STABLE_SYMBOLS
        and (p.get("tvlUsd") or 0) >= MIN_TVL_USD
        and p.get("_has_borrow")
        and p.get("apyBaseBorrow") is not None
    )


def f(x):
    return round(x, 4) if isinstance(x, (int, float)) else x


def write_pools_full(pools):
    path = os.path.join(OUT_DIR, f"pools_full_{TS}.csv")
    fields = ["chain", "project", "symbol", "tvlUsd", "apyBase", "apyReward",
              "apyBaseBorrow", "apyRewardBorrow", "ltv", "totalSupplyUsd",
              "totalBorrowUsd", "utilization", "pool"]
    with open(path, "w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh)
        w.writerow(fields)
        for p in sorted(pools, key=lambda x: (x["chain"], x["symbol"], x["project"])):
            ts_, tb = p.get("totalSupplyUsd"), p.get("totalBorrowUsd")
            util = (tb / ts_) if (ts_ and tb) else None
            w.writerow([
                p["chain"], p["project"], p["symbol"], f(p.get("tvlUsd")),
                f(p.get("apyBase") or 0), f(p.get("apyReward") or 0),
                f(p.get("apyBaseBorrow") or 0), f(p.get("apyRewardBorrow") or 0),
                f(p.get("ltv")), f(ts_), f(tb), f(util), p.get("pool"),
            ])
    return path, len(pools)


def write_spreads_per_asset(pools):
    """
    MOST GENEROUS positive-spread search:
    for each (chain, asset), best supply rate anywhere minus cheapest borrow
    rate anywhere (different platform). Uses base+reward as-is (NO LAV discount)
    to be maximally favorable. This is the strongest case for 'positive exists'.
    """
    by_ca = defaultdict(list)
    for p in pools:
        by_ca[(p["chain"], p["symbol"].upper())].append(p)

    rows = []
    for (chain, asset), pls in by_ca.items():
        if len(pls) < 2:
            continue
        best_sup = max(pls, key=lambda x: (x.get("apyBase") or 0) + (x.get("apyReward") or 0))
        # cheapest borrow on a DIFFERENT platform
        others = [x for x in pls if x["project"] != best_sup["project"]]
        if not others:
            continue
        cheap_bor = min(others, key=lambda x: max(0, (x.get("apyBaseBorrow") or 0) - (x.get("apyRewardBorrow") or 0)))
        sup = (best_sup.get("apyBase") or 0) + (best_sup.get("apyReward") or 0)
        bor = max(0, (cheap_bor.get("apyBaseBorrow") or 0) - (cheap_bor.get("apyRewardBorrow") or 0))
        rows.append({
            "chain": chain, "asset": asset,
            "supply_platform": best_sup["project"], "supply_apy": sup,
            "borrow_platform": cheap_bor["project"], "borrow_apr": bor,
            "raw_spread": sup - bor,
        })
    rows.sort(key=lambda r: r["raw_spread"], reverse=True)

    path = os.path.join(OUT_DIR, f"spreads_per_asset_{TS}.csv")
    with open(path, "w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh)
        w.writerow(["chain", "asset", "supply_platform", "supply_apy",
                    "borrow_platform", "borrow_apr", "raw_spread_pct"])
        for r in rows:
            w.writerow([r["chain"], r["asset"], r["supply_platform"], f(r["supply_apy"]),
                        r["borrow_platform"], f(r["borrow_apr"]), f(r["raw_spread"])])
    return path, rows


def write_loops_all(pools):
    """Every ping-pong loop (supply X on A, borrow Y on A, supply Y on B, borrow X on B)."""
    by_chain = defaultdict(dict)
    for p in pools:
        by_chain[p["chain"]][(p["project"], p["symbol"].upper())] = p

    rows = []
    for chain, pc in by_chain.items():
        platforms = sorted({k[0] for k in pc})
        assets = sorted({k[1] for k in pc})
        if len(platforms) < 2 or len(assets) < 2:
            continue
        for pa, pb in combinations(platforms, 2):
            for ax, ay in combinations(assets, 2):
                sX, bY = pc.get((pa, ax)), pc.get((pa, ay))
                sY, bX = pc.get((pb, ay)), pc.get((pb, ax))
                if not all([sX, bY, sY, bX]):
                    continue
                sup = ((sX.get("apyBase") or 0) + (sX.get("apyReward") or 0)
                       + (sY.get("apyBase") or 0) + (sY.get("apyReward") or 0)) / 2
                bor = (max(0, (bY.get("apyBaseBorrow") or 0) - (bY.get("apyRewardBorrow") or 0))
                       + max(0, (bX.get("apyBaseBorrow") or 0) - (bX.get("apyRewardBorrow") or 0))) / 2
                rows.append({
                    "chain": chain, "plat_A": pa, "X": ax, "plat_B": pb, "Y": ay,
                    "avg_supply": sup, "avg_borrow": bor, "spread": sup - bor,
                })
    rows.sort(key=lambda r: r["spread"], reverse=True)

    path = os.path.join(OUT_DIR, f"loops_all_{TS}.csv")
    with open(path, "w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh)
        w.writerow(["chain", "supply_plat_A", "asset_X", "borrow_plat_B", "asset_Y",
                    "avg_supply_apy", "avg_borrow_apr", "spread_pct"])
        for r in rows:
            w.writerow([r["chain"], r["plat_A"], r["X"], r["plat_B"], r["Y"],
                        f(r["avg_supply"]), f(r["avg_borrow"]), f(r["spread"])])
    return path, rows


def write_passive_supply(stable_pools):
    """Stable lending pools ranked by raw supply APY (base+reward). The clearest
    answer to 'where IS positive yield' — passive deposit, no loop, no leverage."""
    rows = sorted(
        stable_pools,
        key=lambda p: (p.get("apyBase") or 0) + (p.get("apyReward") or 0),
        reverse=True,
    )
    path = os.path.join(OUT_DIR, f"passive_supply_{TS}.csv")
    with open(path, "w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh)
        w.writerow(["chain", "project", "symbol", "apyBase", "apyReward",
                    "apyTotal", "tvlUsd"])
        for p in rows:
            base, rew = p.get("apyBase") or 0, p.get("apyReward") or 0
            w.writerow([p["chain"], p["project"], p["symbol"], f(base), f(rew),
                        f(base + rew), f(p.get("tvlUsd"))])
    return path, rows


def write_rewards_global(all_pools):
    """
    Reward-paying LENDING pools only (has borrow side). Excludes DEX/LP pools
    (aerodrome, blackhole, etc.) whose 'reward APY' is liquidity-mining on a
    token pair, not a lending supply rate — including them would be misleading.
    """
    rewarded = [p for p in all_pools
                if p.get("_has_borrow")
                and (p.get("apyReward") or 0) > 0
                and (p.get("tvlUsd") or 0) >= MIN_TVL_USD]
    rewarded.sort(key=lambda x: x.get("apyReward") or 0, reverse=True)
    path = os.path.join(OUT_DIR, f"rewards_global_{TS}.csv")
    with open(path, "w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh)
        w.writerow(["chain", "project", "symbol", "apyBase", "apyReward",
                    "apyTotal", "tvlUsd"])
        for p in rewarded:
            base, rew = p.get("apyBase") or 0, p.get("apyReward") or 0
            w.writerow([p["chain"], p["project"], p["symbol"], f(base), f(rew),
                        f(base + rew), f(p.get("tvlUsd"))])
    return path, rewarded


def main():
    os.makedirs(OUT_DIR, exist_ok=True)
    all_pools = fetch_pools()
    stable = [p for p in all_pools if is_stable_lending(p)]

    p_full, n_full = write_pools_full(stable)
    p_passive, passive = write_passive_supply(stable)
    p_spread, spreads = write_spreads_per_asset(stable)
    p_loops, loops = write_loops_all(stable)
    p_rew, rewarded = write_rewards_global(all_pools)

    # Stats — distinguish all yield pools from actual lending pools
    n_yield = len(all_pools)
    n_lending = sum(1 for p in all_pools if p.get("_has_borrow"))
    n_reward_lending = sum(1 for p in all_pools
                           if p.get("_has_borrow") and (p.get("apyReward") or 0) > 0)
    pos_spreads = [r for r in spreads if r["raw_spread"] > 0]
    pos_loops = [r for r in loops if r["spread"] > 0]

    # Markdown summary
    md = os.path.join(OUT_DIR, f"SNAPSHOT_{TS}.md")
    with open(md, "w", encoding="utf-8") as fh:
        fh.write(f"# Codee lending-pool snapshot — {TS_HUMAN}\n\n")
        fh.write(f"Source: DefiLlama `/pools` + `/lendBorrow` (joined by pool UUID). No chain/project whitelist.\n\n")
        fh.write(f"## Headline numbers\n\n")
        fh.write(f"- Total yield pools in DefiLlama feed: **{n_yield:,}**\n")
        fh.write(f"- Actual LENDING pools (have a borrow side): **{n_lending:,}**\n")
        fh.write(f"- Lending pools paying ANY supply reward (`apyReward>0`): **{n_reward_lending:,} ({100*n_reward_lending/n_lending:.1f}% of lending pools)**\n")
        fh.write(f"- Stable lending pools, TVL >= $1M (our scope): **{n_full}**\n")
        fh.write(f"- Per-asset spreads computed (most generous, NO LAV discount): **{len(spreads)}**, of which **POSITIVE: {len(pos_spreads)}**\n")
        fh.write(f"- Ping-pong loops enumerated: **{len(loops)}**, of which **POSITIVE spread: {len(pos_loops)}**\n\n")

        fh.write(f"## Passive supply — top 25 stable lending pools by APY (the positive results)\n\n")
        fh.write(f"Just deposit, no loop, no leverage. This is where positive yield clearly exists today.\n\n")
        fh.write("| Chain | Project | Asset | Base | Reward | Total APY | TVL |\n")
        fh.write("|---|---|---|---:|---:|---:|---:|\n")
        for p in passive[:25]:
            base, rew = p.get("apyBase") or 0, p.get("apyReward") or 0
            fh.write(f"| {p['chain']} | {p['project']} | {p['symbol']} | {base:.2f}% | {rew:.2f}% | "
                     f"{base+rew:.2f}% | ${(p.get('tvlUsd') or 0)/1e6:.1f}M |\n")

        fh.write(f"\n## Most generous spread per (chain, asset) — top 25\n\n")
        fh.write(f"Best supply rate anywhere minus cheapest borrow anywhere (different platform), "
                 f"using base+reward with NO discount. If this is <=0, no profitable carry exists for that asset.\n\n")
        fh.write("| Chain | Asset | Supply (plat / APY) | Borrow (plat / APR) | Raw spread |\n")
        fh.write("|---|---|---|---|---:|\n")
        for r in spreads[:25]:
            fh.write(f"| {r['chain']} | {r['asset']} | {r['supply_platform']} {r['supply_apy']:.2f}% | "
                     f"{r['borrow_platform']} {r['borrow_apr']:.2f}% | {r['raw_spread']:+.2f}% |\n")

        fh.write(f"\n## Ping-pong loops — top 25 by spread\n\n")
        fh.write("| Chain | Supply A | X | Borrow B | Y | Avg sup | Avg bor | Spread |\n")
        fh.write("|---|---|---|---|---|---:|---:|---:|\n")
        for r in loops[:25]:
            fh.write(f"| {r['chain']} | {r['plat_A']} | {r['X']} | {r['plat_B']} | {r['Y']} | "
                     f"{r['avg_supply']:.2f}% | {r['avg_borrow']:.2f}% | {r['spread']:+.2f}% |\n")

        fh.write(f"\n## Where rewards actually are — top 25 reward-paying lending pools (any chain)\n\n")
        fh.write("| Chain | Project | Asset | Base | Reward | Total | TVL |\n")
        fh.write("|---|---|---|---:|---:|---:|---:|\n")
        for p in rewarded[:25]:
            base, rew = p.get("apyBase") or 0, p.get("apyReward") or 0
            fh.write(f"| {p['chain']} | {p['project']} | {p['symbol']} | {base:.2f}% | {rew:.2f}% | "
                     f"{base+rew:.2f}% | ${(p.get('tvlUsd') or 0)/1e6:.1f}M |\n")

        fh.write(f"\n## Why 'no positive loops' is expected, not a bug\n\n")
        fh.write("In a lending market WITHOUT incentive rewards, supply rate < borrow rate on every "
                 "platform (that gap is the protocol's revenue). A leveraged ping-pong LOOP pays borrow on "
                 "both legs, so it is profitable only when supply somewhere exceeds borrow elsewhere — which "
                 "requires reward tokens lifting supply / rebating borrow, or a large utilization dislocation. "
                 f"Right now {100*n_reward_lending/n_lending:.1f}% of lending pools pay any reward.\n\n")
        fh.write("**Key nuance:** positive *rate dislocations* DO exist (see the per-asset table — e.g. "
                 "dolomite USDC supply far above fluid's borrow). But most of these are best captured as "
                 "PASSIVE SUPPLY (just deposit on the high-yield platform), not as a leveraged loop. The loop "
                 "table is near-zero because the ping-pong structure pays two borrow legs. So 'no positive "
                 "loops' and 'plenty of positive passive yield' are both true at once — they are different "
                 "strategies. The CSV files contain every row for direct verification.\n")

    print("\n=== FILES WRITTEN ===")
    for path in [p_full, p_passive, p_spread, p_loops, p_rew, md]:
        print(f"  {path}")
    print(f"\nSummary: {n_lending:,} lending pools ({n_reward_lending} reward-paying) | "
          f"{n_full} stable in scope | {len(pos_spreads)} positive per-asset spreads | "
          f"{len(pos_loops)} positive loops")
    print(f"Best passive: {passive[0]['chain']} {passive[0]['project']} {passive[0]['symbol']} "
          f"{(passive[0].get('apyBase') or 0)+(passive[0].get('apyReward') or 0):.2f}%")


if __name__ == "__main__":
    main()
