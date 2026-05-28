"""Match Merkl BORROW opportunities to DefiLlama pools (spec 2b.A, Q6).

Match key: (chain name lowercased, protocol id lowercased, asset symbol uppercased).

Protocol id matching: Merkl uses 'aave', DefiLlama uses 'aave-v3' — we try the
full project string first, then the prefix before '-' (handles aave-v3/-v2,
compound-v3, morpho-blue, etc.).
"""
from collections import defaultdict


def _norm_chain(s: str | None) -> str:
    return (s or "").lower().strip()


def _norm_proto(s: str | None) -> str:
    return (s or "").lower().strip()


def _norm_sym(s: str | None) -> str:
    return (s or "").upper().strip()


def build_rebate_lookup(opps: list[dict]) -> dict[tuple[str, str, str], float]:
    """Returns {(chain, protocol, symbol): max_apr}. Picks max if multiple opps match."""
    out: dict[tuple[str, str, str], float] = defaultdict(float)
    for o in opps:
        chain = _norm_chain((o.get("chain") or {}).get("name"))
        proto = _norm_proto((o.get("protocol") or {}).get("id"))
        apr = float(o.get("apr") or 0)
        for t in o.get("tokens") or []:
            sym = _norm_sym(t.get("symbol"))
            if not (chain and proto and sym):
                continue
            key = (chain, proto, sym)
            if apr > out[key]:
                out[key] = apr
    return dict(out)


def overlay_rebates(pools: list[dict], rebates: dict[tuple[str, str, str], float]) -> list[dict]:
    """For each pool, look up the Merkl rebate by (chain, protocol_prefix, symbol).

    Sets `apyRewardBorrow = max(existing, merkl_apr)` and marks
    `reward_source_borrow = 'merkl'` when Merkl supplied the value.
    """
    out: list[dict] = []
    for p in pools:
        merged = dict(p)
        chain = _norm_chain(p.get("chain"))
        sym = _norm_sym(p.get("symbol"))
        full_proto = _norm_proto(p.get("project"))
        proto_prefix = full_proto.split("-")[0] if "-" in full_proto else full_proto

        merkl_apr = None
        for proto in (full_proto, proto_prefix):
            r = rebates.get((chain, proto, sym))
            if r is not None:
                merkl_apr = r
                break

        if merkl_apr is not None:
            existing = p.get("apyRewardBorrow")
            if existing is None or merkl_apr > existing:
                merged["apyRewardBorrow"] = merkl_apr
                merged["reward_source_borrow"] = "merkl"
            else:
                merged.setdefault("reward_source_borrow", "defillama")
        else:
            merged.setdefault("reward_source_borrow", "defillama" if p.get("apyRewardBorrow") else "none")

        out.append(merged)
    return out
