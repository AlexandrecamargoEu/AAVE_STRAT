"""Codee runtime config loader.

Loads .env via pydantic-settings, JSON config files via plain json.
Single source of truth — never read env vars or config files directly elsewhere.
"""
import json
from functools import lru_cache
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
    MIN_TVL_USD: float = 10_000              # env: CODEE_MIN_TVL_USD (dust floor / slider min)
    PRINCIPAL_DEFAULT: float = 250_000
    HOLD_HOURS_DEFAULT: int = 168
    STALENESS_BANNER_HOURS: int = 3
    BINANCE_WITHDRAW_CACHE: str = str(CONFIG_DIR.parent / "data" / "binance_withdraw.json")
    ACI_INCENTIVES_CACHE: str = str(CONFIG_DIR.parent / "data" / "aci_incentives.json")
    PROTOCOL_CATEGORIES_CACHE: str = str(CONFIG_DIR.parent / "data" / "protocol_categories.json")


# Stylized glyphs some protocols use in tickers that must be folded back to ASCII
# before matching/grouping. DefiLlama lists Tether as USD₮ / USD₮0 (₮ = U+20AE),
# which would never equal "USDT"/"USDT0" under a plain .upper() compare.
_SYMBOL_GLYPHS = {"₮": "T"}   # ₮ -> T


def normalize_symbol(sym: str | None) -> str:
    """Canonicalize a pool ticker for matching/grouping ONLY (display keeps the
    original). Folds known stylized glyphs (e.g. ₮ -> T) and uppercases. Punctuation
    is preserved on purpose — USDC.E and BTC.B are real symbols in our config."""
    if not sym:
        return ""
    for glyph, repl in _SYMBOL_GLYPHS.items():
        sym = sym.replace(glyph, repl)
    return sym.upper()


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


def load_asset_classes() -> dict:
    return _load_json("asset_classes.json")


def load_binance_networks() -> dict:
    return _load_json("binance_networks.json")


def load_aci_chains() -> dict:
    return _load_json("aci_chains.json")


def load_actionable_overrides() -> dict:
    return _load_json("actionable_overrides.json")


@lru_cache(maxsize=1)
def _ticker_to_class() -> dict[str, str]:
    rev = {}
    for cls, tickers in load_asset_classes().items():
        for t in tickers:
            rev[normalize_symbol(t)] = cls
    return rev


def asset_class(symbol: str | None) -> str | None:
    """Binance starting-capital class (USDC/USDT/ETH/BTC) for a ticker, or None.
    Matches on the normalized symbol (folds the ₮ glyph, etc.)."""
    if not symbol:
        return None
    return _ticker_to_class().get(normalize_symbol(symbol))


settings = Settings()
