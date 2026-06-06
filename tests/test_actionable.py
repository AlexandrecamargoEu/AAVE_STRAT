from services.pools.actionable import is_actionable

CATS = {"aave-v3": "Lending", "peapods-finance": "Yield",
        "spark-savings": "Yield", "radiant-v2": "Lending"}
OVR = {"include": ["spark-savings"], "exclude": ["radiant-v2"]}


def test_lending_category_is_actionable():
    assert is_actionable("aave-v3", CATS, OVR) is True


def test_non_lending_is_not_actionable():
    assert is_actionable("peapods-finance", CATS, OVR) is False


def test_include_override_wins_over_category():
    assert is_actionable("spark-savings", CATS, OVR) is True


def test_exclude_override_wins_over_category():
    assert is_actionable("radiant-v2", CATS, OVR) is False


def test_unknown_project_fails_open():
    # a project missing from the category map must NOT be dropped (fail-open)
    assert is_actionable("brand-new-protocol", CATS, OVR) is True


def test_empty_map_fails_open():
    assert is_actionable("peapods-finance", {}, OVR) is True


def test_real_overrides_file_loads_and_applies():
    from config.config import load_actionable_overrides
    ovr = load_actionable_overrides()
    assert "spark-savings" in ovr["include"]
    assert "radiant-v2" in ovr["exclude"]
    assert is_actionable("spark-savings", {"spark-savings": "Yield"}, ovr) is True
    assert is_actionable("radiant-v2", {"radiant-v2": "Lending"}, ovr) is False
