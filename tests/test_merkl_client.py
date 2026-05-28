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
