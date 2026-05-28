"""
PoC: verify whether DefiLlama under-reports Venus XVS reward APY.

Hypothesis (going in): DefiLlama shows apyReward=0 for Venus but lists XVS as a
reward token, so it must be hiding ~3% of real XVS yield.

Result: REFUTED. Venus's own API (api.venus.io) confirms supplyXvsApy=0 on every
stablecoin market right now — DefiLlama's 0 is correct. A populated rewardTokens
list only means a reward token is *configured*, not currently *emitted*.

This PoC is the evidence behind Section 2b.A of the design spec.
"""
import json
import urllib.request


def get(url):
    req = urllib.request.Request(url, headers={"User-Agent": "codee-poc/1.0"})
    return json.loads(urllib.request.urlopen(req, timeout=20).read())


def fetch_venus_core_markets():
    """Venus API paginates 20/page, 0-indexed."""
    markets, page = [], 0
    while True:
        d = get(f"https://api.venus.io/markets/core-pool?page={page}")
        markets.extend(d["result"])
        if len(markets) >= d["total"] or not d["result"]:
            break
        page += 1
    return markets


def main():
    markets = fetch_venus_core_markets()
    print(f"Venus core-pool markets: {len(markets)}\n")

    stables = {"USDT", "USDC", "USD1", "USDE", "DAI", "FDUSD", "TUSD", "LISUSD"}
    print(f"{'symbol':<8} {'supplyApy':>10} {'supplyXvsApy':>13} {'borrowApy':>10} "
          f"{'borrowXvsApy':>13} {'liquidity':>12} {'util':>6}")
    for m in markets:
        sym = (m.get("underlyingSymbol") or "").upper()
        if sym not in stables:
            continue
        sa = float(m.get("supplyApy") or 0)
        sx = float(m.get("supplyXvsApy") or 0)
        ba = float(m.get("borrowApy") or 0)
        bx = float(m.get("borrowXvsApy") or 0)
        liq = float(m.get("liquidityCents") or 0) / 100
        tb = float(m.get("totalBorrowCents") or 0) / 100
        tsup = float(m.get("totalSupplyUnderlyingCents") or 0) / 100
        util = (tb / tsup * 100) if tsup else 0
        print(f"{sym:<8} {sa:>9.3f}% {sx:>12.3f}% {ba:>9.3f}% {bx:>12.3f}% "
              f"${liq/1e6:>9.2f}M {util:>5.1f}%")

    any_xvs = [m for m in markets
               if float(m.get("supplyXvsApy") or 0) > 0 or float(m.get("borrowXvsApy") or 0) > 0]
    print(f"\nMarkets paying ANY XVS reward: {len(any_xvs)} of {len(markets)}")
    for m in any_xvs:
        print(f"  {m.get('underlyingSymbol')}: supplyXvs={float(m.get('supplyXvsApy') or 0):.3f}% "
              f"borrowXvs={float(m.get('borrowXvsApy') or 0):.3f}%")

    print("\nConclusion: if no stablecoin market shows supplyXvsApy>0, DefiLlama's "
          "apyReward=0 for Venus is correct, not a gap.")


if __name__ == "__main__":
    main()
