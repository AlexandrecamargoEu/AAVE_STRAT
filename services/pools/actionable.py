"""T2 actionable-protocol classification (pure — no I/O).

Rule: a protocol is 'actionable' (a plain lending platform whose quoted rates an
executor can actually capture by depositing/borrowing) iff its DefiLlama category
is 'Lending', with a small manual override list on top (exclude beats category,
include beats category; keep the two lists disjoint).

FAIL-OPEN: an empty category map (fetch failed, cache missing) or an unknown
project classifies as actionable — a DefiLlama hiccup must never blank the radar.
"""


def is_actionable(project: str, categories: dict[str, str], overrides: dict) -> bool:
    if project in (overrides.get("exclude") or []):
        return False
    if project in (overrides.get("include") or []):
        return True
    if not categories:
        return True                       # fail-open: no data, no filtering
    cat = categories.get(project)
    if cat is None:
        return True                       # fail-open: unknown project
    return cat == "Lending"
