import pytest
from sources.defillama.client import DefiLlamaClient, join_supply_borrow


def test_join_supply_borrow_attaches_matching_borrow(fixture_loader):
    supply = fixture_loader("defillama_pools_sample.json")["data"]
    borrow = fixture_loader("defillama_lendborrow_sample.json")
    joined = join_supply_borrow(supply, borrow)
    # Every joined record has a populated apyBaseBorrow OR explicitly None
    assert all("apyBaseBorrow" in p for p in joined)


def test_join_borrow_data_attached_correctly(fixture_loader):
    supply = fixture_loader("defillama_pools_sample.json")["data"]
    borrow = fixture_loader("defillama_lendborrow_sample.json")
    joined = join_supply_borrow(supply, borrow)
    # Find a pool that was in both feeds (UUID overlap)
    borrow_uuids = {b["pool"] for b in borrow}
    pools_with_borrow_side = [p for p in joined if p["pool"] in borrow_uuids]
    assert len(pools_with_borrow_side) > 0
    # That pool must have apyBaseBorrow filled in (matched the borrow record)
    sample = pools_with_borrow_side[0]
    borrow_rec = next(b for b in borrow if b["pool"] == sample["pool"])
    assert sample["apyBaseBorrow"] == borrow_rec.get("apyBaseBorrow")


def test_join_pool_without_borrow_side_keeps_supply_with_none(fixture_loader):
    supply = fixture_loader("defillama_pools_sample.json")["data"]
    # filter to one with no borrow record
    borrow = []
    joined = join_supply_borrow(supply, borrow)
    assert len(joined) == len(supply)
    assert all(p.get("apyBaseBorrow") is None for p in joined)


@pytest.mark.skip(reason="network — only run locally as smoke test")
async def test_live_fetch_pools():
    client = DefiLlamaClient()
    pools = await client.fetch_pools_supply()
    assert len(pools) > 1000
