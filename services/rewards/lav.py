"""LAV (liquid-at-vesting) bucket lookup.

Buckets are static config-driven (see config/lav_buckets.json).
Discount returned here is the bucket discount — applied as `eff_reward = raw_reward * (1 - discount)`.

Phase 1a uses bucket-fixed % only. Phase 2 will extend with dynamic sell-liquidity
component; for now treat unknown tokens as bucket B (conservative-ish default).
"""
from functools import lru_cache

from config.config import load_lav_buckets


@lru_cache(maxsize=1)
def _lav_index() -> tuple[dict[str, str], dict[str, float], str, float]:
    """Returns: (symbol -> bucket, bucket -> discount, default_bucket, default_discount)."""
    raw = load_lav_buckets()
    sym_to_bucket: dict[str, str] = {}
    bucket_to_discount: dict[str, float] = {}
    for bucket, payload in raw["buckets"].items():
        bucket_to_discount[bucket] = float(payload["discount_pct"])
        for sym in payload.get("tokens", []):
            sym_to_bucket[sym.upper()] = bucket
    return sym_to_bucket, bucket_to_discount, raw["default_bucket"], float(raw["default_discount_pct"])


def bucket_for_token(symbol: str | None) -> str:
    if not symbol:
        _, _, default_bucket, _ = _lav_index()
        return default_bucket
    sym_to_bucket, _, default_bucket, _ = _lav_index()
    return sym_to_bucket.get(symbol.upper(), default_bucket)


def discount_for_token(symbol: str | None) -> float:
    sym_to_bucket, bucket_to_discount, default_bucket, default_discount = _lav_index()
    if not symbol:
        return default_discount
    bucket = sym_to_bucket.get(symbol.upper())
    if bucket is None:
        return default_discount
    return bucket_to_discount[bucket]
