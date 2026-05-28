"""Codee runtime config loader.

Loads .env via pydantic-settings, JSON config files via plain json.
Single source of truth — never read env vars or config files directly elsewhere.
"""
import json
from pathlib import Path
from pydantic_settings import BaseSettings, SettingsConfigDict


CONFIG_DIR = Path(__file__).resolve().parent
_ENV_FILE = str(CONFIG_DIR.parent / ".env")  # project-root-relative, immune to CWD


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=_ENV_FILE, env_prefix="", extra="ignore")

    CODEE_DB_PATH: str = "data/codee.db"
    CODEE_LOG_LEVEL: str = "INFO"
    SNAPSHOT_INTERVAL_MIN: int = 60
    API_HOST: str = "127.0.0.1"
    API_PORT: int = 8000
    MIN_TVL_USD: float = 1_000_000
    PRINCIPAL_DEFAULT: float = 250_000
    HOLD_HOURS_DEFAULT: int = 168
    STALENESS_BANNER_HOURS: int = 3


def _load_json(name: str):
    path = CONFIG_DIR / name
    with path.open(encoding="utf-8") as f:
        return json.load(f)


def load_stable_symbols() -> set[str]:
    return {s.upper() for s in _load_json("stable_symbols.json")}


def load_lav_buckets() -> dict:
    return _load_json("lav_buckets.json")


def load_chains() -> dict:
    return _load_json("chains.json")


def load_projects() -> dict:
    return _load_json("projects.json")


settings = Settings()
