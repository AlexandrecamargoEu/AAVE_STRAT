import pytest
from sources.binance.client import BinanceClient


async def test_fetch_returns_empty_without_credentials():
    c = BinanceClient(api_key="", api_secret="")
    async with c:
        assert await c.fetch_capital_config() == []


def test_sign_appends_hmac_signature():
    c = BinanceClient(api_key="k", api_secret="secret")
    signed = c._sign({"timestamp": 1, "recvWindow": 5000})
    assert "signature=" in signed
    assert signed.startswith("timestamp=1&recvWindow=5000")
    # deterministic HMAC-SHA256 of the query under key 'secret'
    import hmac, hashlib
    expect = hmac.new(b"secret", b"timestamp=1&recvWindow=5000", hashlib.sha256).hexdigest()
    assert signed.endswith("&signature=" + expect)
