"""Pure ranking math. NO I/O. NO state. Testable without network or DB.

Built around the spec's central design choice (Section 7): store raw rates,
compute effective on read. LAV reclassification recomputes everything for free.

Effective formulas (spec 2b.A):
  effective_supply_apy = base + reward * (1 - LAV_discount)
  effective_borrow_apr = max(0, base - rebate * (1 - LAV_discount))

Leverage (spec 2b.H):
  per_iter_ltv  = platform_ltv - 5% buffer (clamped >= 0)
  leverage      = sum(per_iter_ltv^i for i in 0..n_iter-1)
  In a same-chain loop, the binding LTV is the lower of the two legs.
"""
from functools import lru_cache

from config.config import load_projects
from services.rewards.lav import discount_for_token


BUFFER_PCT = 0.05
N_ITER_DEFAULT = 10


@lru_cache(maxsize=1)
def _projects_index() -> dict:
    return load_projects()


def _primary_reward_token(project: str | None) -> str | None:
    if not project:
        return None
    proj = _projects_index().get(project)
    return proj.get("primary_reward") if proj else None


def effective_supply_apy(pool: dict) -> float:
    """base + reward*(1 - LAV_discount). Reward token inferred from project."""
    base = float(pool.get("apyBase") or 0)
    reward = float(pool.get("apyReward") or 0)
    token = _primary_reward_token(pool.get("project"))
    disc = discount_for_token(token)
    return base + reward * (1 - disc)


def effective_borrow_apr(pool: dict) -> float:
    """max(0, base - rebate*(1 - LAV_discount)). Floored at 0."""
    base = float(pool.get("apyBaseBorrow") or 0)
    rebate = float(pool.get("apyRewardBorrow") or 0)
    token = _primary_reward_token(pool.get("project"))
    disc = discount_for_token(token)
    return max(0.0, base - rebate * (1 - disc))


def per_iter_ltv(platform_ltv: float | None) -> float:
    """Apply 5% safety buffer to the platform's LTV. Clamp at 0."""
    if platform_ltv is None:
        return 0.0
    return max(0.0, float(platform_ltv) - BUFFER_PCT)


def compute_leverage(per_iter_ltv_value: float, n_iter: int = N_ITER_DEFAULT) -> float:
    """Sum of geometric series: 1 + r + r^2 + ... + r^(n-1)."""
    r = per_iter_ltv_value
    if r <= 0:
        return 1.0
    total = 0.0
    p = 1.0
    for _ in range(n_iter):
        total += p
        p *= r
    return total


# --- Route value object + ranking functions --------------------------------
from dataclasses import dataclass
from collections import defaultdict
from itertools import combinations, permutations


@dataclass(frozen=True)
class Route:
    chain: str
    project: str
    symbol: str
    effective_apy: float            # for passive: just supply; for loops: gross APY of the loop
    spread: float = 0.0             # = avg_supply - avg_borrow (loop only); for passive == effective_apy
    leverage: float = 1.0           # 1.0 for passive
    # loop-only fields (None for passive)
    plat_a: str | None = None
    asset_x: str | None = None
    plat_b: str | None = None
    asset_y: str | None = None
    avg_supply: float = 0.0
    avg_borrow: float = 0.0
    min_tvl_usd: float = 0.0


def rank_passive_supply(pools: list[dict]) -> list[Route]:
    """Each in-scope pool as a passive deposit. Sorted by effective_apy desc."""
    routes: list[Route] = []
    for p in pools:
        eapy = effective_supply_apy(p)
        if eapy <= 0:
            continue
        routes.append(Route(
            chain=p["chain"], project=p["project"], symbol=p["symbol"],
            effective_apy=eapy, spread=eapy, leverage=1.0,
            min_tvl_usd=float(p.get("tvlUsd") or 0),
        ))
    routes.sort(key=lambda r: r.effective_apy, reverse=True)
    return routes


