"""Overlay supply-side incentives from the two aggregators onto pool dicts.

Sources:
  - Merkl LEND campaigns: lookup {(chain_lower, proto, SYM): apr} built with the
    SAME build_rebate_lookup used for borrow (reuse — the shape is identical).
  - ACI Merit map: {(defillama_chain, NORM_SYM): {'merit': apr, 'self': apr}} from
    parse_merit_aprs. merit+self are DISTINCT programs -> summed within ACI.

Cross-source rule: take the MAX of (merkl_lend, aci_total) — never sum across
sources (could be the same program surfaced twice). Never LOWER an existing
DefiLlama apyReward. Self present -> incentive_conditional=1 (zkPoH-gated,
$35k/user cap); the dict flag is read by the ingestor's ACI-cache writer and the
router's read-time tag (no DB column).
"""
from config.config import normalize_symbol
from services.rewards.merkl_match import _norm_chain, _norm_proto, _norm_sym


def overlay_supply_incentives(pools: list[dict],
                              merkl_lend: dict[tuple[str, str, str], float],
                              aci_map: dict[tuple[str, str], dict]) -> list[dict]:
    out: list[dict] = []
    for p in pools:
        merged = dict(p)
        chain_l = _norm_chain(p.get("chain"))
        sym_u = _norm_sym(p.get("symbol"))
        full_proto = _norm_proto(p.get("project"))
        proto_prefix = full_proto.split("-")[0] if "-" in full_proto else full_proto

        merkl_apr = 0.0
        for proto in (full_proto, proto_prefix):
            r = merkl_lend.get((chain_l, proto, sym_u))
            if r is not None:
                merkl_apr = r
                break

        aci = aci_map.get((p.get("chain"), normalize_symbol(p.get("symbol"))))
        aci_apr = (aci["merit"] + aci["self"]) if aci else 0.0

        incentive = max(merkl_apr, aci_apr)
        if incentive > 0:
            existing = merged.get("apyReward") or 0
            if incentive > existing:
                merged["apyReward"] = incentive
                merged["reward_source"] = "aci_merit" if aci_apr >= merkl_apr else "merkl_lend"
        if aci and aci.get("self"):
            merged["incentive_conditional"] = 1
        out.append(merged)
    return out
