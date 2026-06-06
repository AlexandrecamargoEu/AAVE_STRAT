"""Ingestor: orchestrates the 60-min pipeline (spec Section 6).

  fetch DefiLlama supply+borrow (parallel)  -->  JOIN by UUID
  fetch Merkl BORROW opps (parallel)        -->  overlay rebates
  filter (TVL, stables, chain blacklist)
  validate (quality_flag)
  apply_snapshot -> aggregator
"""
import asyncio
import json
import logging
import time
from pathlib import Path

from config.config import settings, load_chains, load_stable_symbols, load_projects, normalize_symbol, asset_class, load_binance_networks, load_asset_classes, load_aci_chains
from db.sqlite_client import SqliteClient
from sources.defillama.client import DefiLlamaClient, join_supply_borrow
from sources.merkl.client import MerklClient
from sources.aci.client import AciClient
from sources.aci.parse import parse_merit_aprs
from sources.binance.client import BinanceClient
from sources.binance.withdraw import build_withdrawable_chains, build_deposit_chains
from services.rewards.merkl_match import build_rebate_lookup, overlay_rebates
from services.rewards.supply_incentives import overlay_supply_incentives
from services.pools.validators import classify_pool
from services.rewards.lav import is_token_known
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

    def __init__(self, db: SqliteClient, defillama=None, merkl=None, binance=None, aci=None):
        self.db = db
        self._defillama = defillama  # if None, use DefiLlamaClient() in run_once
        self._merkl = merkl
        self._binance = binance
        self._aci = aci

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
            merkl_lend_task = asyncio.create_task(merkl.fetch_supply_opportunities())

            async def _cats_safe():
                try:
                    return await defillama.fetch_protocol_categories()
                except Exception:
                    log.exception("[Ingestor] protocol categories fetch failed (non-fatal)")
                    return {}
            cats_task = asyncio.create_task(_cats_safe())

            supply, borrow, merkl_opps, merkl_lend, categories = await asyncio.gather(
                supply_task, borrow_task, merkl_task, merkl_lend_task, cats_task)

        # ACI Merit (off-protocol Aave supply incentives) — guarded; failure is non-fatal.
        aci_map: dict = {}
        try:
            aci = self._aci or AciClient()
            async with aci:
                aci_payload = await aci.fetch_merit_aprs()
            aci_map = parse_merit_aprs(aci_payload, load_aci_chains())
        except Exception:
            log.exception("[Ingestor] ACI merit fetch failed (non-fatal)")

        joined = join_supply_borrow(supply, borrow)
        rebates = build_rebate_lookup(merkl_opps)
        overlaid = overlay_rebates(joined, rebates)
        lend_lookup = build_rebate_lookup(merkl_lend)
        overlaid = overlay_supply_incentives(overlaid, lend_lookup, aci_map)
        filtered = self._filter(overlaid)
        validated = self._validate(filtered)

        n = await apply_snapshot(self.db, validated, ts=ts)
        await compute_aggregates(self.db, now_ts=ts)

        try:
            binance = self._binance or BinanceClient()
            async with binance:
                coins = await binance.fetch_capital_config()
            classes = list(load_asset_classes().keys())
            networks = load_binance_networks()
            wmap = build_withdrawable_chains(coins, networks, classes)
            dmap = build_deposit_chains(coins, networks, classes)
            cache_path = Path(settings.BINANCE_WITHDRAW_CACHE)
            cache_path.parent.mkdir(parents=True, exist_ok=True)
            cache_path.write_text(json.dumps({
                "withdraw": {k: sorted(v) for k, v in wmap.items()},
                "deposit": {k: sorted(v) for k, v in dmap.items()},
            }))
        except Exception:
            log.exception("[Ingestor] binance withdraw-map fetch failed (non-fatal)")

        # Persist the ACI map as a JSON cache for read-time supply tagging (guarded).
        try:
            aci_cache = Path(settings.ACI_INCENTIVES_CACHE)
            aci_cache.parent.mkdir(parents=True, exist_ok=True)
            aci_cache.write_text(json.dumps({f"{c}|{s}": v for (c, s), v in aci_map.items()}))
        except Exception:
            log.exception("[Ingestor] ACI cache write failed (non-fatal)")

        # Persist protocol categories cache — ONLY when non-empty, so a failed/empty
        # fetch keeps the prior (stale) cache rather than clobbering it.
        if categories:
            try:
                cats_cache = Path(settings.PROTOCOL_CATEGORIES_CACHE)
                cats_cache.parent.mkdir(parents=True, exist_ok=True)
                cats_cache.write_text(json.dumps(categories))
            except Exception:
                log.exception("[Ingestor] categories cache write failed (non-fatal)")

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
            sym = normalize_symbol(p.get("symbol"))   # folds USD₮ -> USDT etc.
            if sym not in stables and asset_class(p.get("symbol")) is None:
                continue
            if (p.get("tvlUsd") or 0) < min_tvl:
                continue
            if p.get("chain") in excluded:
                continue
            out.append(p)
        return out

    def _validate(self, pools: list[dict]) -> list[dict]:
        projects = load_projects()
        out = []
        for p in pools:
            flag = classify_pool(p)
            p2 = dict(p)
            p2["quality_flag"] = flag.value
            # overlay_rebates sets reward_source_borrow; snapshot reads reward_source
            if "reward_source_borrow" in p2 and "reward_source" not in p2:
                p2["reward_source"] = p2["reward_source_borrow"]

            # Set lav_uncertain=1 if the pool's primary reward token isn't in our LAV config.
            # This happens for new/unclassified protocols — we still discount conservatively (bucket B default)
            # but the flag tells the dashboard to render "B?" instead of "B".
            proj = projects.get(p2.get("project") or "")
            reward_token = (proj or {}).get("primary_reward")
            p2["lav_uncertain"] = 0 if is_token_known(reward_token) else 1

            out.append(p2)
        return out
