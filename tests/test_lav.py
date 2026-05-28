from services.rewards.lav import bucket_for_token, discount_for_token


def test_bucket_known_a():
    assert bucket_for_token("AAVE") == "A"
    assert bucket_for_token("aave") == "A"  # case-insensitive


def test_bucket_known_b():
    assert bucket_for_token("XVS") == "B"
    assert bucket_for_token("LISTA") == "B"


def test_bucket_known_c():
    assert bucket_for_token("HPL") == "C"


def test_bucket_unknown_defaults_to_b():
    assert bucket_for_token("RANDOMCOIN") == "B"
    assert bucket_for_token(None) == "B"


def test_discount_for_known_a_is_zero():
    assert discount_for_token("AAVE") == 0.0


def test_discount_for_b_is_12_5_percent():
    assert abs(discount_for_token("XVS") - 0.125) < 1e-9


def test_discount_unknown_default():
    assert abs(discount_for_token("RANDOMCOIN") - 0.125) < 1e-9
