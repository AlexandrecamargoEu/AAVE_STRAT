"""
Re-run the ping-pong loop ranking with Merkl borrow rebates overlaid.

Proves the impact of the verified gap (2b.A): DefiLlama misses borrow-side
incentives. We fetch Merkl BORROW opportunities and subtract the rebate from
each matched pool's borrow cost, then compare loops BEFORE vs AFTER.

Match key: (chain name, protocol, asset symbol).
Rebate applied at face value (pre-LAV) — most generous; LAV would haircut it.
"""
import json
import urllib.request
from collections import defaultdict
from itertools import combinations

STABLE_SYMBOLS = {
    "USDT", "USDC", "USD1", "USDE", "FDUSD", "DAI", "USDS", "USDC.E", "PYUSD",
    "GHO", "CRVUSD", "FRAX", "TUSD", "LUSD", "SUSDE", "AUSD", "USDT0", "USDTB",
    "RLUSD", "USDG",
}
MIN_TVL_USD = 1_000_000
LTV_PER_ITER = 0.855
N_ITER = 10
LEVERAGE = sum(LTV_PER_ITER ** i for i in range(N_ITER))
PRINCIPAL = 250_000
HOLD_H = 24 * 7


def get(url):
    req = urllib.request.Request(url, headers={"User-Agent": "codee-poc/1.0"})
    return json.loads(urllib.request.urlopen(req, timeout=40).read())


def norm_chain(s):
    return (s or "").lower().replace(" ", "").replace("mainnet", "")


def norm_proto(s):
    return (s or "").lower()


def fetch_defillama():
    supply = get("https://yields.llama.fi/pools")["data"]
    raw = get("https://yields.llama.fi/lendBorrow")
    borrow = raw if isinstance(raw, list) else raw.get("data", [])
    bbp = {b["pool"]: b for b in borrow}
    merged = []
    for p in supply:
        b = bbp.get(p.get("pool"))
        if b is None:
            continue
        p["apyBaseBorrow"] = b.get("apyBaseBorrow")
        p["apyRewardBorrow"] = b.get("apyRewardBorrow")
        merged.append(p)
    return merged


def fetch_merkl_borrow_rebates():
    """Return {(chain_norm, proto_norm, symbol): apr_pct} for LIVE BORROW opps."""
    rebates = {}
    page = 0
    while True:
        d = get(f"https://api.merkl.xyz/v4/opportunities?action=BORROW&status=LIVE&items=100&page={page}")
        if not d:
            break
        for o in d:
            chain = norm_chain((o.get("chain") or {}).get("name"))
            proto = norm_proto((o.get("protocol") or {}).get("id"))
            toks = o.get("tokens") or []
            apr = o.get("apr") or 0
            for t in toks:
                sym = (t.get("symbol") or "").upper()
                if sym:
                    key = (chain, proto, sym)
                    rebates[key] = max(rebates.get(key, 0), apr)
        if len(d) < 100:
            break
        page += 1
        if page > 5:
            break
    return rebates


def match_rebate(pool, rebates):
    chain = norm_chain(pool.get("chain"))
    proto_full = norm_proto(pool.get("project"))
    sym = (pool.get("symbol") or "").upper()
    # try exact, then protocol-prefix variants (aave-v3 -> aave)
    for proto in {proto_full, proto_full.split("-")[0]}:
        r = rebates.get((chain, proto, sym))
        if r is not None:
            return r
    return None


def eff_supply(p):
    return (p.get("apyBase") or 0) + (p.get("apyReward") or 0)


def eff_borrow(p, rebates=None):
    base = p.get("apyBaseBorrow") or 0
    rebate = p.get("apyRewardBorrow") or 0
    if rebates is not None:
        m = match_rebate(p, rebates)
        if m is not None:
            rebate = max(rebate, m)  # use Merkl if DefiLlama missed it
    return max(0.0, base - rebate)


def enumerate_loops(pools, rebates=None):
    by_chain = defaultdict(dict)
    for p in pools:
        by_chain[p["chain"]][(p["project"], p["symbol"].upper())] = p
    out = []
    for chain, pc in by_chain.items():
        plats = sorted({k[0] for k in pc})
        assets = sorted({k[1] for k in pc})
        if len(plats) < 2 or len(assets) < 2:
            continue
        for pa, pb in combinations(plats, 2):
            for ax, ay in combinations(assets, 2):
                sX, bY = pc.get((pa, ax)), pc.get((pa, ay))
                sY, bX = pc.get((pb, ay)), pc.get((pb, ax))
                if not all([sX, bY, sY, bX]):
                    continue
                sup = (eff_supply(sX) + eff_supply(sY)) / 2
                bor = (eff_borrow(bY, rebates) + eff_borrow(bX, rebates)) / 2
                spread = sup - bor
                gross = LEVERAGE * sup - (LEVERAGE - 1) * bor
                out.append({"chain": chain, "pa": pa, "x": ax, "pb": pb, "y": ay,
                            "sup": sup, "bor": bor, "spread": spread, "gross": gross})
    return sorted(out, key=lambda r: r["spread"], reverse=True)


