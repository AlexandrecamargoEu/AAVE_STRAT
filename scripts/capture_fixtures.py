"""One-off: capture a small subset of DefiLlama responses for offline tests.
Run once; commit the resulting JSON in tests/fixtures/.
"""
import json
import urllib.request
from pathlib import Path


def get(url):
    req = urllib.request.Request(url, headers={"User-Agent": "codee/fixture-capture"})
    return json.loads(urllib.request.urlopen(req, timeout=40).read())


def main():
    out = Path("tests/fixtures")
    out.mkdir(parents=True, exist_ok=True)

    supply = get("https://yields.llama.fi/pools")["data"]
    raw_borrow = get("https://yields.llama.fi/lendBorrow")
    borrow = raw_borrow if isinstance(raw_borrow, list) else raw_borrow.get("data", [])

    # Keep a small but diverse subset: 6 chains, ~3 platforms each, stable assets
    keep_chains = {"BSC", "Ethereum", "Base", "Arbitrum", "Mantle", "Solana"}
    keep_assets = {"USDT", "USDC", "USD1", "DAI", "GHO", "USDE", "PYUSD"}

    supply_subset = [
        p for p in supply
        if p.get("chain") in keep_chains
        and (p.get("symbol") or "").upper() in keep_assets
        and (p.get("tvlUsd") or 0) >= 500_000
    ][:120]

    keep_uuids = {p["pool"] for p in supply_subset}
    borrow_subset = [b for b in borrow if b.get("pool") in keep_uuids]

    (out / "defillama_pools_sample.json").write_text(json.dumps({"data": supply_subset}, indent=2))
    (out / "defillama_lendborrow_sample.json").write_text(json.dumps(borrow_subset, indent=2))

    print(f"supply: {len(supply_subset)} | borrow: {len(borrow_subset)}")


if __name__ == "__main__":
    main()
