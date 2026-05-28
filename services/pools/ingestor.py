"""Ingestor: orchestrates the 60-min pipeline (spec Section 6).

  fetch DefiLlama supply+borrow (parallel)  -->  JOIN by UUID
  fetch Merkl BORROW opps (parallel)        -->  overlay rebates
  filter (TVL, stables, chain blacklist)
  validate (quality_flag)
  apply_snapshot -> aggregator
"""
import asyncio
import logging
import time

from config.config import settings, load_chains, load_stable_symbols
from db.sqlite_client import SqliteClient
from sources.defillama.client import DefiLlamaClient, join_supply_borrow
from sources.merkl.client import MerklClient
from services.rewards.merkl_match import build_rebate_lookup, overlay_rebates
from services.pools.validators import classify_pool
from services.pools.snapshot import apply_snapshot
from services.pools.aggregator import compute_aggregates


log = logging.getLogger("codee.ingestor")


class PoolsIngestor:
    """Orchestrates one ingestion tick or a long-running loop.

    apply_snapshot is called with the FULL filtered batch — partial batches
    would mark omitted pools as inactive (spec 2b error handling). The tick
    is fail-open: any exception in run_once is logged and the next tick still
    runs; the last good snapshot remains servable.
    """

    def __init__(self, db: SqliteClient, defillama=None, merkl=None):
        self.db = db
        self._defillama = defillama  # if None, use DefiLlamaClient() in run_once
        self._merkl = merkl

    async def run(self) -> None:
        """Long-running loop. Sleeps SNAPSHOT_INTERVAL_MIN between ticks."""
        interval_s = settings.SNAPSHOT_INTERVAL_MIN * 60
        while True:
            try:
                await self.run_once(ts=int(time.time()))
            except Exception:
                log.exception("[Ingestor] tick failed — keeping last good snapshot")
            await asyncio.sleep(interval_s)

    async def run_once(self, ts: int) -> int:
        """Single ingestion tick. Returns count of pools persisted."""
        defillama = self._defillama or DefiLlamaClient()
        merkl = self._merkl or MerklClient()

        async with defillama, merkl:
            supply_task = asyncio.create_task(defillama.fetch_pools_supply())
            borrow_task = asyncio.create_task(defillama.fetch_pools_borrow())
            merkl_task = asyncio.create_task(merkl.fetch_borrow_opportunities())
            supply, borrow, merkl_opps = await asyncio.gather(supply_task, borrow_task, merkl_task)

        joined = join_supply_borrow(supply, borrow)
        rebates = build_rebate_lookup(merkl_opps)
        overlaid = overlay_rebates(joined, rebates)
        filtered = self._filter(overlaid)
        validated = self._validate(filtered)

        n = await apply_snapshot(self.db, validated, ts=ts)
        await compute_aggregates(self.db, now_ts=ts)

        log.info("[Ingestor] ingested %d in-scope pools (of %d joined, %d merkl rebates)",
                 n, len(joined), len(rebates))
        return n

    def _filter(self, pools: list[dict]) -> list[dict]:
        """Apply scope filters: TVL, stable symbol, chain not blacklisted (default: nothing blacklisted)."""
        stables = load_stable_symbols()
        chains_cfg = load_chains()["chains"]
        excluded = {c for c, payload in chains_cfg.items() if payload.get("excluded")}
        min_tvl = settings.MIN_TVL_USD
        out = []
        for p in pools:
            sym = (p.get("symbol") or "").upper()
            if sym not in stables:
                continue
            if (p.get("tvlUsd") or 0) < min_tvl:
                continue
            if p.get("chain") in excluded:
                continue
            out.append(p)
        return out

    def _validate(self, pools: list[dict]) -> list[dict]:
        out = []
        for p in pools:
            flag = classify_pool(p)
            p2 = dict(p)
            p2["quality_flag"] = flag.value
            # overlay_rebates sets reward_source_borrow; snapshot reads reward_source
            if "reward_source_borrow" in p2 and "reward_source" not in p2:
                p2["reward_source"] = p2["reward_source_borrow"]
            out.append(p2)
        return out