def main():
    pools = [p for p in fetch_defillama()
             if (p.get("symbol") or "").upper() in STABLE_SYMBOLS
             and (p.get("tvlUsd") or 0) >= MIN_TVL_USD
             and p.get("apyBaseBorrow") is not None]
    rebates = fetch_merkl_borrow_rebates()
    print(f"Stable lending pools: {len(pools)} | Merkl BORROW rebates: {len(rebates)}\n")

    before = enumerate_loops(pools, rebates=None)
    after = enumerate_loops(pools, rebates=rebates)

    pos_before = [r for r in before if r["spread"] > 0]
    pos_after = [r for r in after if r["spread"] > 0]

    print(f"Loops enumerated: {len(before)}")
    print(f"  POSITIVE spread BEFORE Merkl (DefiLlama only): {len(pos_before)}")
    print(f"  POSITIVE spread AFTER  Merkl (rebates overlaid): {len(pos_after)}")
    print()

    print("=== TOP 12 loops AFTER Merkl overlay ===")
    print(f"{'chain':<10} {'A':<14} {'X':<7} {'B':<14} {'Y':<7} {'sup':>6} {'bor':>6} {'spread':>7} {'grossAPY':>9}")
    for r in after[:12]:
        print(f"{r['chain'][:10]:<10} {r['pa'][:14]:<14} {r['x']:<7} {r['pb'][:14]:<14} {r['y']:<7} "
              f"{r['sup']:>5.2f}% {r['bor']:>5.2f}% {r['spread']:>+6.2f}% {r['gross']:>8.2f}%")

    # which flipped from negative to positive
    before_map = {(r["chain"], r["pa"], r["x"], r["pb"], r["y"]): r["spread"] for r in before}
    flipped = []
    for r in pos_after:
        k = (r["chain"], r["pa"], r["x"], r["pb"], r["y"])
        if before_map.get(k, 0) <= 0:
            flipped.append((r, before_map.get(k, 0)))
    print(f"\n=== Loops that FLIPPED negative->positive thanks to Merkl: {len(flipped)} ===")
    for r, old in flipped[:12]:
        print(f"  {r['chain'][:10]:<10} {r['pa'][:12]:<12} {r['x']:<6} / {r['pb'][:12]:<12} {r['y']:<6} "
              f"{old:>+6.2f}% -> {r['spread']:>+6.2f}%")

    # ---- CROSS-CHAIN carry (where Merkl rebates actually unlock value) ----
    # Per asset: highest supply APY anywhere vs cheapest NET borrow anywhere (with Merkl).
    # Ignores bridge cost/time (Phase 2 models that) — this is the theoretical ceiling.
    print(f"\n=== CROSS-CHAIN carry per asset (max supply anywhere - min net borrow anywhere, w/ Merkl) ===")
    by_asset_sup = defaultdict(list)
    by_asset_bor = defaultdict(list)
    for p in pools:
        sym = p["symbol"].upper()
        by_asset_sup[sym].append((eff_supply(p), p["chain"], p["project"]))
        by_asset_bor[sym].append((eff_borrow(p, rebates), p["chain"], p["project"]))
    print(f"{'asset':<7} {'best supply (chain/proto)':<34} {'cheapest net borrow (chain/proto)':<38} {'x-chain spread':>14}")
    xrows = []
    for sym in by_asset_sup:
        if sym not in by_asset_bor:
            continue
        bs = max(by_asset_sup[sym]); cb = min(by_asset_bor[sym])
        # require different chain (it's a cross-chain carry)
        if bs[1] == cb[1]:
            continue
        xrows.append((sym, bs, cb, bs[0] - cb[0]))
    for sym, bs, cb, sp in sorted(xrows, key=lambda x: x[3], reverse=True)[:12]:
        print(f"{sym:<7} {bs[0]:>5.2f}% {bs[1][:12]+'/'+bs[2][:12]:<27} {cb[0]:>5.2f}% {cb[1][:12]+'/'+cb[2][:14]:<31} {sp:>+13.2f}%")


if __name__ == "__main__":
    main()
