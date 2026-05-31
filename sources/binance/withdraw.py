"""Pure parsing of Binance capital/config into a {class: {chain}} withdrawable map.
No I/O — the signed fetch lives in client.py; this is testable offline."""


def build_withdrawable_chains(coin_list: list[dict], network_map: dict, classes: list[str]) -> dict[str, set]:
    """coin_list: raw /sapi/v1/capital/config/getall entries.
    network_map: Binance network code -> DefiLlama chain name.
    classes: the starting-capital classes (Binance base-coin symbols USDC/USDT/ETH/BTC).
    Returns {class: set(withdrawable DefiLlama chains)}; unmapped codes & withdraw-disabled
    networks are skipped; coins not in `classes` are ignored."""
    out: dict[str, set] = {c: set() for c in classes}
    wanted = set(classes)
    for c in coin_list:
        coin = c.get("coin")
        if coin not in wanted:
            continue
        for net in (c.get("networkList") or []):
            if not net.get("withdrawEnable"):
                continue
            chain = network_map.get(net.get("network"))
            if chain:
                out[coin].add(chain)
    return out
