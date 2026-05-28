CREATE TABLE IF NOT EXISTS pools_snapshot (
    pool_id             TEXT PRIMARY KEY,
    chain               TEXT NOT NULL,
    project             TEXT NOT NULL,
    symbol              TEXT NOT NULL,
    pool_meta           TEXT,
    tvl_usd             REAL NOT NULL,
    total_supply_usd    REAL,
    total_borrow_usd    REAL,
    available_liquidity REAL,
    debt_ceiling_usd    REAL,
    utilization         REAL,
    supply_apy_base     REAL NOT NULL DEFAULT 0,
    supply_apy_reward   REAL NOT NULL DEFAULT 0,
    reward_source       TEXT NOT NULL DEFAULT 'defillama',
    borrow_apr_base     REAL,
    borrow_apr_reward   REAL,
    ltv                 REAL,
    borrow_factor       REAL,
    borrowable          INTEGER,
    reward_tokens       TEXT,
    underlying_tokens   TEXT,
    lav_uncertain       INTEGER NOT NULL DEFAULT 0,
    quality_flag        TEXT NOT NULL DEFAULT 'ok',
    status              TEXT NOT NULL DEFAULT 'active',
    updated_at          INTEGER NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_snapshot_chain    ON pools_snapshot(chain);
CREATE INDEX IF NOT EXISTS idx_snapshot_symbol   ON pools_snapshot(symbol);
CREATE INDEX IF NOT EXISTS idx_snapshot_util     ON pools_snapshot(utilization);
CREATE INDEX IF NOT EXISTS idx_snapshot_loopable ON pools_snapshot(chain, symbol) WHERE borrow_apr_base IS NOT NULL;

CREATE TABLE IF NOT EXISTS pools_history (
    pool_id             TEXT NOT NULL,
    ts                  INTEGER NOT NULL,
    source              TEXT NOT NULL,
    tvl_usd             REAL,
    total_supply_usd    REAL,
    total_borrow_usd    REAL,
    available_liquidity REAL,
    debt_ceiling_usd    REAL,
    supply_apy_base     REAL,
    supply_apy_reward   REAL,
    reward_source       TEXT,
    borrow_apr_base     REAL,
    borrow_apr_reward   REAL,
    utilization         REAL,
    quality_flag        TEXT NOT NULL DEFAULT 'ok',
    PRIMARY KEY (pool_id, ts, source)
);

CREATE INDEX IF NOT EXISTS idx_history_pool_ts ON pools_history(pool_id, ts);
CREATE INDEX IF NOT EXISTS idx_history_ts      ON pools_history(ts);

CREATE TABLE IF NOT EXISTS rate_aggregates (
    pool_id                  TEXT NOT NULL,
    window                   TEXT NOT NULL,
    supply_apy_effective_avg REAL,
    borrow_apr_effective_avg REAL,
    utilization_avg          REAL,
    tvl_avg                  REAL,
    sample_count             INTEGER NOT NULL,
    computed_at              INTEGER NOT NULL,
    PRIMARY KEY (pool_id, window)
);

-- Phase 2: not populated in 1a, schema present for forward-compat
CREATE TABLE IF NOT EXISTS reward_token_prices (
    token_id         TEXT NOT NULL,
    symbol           TEXT NOT NULL,
    ts               INTEGER NOT NULL,
    price_usd        REAL NOT NULL,
    source           TEXT NOT NULL,
    lav_bucket       TEXT,
    lav_discount_pct REAL NOT NULL DEFAULT 0.125,
    PRIMARY KEY (token_id, ts)
);
CREATE INDEX IF NOT EXISTS idx_prices_symbol_ts ON reward_token_prices(symbol, ts);
