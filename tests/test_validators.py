from services.pools.validators import classify_pool, QualityFlag


def _base(**overrides):
    p = {
        "apyBase": 5.0,
        "apyReward": 0.0,
        "tvlUsd": 10_000_000,
        "totalSupplyUsd": 10_000_000,
        "totalBorrowUsd": 5_000_000,
    }
    p.update(overrides)
    return p


def test_normal_pool_is_ok():
    assert classify_pool(_base()) == QualityFlag.OK


def test_high_apy_above_50_is_needs_review():
    assert classify_pool(_base(apyBase=75.0)) == QualityFlag.NEEDS_REVIEW


def test_impossible_apy_above_10000_is_impossible():
    assert classify_pool(_base(apyBase=12000.0)) == QualityFlag.IMPOSSIBLE


def test_impossible_utilization_above_100pct():
    p = _base(totalBorrowUsd=11_000_000, totalSupplyUsd=10_000_000)
    assert classify_pool(p) == QualityFlag.IMPOSSIBLE


def test_high_utilization_92pct_or_above_flags():
    p = _base(totalBorrowUsd=9_300_000, totalSupplyUsd=10_000_000)  # 93%
    assert classify_pool(p) == QualityFlag.HIGH_UTILIZATION


def test_negative_rate_invalid_is_impossible():
    assert classify_pool(_base(apyBase=-5.0)) == QualityFlag.IMPOSSIBLE


def test_severity_ordering_impossible_beats_high_util():
    """If both impossible-APY and high-util flags trip, IMPOSSIBLE wins."""
    p = _base(apyBase=20000.0, totalBorrowUsd=9_500_000, totalSupplyUsd=10_000_000)
    assert classify_pool(p) == QualityFlag.IMPOSSIBLE
