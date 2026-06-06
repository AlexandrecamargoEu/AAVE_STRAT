import pytest
from sources.aci.parse import parse_merit_aprs
from sources.aci.client import AciClient

CHAIN_MAP = {"celo": "Celo", "ethereum": "Ethereum"}

PAYLOAD = {"currentAPR": {"actionsAPR": {
    "celo-supply-weth": 2.08,
    "self-celo-supply-weth": 2.08,
    "celo-supply-usdt": 4.23,
    "self-celo-supply-usdt": 4.23,
    "ethereum-sgho": 3.76,                    # no '-supply-' -> not a pool supply key, ignored
    "celo-supply-multiple-borrow-usdt": None, # null -> ignored
    "fantomx-supply-usdc": 9.9,               # unknown chain slug -> ignored
}}}


def test_parse_maps_chain_asset_with_merit_and_self():
    out = parse_merit_aprs(PAYLOAD, CHAIN_MAP)
    assert out[("Celo", "WETH")] == {"merit": 2.08, "self": 2.08}
    assert out[("Celo", "USDT")] == {"merit": 4.23, "self": 4.23}


def test_parse_ignores_non_supply_unknown_and_null():
    out = parse_merit_aprs(PAYLOAD, CHAIN_MAP)
    assert all(k[0] in ("Celo", "Ethereum") for k in out)
    assert ("Ethereum", "SGHO") not in out          # sgho key has no '-supply-'
    assert not any(k[1] == "USDC" for k in out)     # unknown chain slug dropped


def test_parse_empty_payload():
    assert parse_merit_aprs({}, CHAIN_MAP) == {}


async def test_client_returns_empty_on_error_shape():
    class FakeResp:
        async def __aenter__(self): return self
        async def __aexit__(self, *a): pass
        def raise_for_status(self): pass
        async def json(self): return ["not-a-dict"]
    class FakeSession:
        def get(self, url): return FakeResp()
    c = AciClient(session=FakeSession())
    assert await c.fetch_merit_aprs() == {}
