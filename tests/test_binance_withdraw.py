from sources.binance.withdraw import build_withdrawable_chains

NETMAP = {"ETH": "Ethereum", "ARBITRUM": "Arbitrum", "BSC": "BSC"}
CLASSES = ["USDC", "USDT", "ETH", "BTC"]

def _coin(coin, nets):
    return {"coin": coin, "networkList": [{"network": n, "withdrawEnable": en} for n, en in nets]}

def test_build_maps_withdrawable_networks_to_chains():
    raw = [
        _coin("USDC", [("ETH", True), ("ARBITRUM", True), ("BSC", False)]),
        _coin("ETH",  [("ETH", True), ("ARBITRUM", True)]),
        _coin("DOGE", [("BSC", True)]),          # not a class -> ignored
    ]
    out = build_withdrawable_chains(raw, NETMAP, CLASSES)
    assert out["USDC"] == {"Ethereum", "Arbitrum"}   # BSC excluded (withdrawEnable False)
    assert out["ETH"] == {"Ethereum", "Arbitrum"}
    assert out["USDT"] == set() and out["BTC"] == set()

def test_build_ignores_unmapped_network_codes():
    raw = [_coin("USDC", [("ETH", True), ("FANTOM", True)])]   # FANTOM not in NETMAP
    out = build_withdrawable_chains(raw, NETMAP, CLASSES)
    assert out["USDC"] == {"Ethereum"}

def test_build_empty_on_empty_input():
    assert build_withdrawable_chains([], NETMAP, CLASSES) == {"USDC": set(), "USDT": set(), "ETH": set(), "BTC": set()}
