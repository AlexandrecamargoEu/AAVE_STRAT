# Codee Multi-Hop v1.2 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Two improvements revealed by reading live routes: (1) same-chain platform-to-platform edges (borrow on A, deposit directly on B on the SAME chain — a plain on-chain transfer: no Binance, no bridge cost; kills the redundant "out-and-back-via-Base" detour), and (2) show the protocol name on every route leg (two "USDC·Ethereum" legs were different protocols — Morpho 8.13% vs Silo 55.91% — and the UI hid that).

**Architecture:** Analyzer-only for (1): in `enumerate_multihop_paths`' expansion, allow `c2 == chain` when the platform differs (`p2 != proj`), skipping the Binance deposit/withdraw gates and adding zero bridge cost for those edges; the deposit gate moves from the borrow level into the destination loop (it only applies to cross-chain destinations). Frontend-only for (2): the Route cell renders `SYM·Chain·project apy`. API unchanged (`path[].project` already exists).

**Where:** Branch `codee-multihop-v12` in both repos (VT from `main`, AAVE_STRAT from `master`). Test cmd (Bash, from VT): `PYTHONIOENCODING=utf-8 .venv/Scripts/pytest codee/tests/ -q`.

---

### Task 1: Analyzer — same-chain edges

**Files (ONLY 2):**
- Modify: `codee/services/routes/analyzer.py` (the expansion loop in `enumerate_multihop_paths`)
- Modify: `codee/tests/test_analyzer_multihop.py`

- [ ] **Step 1: Update the obsolete test + add the failing tests**

The existing `test_max_hops_respected_and_same_chain_dest_excluded` encodes the OLD rule (consecutive chains must differ). Replace its second half:
```python
def test_max_hops_respected_and_same_platform_dest_excluded():
    paths = enumerate_multihop_paths(POOLS, WMAP, DMAP, COSTS, capital_class="USDC", max_hops=1)
    assert all(p.hops == 1 for p in paths)
    # supplying the borrowed asset back into the SAME (chain, project) is never a hop
    full = enumerate_multihop_paths(POOLS, WMAP, DMAP, COSTS, capital_class="USDC")
    for p in full:
        pairs = [(n[0], n[1]) for n in p.nodes]
        assert all(pairs[i] != pairs[i + 1] for i in range(len(pairs) - 1))
```
(delete the old test function; this replaces it.)

Append the new tests:
```python
def test_same_chain_cross_platform_hop_no_bridge_no_binance_gate():
    # second platform on ChainA: borrow WETH on aave (2%), walk it across the street
    # to morpho-blue on the SAME chain (6%). No Binance maps needed for that hop,
    # no bridge cost. net = 10 + 0.75*(6-2) = 13.0
    pools = POOLS + [_p("ChainA", "morpho-blue", "WETH", base=6.0, borrow_base=5.0)]
    wmap = {"USDC": {"ChainA"}, "ETH": set(), "USDT": set(), "BTC": set()}   # Binance can't move ETH AT ALL
    dmap = {"USDC": set(), "ETH": set(), "USDT": set(), "BTC": set()}
    paths = enumerate_multihop_paths(pools, wmap, dmap, COSTS, capital_class="USDC")
    two = [p for p in paths if p.hops == 2]
    assert two, "same-chain hop must exist without any Binance route for the asset"
    best = two[0]
    assert best.nodes == (("ChainA", "aave-v3", "USDC"), ("ChainA", "morpho-blue", "WETH"))
    assert best.net_apy == pytest.approx(13.0)
    assert best.bridge_cost_usd == pytest.approx(0.0)      # on-chain transfer, not a bridge


def test_cross_chain_hop_still_requires_binance_gates():
    # same fixture WITHOUT the same-chain platform: the only dest is ChainB and
    # Binance can't move ETH -> no 2-hop (the gates still bind cross-chain edges)
    wmap = {"USDC": {"ChainA"}, "ETH": set(), "USDT": set(), "BTC": set()}
    dmap = {"USDC": set(), "ETH": set(), "USDT": set(), "BTC": set()}
    paths = enumerate_multihop_paths(POOLS, wmap, dmap, COSTS, capital_class="USDC")
    assert all(p.hops == 1 for p in paths)


def test_same_chain_hop_beats_bridge_detour():
    # both a same-chain dest (6%) and a cross-chain dest (5%, costs bridge $) exist;
    # the same-chain route must rank first (higher net) and carry less bridge cost
    pools = POOLS + [_p("ChainA", "morpho-blue", "WETH", base=6.0, borrow_base=5.0)]
    paths = enumerate_multihop_paths(pools, WMAP, DMAP, COSTS, capital_class="USDC")
    two = [p for p in paths if p.hops == 2]
    assert two[0].nodes[-1] == ("ChainA", "morpho-blue", "WETH")
    assert two[0].bridge_cost_usd == pytest.approx(0.0)
    assert any(p.nodes[-1] == ("ChainB", "aave-v3", "WETH") for p in two)  # bridge route still emitted
```

