"""Pure parsing of the ACI Merit payload. Keys look like:
  '<chain>-supply-<asset>'        -> Merit APR for supplying <asset> on <chain>
  'self-<chain>-supply-<asset>'   -> Self (zkPoH-gated) APR for the same pool
Anything else (sgho keys, borrow combos, null values, unknown chains) is ignored."""
from config.config import normalize_symbol


def parse_merit_aprs(payload: dict, chain_map: dict) -> dict[tuple[str, str], dict]:
    """-> {(defillama_chain, NORMALIZED_ASSET): {'merit': apr, 'self': apr}}"""
    actions = ((payload.get("currentAPR") or {}).get("actionsAPR")) or {}
    out: dict[tuple[str, str], dict] = {}
    for key, apr in actions.items():
        if apr is None:
            continue
        is_self = key.startswith("self-")
        k = key[5:] if is_self else key
        parts = k.split("-supply-")
        if len(parts) != 2 or "-" in parts[1]:      # not a plain supply key (e.g. borrow combos)
            continue
        chain = chain_map.get(parts[0])
        if not chain:
            continue
        sym = normalize_symbol(parts[1])
        entry = out.setdefault((chain, sym), {"merit": 0.0, "self": 0.0})
        entry["self" if is_self else "merit"] = float(apr)
    return out
