"""SQLAlchemy declarative models matching db/migrations/001_initial_schema.sql.

Models are used for type-safe inserts/queries. Schema is the source of truth —
if you change a column, change BOTH the migration SQL and this file.
"""
from sqlalchemy import Column, Integer, REAL as Real, Text
from sqlalchemy.orm import declarative_base


Base = declarative_base()


class PoolSnapshot(Base):
    __tablename__ = "pools_snapshot"
    pool_id             = Column(Text, primary_key=True)
    chain               = Column(Text, nullable=False)
    project             = Column(Text, nullable=False)
    symbol              = Column(Text, nullable=False)
    pool_meta           = Column(Text)
    tvl_usd             = Column(Real, nullable=False)
    total_supply_usd    = Column(Real)
    total_borrow_usd    = Column(Real)
    available_liquidity = Column(Real)
    debt_ceiling_usd    = Column(Real)
    utilization         = Column(Real)
    supply_apy_base     = Column(Real, nullable=False, default=0)
    supply_apy_reward   = Column(Real, nullable=False, default=0)
    reward_source       = Column(Text, nullable=False, default="defillama")
    borrow_apr_base     = Column(Real)
    borrow_apr_reward   = Column(Real)
    ltv                 = Column(Real)
    borrow_factor       = Column(Real)
    borrowable          = Column(Integer)
    reward_tokens       = Column(Text)
    underlying_tokens   = Column(Text)
    lav_uncertain       = Column(Integer, nullable=False, default=0)
    quality_flag        = Column(Text, nullable=False, default="ok")
    status              = Column(Text, nullable=False, default="active")
    updated_at          = Column(Integer, nullable=False)


class PoolHistory(Base):
    __tablename__ = "pools_history"
    pool_id             = Column(Text, primary_key=True)
    ts                  = Column(Integer, primary_key=True)
    source              = Column(Text, primary_key=True)
    tvl_usd             = Column(Real)
    total_supply_usd    = Column(Real)
    total_borrow_usd    = Column(Real)
    available_liquidity = Column(Real)
    debt_ceiling_usd    = Column(Real)
    supply_apy_base     = Column(Real)
    supply_apy_reward   = Column(Real)
    reward_source       = Column(Text)
    borrow_apr_base     = Column(Real)
    borrow_apr_reward   = Column(Real)
    utilization         = Column(Real)
    quality_flag        = Column(Text, nullable=False, default="ok")


class RateAggregate(Base):
    __tablename__ = "rate_aggregates"
    pool_id                  = Column(Text, primary_key=True)
    window                   = Column(Text, primary_key=True)
    supply_apy_effective_avg = Column(Real)
    borrow_apr_effective_avg = Column(Real)
    utilization_avg          = Column(Real)
    tvl_avg                  = Column(Real)
    sample_count             = Column(Integer, nullable=False)
    computed_at              = Column(Integer, nullable=False)
