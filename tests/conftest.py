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
