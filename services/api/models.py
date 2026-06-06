"""Pydantic response schemas — the contract between API and dashboard."""
from pydantic import BaseModel


class HealthResponse(BaseModel):
    status: str                    # 'ok' | 'degraded' | 'warming_up'
    last_snapshot_at: int | None
    snapshot_age_s: int | None
    stale: bool
    pool_count_total: int          # all pools in pools_snapshot (active + inactive)
    pool_count_in_scope: int       # only status='active' pools
    join_rate: float | None
    lav_coverage_pct: float | None  # share of in-scope pools with lav_uncertain=0
    quality_flags: dict[str, int]
    reward_active_pools: int
    last_error: str | None = None


class PassiveRoute(BaseModel):
    chain: str
    project: str
    symbol: str
    effective_apy: float
    tvl_usd: float
    quality_flag: str
    entry_asset_classes: list[str] = []
    binance_withdrawable: bool | None = None
    incentive_conditional: bool = False
    actionable: bool = True               # False = not a plain lending deposit (T2)


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
    entry_asset_classes: list[str] = []
    binance_withdrawable: bool | None = None


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
    available_liquidity_usd: float | None = None
    entry_asset_classes: list[str] = []
    binance_withdrawable: bool | None = None


class PoolHistoryPoint(BaseModel):
    ts: int
    source: str
    supply_apy_base: float | None
    supply_apy_reward: float | None
    borrow_apr_base: float | None
    borrow_apr_reward: float | None
    tvl_usd: float | None
    utilization: float | None


class PoolSummary(BaseModel):
    """Compact row for pool browser (GET /pools/snapshot)."""
    pool_id: str
    chain: str
    project: str
    symbol: str
    tvl_usd: float
    supply_apy_base: float
    supply_apy_reward: float
    borrow_apr_base: float | None
    borrow_apr_reward: float | None
    quality_flag: str
    lav_uncertain: int


class PoolsSnapshotPage(BaseModel):
    total: int
    offset: int
    limit: int
    items: list[PoolSummary]


class RewardsCoverageResponse(BaseModel):
    pools_in_scope: int
    pools_with_classified_reward: int        # lav_uncertain = 0
    lav_coverage_pct: float | None           # = classified / in_scope
    pools_with_merkl_borrow_rebate: int      # reward_source = 'merkl'
    reward_active_pools: int                 # supply_apy_reward > 0


class ChainSummary(BaseModel):
    chain: str
    pool_count: int
    avg_supply_apy_effective: float | None
    avg_borrow_apr_effective: float | None
    avg_spread: float | None


class MultiHopNode(BaseModel):
    chain: str
    project: str
    symbol: str
    supply_apy: float | None = None       # effective supply APY of this leg


class MultiHopBorrow(BaseModel):
    symbol: str                            # borrowed asset (normalized)
    borrow_apr: float                      # effective borrow APR paid on that leg


class MultiHopRoute(BaseModel):
    path: list[MultiHopNode]
    borrows: list[MultiHopBorrow] = []     # one per transition (len == hops-1)
    net_apy: float
    hops: int
    bridge_cost_usd: float
    min_liquidity_usd: float
    entry_asset_classes: list[str] = []
    incentive_conditional: bool = False   # any leg has a Self-gated incentive