def enumerate_same_chain_loops(pools: list[dict], n_iter: int = N_ITER_DEFAULT) -> list[Route]:
    """Find all (plat_A, plat_B, asset_X, asset_Y) ping-pong loops on the same chain.

    Each route's leverage uses the LOWER of the two platforms' per-iter LTVs
    (the binding constraint — spec 2b.H).
    """
    by_chain: dict[str, dict[tuple[str, str], dict]] = defaultdict(dict)
    for p in pools:
        if p.get("apyBaseBorrow") is None:
            continue
        by_chain[p["chain"]][(p["project"], p["symbol"].upper())] = p

    out: list[Route] = []
    for chain, mp in by_chain.items():
        platforms = sorted({k[0] for k in mp})
        assets = sorted({k[1] for k in mp})
        if len(platforms) < 2 or len(assets) < 2:
            continue
        for pa, pb in combinations(platforms, 2):
            for ax, ay in permutations(assets, 2):
                sX_A = mp.get((pa, ax)); bY_A = mp.get((pa, ay))
                sY_B = mp.get((pb, ay)); bX_B = mp.get((pb, ax))
                if not all([sX_A, bY_A, sY_B, bX_B]):
                    continue
                sup = (effective_supply_apy(sX_A) + effective_supply_apy(sY_B)) / 2
                bor = (effective_borrow_apr(bY_A) + effective_borrow_apr(bX_B)) / 2
                bind_iter_ltv = min(per_iter_ltv(sX_A.get("ltv")), per_iter_ltv(sY_B.get("ltv")))
                lev = compute_leverage(bind_iter_ltv, n_iter)
                gross = lev * sup - (lev - 1) * bor
                min_tvl = min(float(x.get("tvlUsd") or 0) for x in (sX_A, bY_A, sY_B, bX_B))
                out.append(Route(
                    chain=chain, project=f"{pa}+{pb}", symbol=f"{ax}/{ay}",
                    effective_apy=gross, spread=sup - bor, leverage=lev,
                    plat_a=pa, asset_x=ax, plat_b=pb, asset_y=ay,
                    avg_supply=sup, avg_borrow=bor, min_tvl_usd=min_tvl,
                ))
    out.sort(key=lambda r: r.spread, reverse=True)
    return out


# --- Cross-chain carry radar (spec 2b.E) -----------------------------------
@dataclass(frozen=True)
class CrossChainCarry:
    symbol: str
    supply_chain: str
    supply_project: str
    supply_apy: float
    borrow_chain: str
    borrow_project: str
    borrow_apr: float
    spread: float
    pre_bridge_ceiling: bool = True   # always True in Phase 1a — no bridge cost applied
    available_liquidity_usd: float | None = None


def cross_chain_carry(pools: list[dict]) -> list[CrossChainCarry]:
    """Per-stable-asset: best supply on any chain vs cheapest net-borrow on any
    OTHER chain. With Merkl rebates already applied via overlay_rebates() upstream.

    Pre-bridge-cost ceiling — the executable filter (bridge <= $1) is Phase 2.
    """
    # tuples: (apy, chain, project, tvlUsd)
    sup_by_asset: dict[str, list[tuple[float, str, str, float | None]]] = defaultdict(list)
    bor_by_asset: dict[str, list[tuple[float, str, str, float | None]]] = defaultdict(list)
    for p in pools:
        sym = (p.get("symbol") or "").upper()
        chain = p.get("chain") or ""
        proj = p.get("project") or ""
        tvl = float(p["tvlUsd"]) if p.get("tvlUsd") is not None else None
        sup_by_asset[sym].append((effective_supply_apy(p), chain, proj, tvl))
        if p.get("apyBaseBorrow") is not None:
            bor_by_asset[sym].append((effective_borrow_apr(p), chain, proj, tvl))

    out: list[CrossChainCarry] = []
    for sym, sup_list in sup_by_asset.items():
        bor_list = bor_by_asset.get(sym, [])
        if not bor_list:
            continue
        best_sup = max(sup_list, key=lambda t: t[0])
        cheap_bor = min(bor_list, key=lambda t: t[0])
        if best_sup[1] == cheap_bor[1]:
            # same chain — skip (covered by same-chain loop ranking)
            continue
        avail = min((t for t in (best_sup[3], cheap_bor[3]) if t is not None), default=None)
        out.append(CrossChainCarry(
            symbol=sym,
            supply_chain=best_sup[1], supply_project=best_sup[2], supply_apy=best_sup[0],
            borrow_chain=cheap_bor[1], borrow_project=cheap_bor[2], borrow_apr=cheap_bor[0],
            spread=best_sup[0] - cheap_bor[0],
            available_liquidity_usd=avail,
        ))
    out.sort(key=lambda r: r.spread, reverse=True)
    return out
