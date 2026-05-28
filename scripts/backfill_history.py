"""Pull 90-day daily history for every in-scope pool via DefiLlama /chart/{uuid}.

Marks rows with source='chart_daily' so they coexist with 60-min 'live' samples
(spec 7 — composite PK includes source).
"""
import asyncio
import logging
import time

from db.sqlite_client import SqliteClient
from sources.defillama.client import DefiLlamaClient


_INSERT = """
INSERT OR IGNORE INTO pools_history
  (pool_id, ts, source, tvl_usd, supply_apy_base, supply_apy_reward, utilization)
VALUES (?, ?, 'chart_daily', ?, ?, ?, ?)
"""


async def main():
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s | %(message)s")
    log = logging.getLogger("backfill")

    db = SqliteClient()
    await db.connect()

    rows = await db.fetch_all(
        "SELECT pool_id FROM pools_snapshot WHERE status='active'"
    )
    pool_ids = [r[0] for r in rows]
    log.info("backfilling %d pools", len(pool_ids))

    async with DefiLlamaClient() as dl:
        for i, pool_id in enumerate(pool_ids, 1):
            try:
                chart = await dl.fetch_pool_history(pool_id)
            except Exception as e:
                log.warning("pool %s failed: %s", pool_id, e)
                continue
            for point in chart:
                ts_str = point.get("timestamp")
                if not ts_str:
                    continue
                ts_int = int(time.mktime(time.strptime(ts_str[:19], "%Y-%m-%dT%H:%M:%S")))
                await db.execute(_INSERT, (
                    pool_id, ts_int,
                    point.get("tvlUsd"),
                    point.get("apyBase"),
                    point.get("apyReward"),
                    None,  # /chart doesn't include utilization
                ))
            if i % 25 == 0:
                log.info("backfilled %d/%d", i, len(pool_ids))

    await db.close()


if __name__ == "__main__":
    asyncio.run(main())
