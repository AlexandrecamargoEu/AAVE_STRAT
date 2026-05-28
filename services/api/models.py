"""Pydantic response schemas — the contract between API and dashboard."""
from pydantic import BaseModel


class HealthResponse(BaseModel):
    status: str                    # 'ok' | 'degraded' | 'warming_up'
    last_snapshot_at: int | None
    snapshot_age_s: int | None
    stale: bool
    pool_count_in_scope: int
    join_rate: float | None
    quality_flags: dict[str, int]
    reward_active_pools: int       # spec regime signal


class PassiveRoute(BaseModel):
    chain: str
    project: str
    symbol: str
    effective_apy: float
    tvl_usd: float
    quality_flag: str


class LoopRoute(BaseModel):
    chain: str
    plat_a: str
    asset_x: str
    plat_b: str
    asset_y: str
    avg_supply: float
    avg_borrow: float
    spread: float
    leverage: float
    gross_apy: float
    min_tvl_usd: float


class CrossChainRoute(BaseModel):
    symbol: str
    supply_chain: str
    supply_project: str
    supply_apy: float
    borrow_chain: str
    borrow_project: str
    borrow_apr: float
    spread: float
    pre_bridge_ceiling: bool = True


class PoolHistoryPoint(BaseModel):
    ts: int
    source: str
    supply_apy_base: float | None
    supply_apy_reward: float | None
    borrow_apr_base: float | None
    borrow_apr_reward: float | None
    tvl_usd: float | None
    utilization: float | None