- [ ] **Step 2: Run — expect FAIL** (same-chain hops don't exist yet):
`PYTHONIOENCODING=utf-8 .venv/Scripts/pytest codee/tests/test_analyzer_multihop.py -v`

- [ ] **Step 3: Implement** — in the expansion loop of `enumerate_multihop_paths`:
- REMOVE the borrow-level deposit gate (`if bcls is None or chain not in deposit_map.get(bcls, set()): continue` → keep only the `bcls is None` part); the deposit gate moves into the dest loop, where it only applies cross-chain.
- Replace the dest-loop gating:
```python
                for (c2, p2, spool) in supply_nodes.get(bcls, []):
                    same_chain = (c2 == chain)
                    if same_chain and p2 == proj:
                        continue              # back into the same platform = a loop, not a hop
                    if not same_chain:
                        # Binance bridge gates apply only when actually moving chains
                        if chain not in deposit_map.get(bcls, set()):
                            continue
                        if c2 not in withdraw_map.get(bcls, set()):
                            continue
                    ...
                    nxt.append((..., bridge + (0.0 if same_chain else float(bridge_costs.get(c2, 1.0))), ...))
```
- Update the docstring: "the dest is either a DIFFERENT platform on the same chain (plain on-chain transfer — no Binance, no bridge cost) or any chain reachable via Binance (deposit on source AND withdraw on dest, by the borrowed asset's class)".

- [ ] **Step 4: Run — full multihop file + golden + full suite** — ALL PASS. Existing tests to sanity-check (fixture has ONE platform per chain, so same-chain edges don't change their results): `test_two_hop_path_found...` (12.25 unchanged), `test_blocked_bridge_kills_the_hop` (no second ChainA platform → still all 1-hop), diversity/cap tests.

- [ ] **Step 5: Commit**
```bash
git add codee/services/routes/analyzer.py codee/tests/test_analyzer_multihop.py
git commit -m "T4v1.2-1: same-chain cross-platform edges (no Binance gate, zero bridge cost)"
```

---

### Task 2: Frontend — protocol name on every leg

**Files (ONLY):** `Volume_tracker/web/index.html` (`VIEWS.multihop.row` only)

- [ ] **Step 1:** In the Route renderer, change the segment template from `${n.symbol}·${n.chain} ${codeeFmtApy(n.supply_apy)}` to:
```javascript
`${n.symbol}·${n.chain}·${n.project} ${codeeFmtApy(n.supply_apy)}`
```
- [ ] **Step 2:** Static check (`grep -n "n.project" web/index.html` → 1 hit in multihop row) + node sanity render + harness smoke (`/` serves; multihop endpoint 200). Kill harness.
- [ ] **Step 3:** Commit:
```bash
git add web/index.html
git commit -m "T4v1.2-2: Multi-Hop route legs show the protocol name"
```

---

### Task 3: Mirror backend to AAVE_STRAT
Branch `codee-multihop-v12`. Task 1 only (analyzer + tests; bare imports; same escalation rule). Full suite green (expect ~133 passed, 1 skipped; report exact). Commit: `T4 v1.2 (mirror): same-chain cross-platform edges`.

### Task 4: Deploy (gated on explicit user approval)
Backend changed → restart. Verify after: `/routes/multihop` routes exist with consecutive same-chain nodes (different projects) and correspondingly lower `bridge_cost_usd`; the redundant out-and-back-via-Base detours are outranked; dashboard legs show `SYM·Chain·project`.

---

## Self-review notes
- The deposit-gate move is the subtle bit: it was an optimization at borrow level (valid when ALL dests bridge); now it must bind per-dest. Covered by `test_cross_chain_hop_still_requires_binance_gates`.
- Same-platform re-supply excluded (`p2 == proj` on same chain) — that's the loop strategy's territory, not multihop.
- `visited` already prevents node reuse; same-chain edges introduce no new cycle risk.
- Bridge $ column: sums only true bridges now — consistent with what the user pays.
- Old `chains[i] != chains[i+1]` test replaced by platform-pair rule — intentional spec change, not a regression.
