import pytest
from sources.merkl.client import MerklClient


def test_borrow_opps_have_expected_shape(fixture_loader):
    opps = fixture_loader("merkl_borrow_sample.json")
    assert isinstance(opps, list)
    assert len(opps) > 0
    o = opps[0]
    for key in ("chain", "protocol", "tokens", "action", "apr"):
        assert key in o, f"missing key {key} in Merkl opportunity"
    assert o["action"] == "BORROW"


def test_extract_match_keys_from_opportunity(fixture_loader):
    """We will match by (chain.name normalized, protocol.id, tokens[].symbol)."""
    opps = fixture_loader("merkl_borrow_sample.json")
    sample = opps[0]
    chain_name = sample["chain"]["name"]
    proto_id = sample["protocol"]["id"]
    syms = [t.get("symbol") for t in sample.get("tokens") or [] if t.get("symbol")]
    assert isinstance(chain_name, str) and chain_name
    assert isinstance(proto_id, str) and proto_id
    assert len(syms) > 0


async def test_fetch_supply_opportunities_paginates_lend(monkeypatch):
    """fetch_supply_opportunities pulls action=LEND pages until a short page."""
    pages = {
        0: [{"id": i} for i in range(100)],   # full page -> keep going
        1: [{"id": 100}],                      # short page -> stop
    }
    captured_urls = []

    class FakeResp:
        def __init__(self, data): self._d = data
        async def __aenter__(self): return self
        async def __aexit__(self, *a): pass
        def raise_for_status(self): pass
        async def json(self): return self._d

    class FakeSession:
        def get(self, url):
            captured_urls.append(url)
            page = int(url.split("page=")[1])
            return FakeResp(pages.get(page, []))

    c = MerklClient(session=FakeSession())
    out = await c.fetch_supply_opportunities()
    assert len(out) == 101
    assert all("action=LEND" in u for u in captured_urls)
    assert "status=LIVE" in captured_urls[0] and "items=100" in captured_urls[0]
