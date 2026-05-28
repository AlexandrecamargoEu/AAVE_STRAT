"""One-off setup: create SQLite schema, then trigger a single ingestion tick so
the dashboard has data to render. Idempotent — safe to re-run.
"""
import asyncio
import logging
import time

from db.sqlite_client import SqliteClient
from services.pools.ingestor import PoolsIngestor


async def main():
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s | %(message)s")
    db = SqliteClient()
    await db.connect()
    await db.apply_migrations()
    print("[bootstrap] schema applied")

    ing = PoolsIngestor(db)
    n = await ing.run_once(ts=int(time.time()))
    print(f"[bootstrap] first ingestion complete: {n} in-scope pools")

    await db.close()


if __name__ == "__main__":
    asyncio.run(main())
