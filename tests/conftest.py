"""Shared pytest config + fixtures."""
import json
from pathlib import Path
import pytest

FIXTURE_DIR = Path(__file__).parent / "fixtures"


def load_fixture(name: str):
    path = FIXTURE_DIR / name
    with path.open(encoding="utf-8") as f:
        return json.load(f)


@pytest.fixture
def fixture_loader():
    return load_fixture


@pytest.fixture(autouse=True)
def _isolate_cache_settings(tmp_path, monkeypatch):
    """Point all JSON-cache settings at non-existent tmp files so tests never read
    real caches the ingestor may have written locally (data/*.json)."""
    from config.config import settings
    monkeypatch.setattr(settings, "BINANCE_WITHDRAW_CACHE", str(tmp_path / "_bw_isolated.json"), raising=False)
    monkeypatch.setattr(settings, "ACI_INCENTIVES_CACHE", str(tmp_path / "_aci_isolated.json"), raising=False)
    monkeypatch.setattr(settings, "PROTOCOL_CATEGORIES_CACHE", str(tmp_path / "_cats_isolated.json"), raising=False)
