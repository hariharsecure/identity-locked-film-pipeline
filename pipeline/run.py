#!/usr/bin/env python3
"""
Pipeline planner + review-gate driver (the orchestration view).
===============================================================
Reads pipeline.yaml + tool_registry.yaml + the checkpoint store and answers:
  - what is the build order (topological, from each stage's `deps`)?
  - what is each stage's status + gate verdict (from the checkpoints)?
  - what is RUNNABLE now (deps' gates cleared) vs BLOCKED on a gate?
  - HOW do I run the next stage (the exact registry invocation + governor call)?

It is a PLANNER, not an executor. It deliberately does NOT run heavy generation —
it prints the command (the real generation-script invocation, with the RAM-governor
acquire_slot wrapper) for a human/agent to run. This keeps the review-gate
discipline (a human approves between stages) and the "one heavy job at a time,
governor-gated" rule intact: the planner marks a stage BLOCKED until its upstream
gate is stamped PASS in the checkpoint store.

This re-implements the "agent IS the control plane + human approval gate" PATTERN:
the agent reads this plan, runs the printed command, records the checkpoint, and
stamps the gate.

CLI:
  run.py plan          # the full board: order, status, gates, what's runnable/blocked
  run.py next          # the next runnable stage + its exact command + governor call
  run.py order         # just the topological build order
  run.py gates         # the gate map (which gate guards which stage advance)
"""
from __future__ import annotations

import sys
from pathlib import Path

import yaml

PIPE_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(PIPE_DIR))
import checkpoint as ckpt_store          # noqa: E402  (sibling module)
import tools as registry                 # noqa: E402

MANIFEST = PIPE_DIR / "pipeline.yaml"


def _topo(stages: list[dict]) -> list[str]:
    """Kahn topological sort over stage deps. QC (deps=[]) sorts early but is cross-cutting."""
    ids = [s["id"] for s in stages]
    deps = {s["id"]: list(s.get("deps", [])) for s in stages}
    order, ready = [], [i for i in ids if not deps[i]]
    deps = {k: set(v) for k, v in deps.items()}
    while ready:
        n = ready.pop(0)
        order.append(n)
        for m in ids:
            if n in deps[m]:
                deps[m].discard(n)
                if not deps[m] and m not in order and m not in ready:
                    ready.append(m)
    # any remainder (cycle / unreachable) appended for visibility
    for i in ids:
        if i not in order:
            order.append(i)
    return order


def _load():
    man = yaml.safe_load(MANIFEST.read_text())
    reg = registry.load_registry()
    return man, reg


def _stage_runnable(stage: dict) -> tuple[bool, str]:
    """A stage is runnable iff every dep's review-gate is PASS (or the dep has no gate)."""
    man, _ = _load()
    gate_of = {s["id"]: s.get("review_gate") for s in man["stages"]}
    blockers = []
    for d in stage.get("deps", []):
        # a dep blocks only if it HAS a gate and that gate isn't cleared
        if gate_of.get(d) and not ckpt_store.is_gate_clear(d):
            c = ckpt_store.load(d)
            blockers.append(f"{d}(gate={c.get('gate', {}) and (c['gate'] or {}).get('verdict', 'unstamped')})")
    if blockers:
        return False, "blocked on: " + ", ".join(blockers)
    return True, "deps cleared"


def cmd_order() -> int:
    man, _ = _load()
    order = _topo(man["stages"])
    print("BUILD ORDER (topological, from deps):")
    for i, sid in enumerate(order, 1):
        st = next(s for s in man["stages"] if s["id"] == sid)
        deps = ", ".join(st.get("deps", [])) or "-"
        print(f"  {i}. {sid:14s} (deps: {deps})")
    return 0


def cmd_gates() -> int:
    man, _ = _load()
    print("GATE MAP (the approval point that guards each stage's advance):")
    for g, spec in man.get("gates", {}).items():
        print(f"  {g:14s} [{spec.get('policy')}]  {spec.get('name')}")
        print(f"      when: {spec.get('when')}")
        print(f"      fail: {spec.get('fail_action')}")
    return 0


def cmd_plan() -> int:
    man, reg = _load()
    order = _topo(man["stages"])
    tools = reg.get("tools", {})
    print("=" * 76)
    print("PIPELINE — PLAN")
    print("=" * 76)
    print(f"{'#':>2} {'STAGE':14s} {'STATUS':9s} {'GATE':18s} {'RAM':6s} RUNNABLE")
    print("-" * 76)
    for i, sid in enumerate(order, 1):
        st = next(s for s in man["stages"] if s["id"] == sid)
        c = ckpt_store.load(sid)
        gate = c.get("gate")
        gtxt = f"{gate['verdict']}" if gate else "-"
        ram = st.get("ram_class", "?")
        if st.get("review_gate") is None:
            # cross-cutting discipline (QC) — not a linear runnable stage
            print(f"{i:>2} {sid:14s} {c['status']:9s} {gtxt:18s} {ram:6s} x-cut")
            continue
        runnable, why = _stage_runnable(st)
        rtxt = "yes" if runnable else "NO"
        print(f"{i:>2} {sid:14s} {c['status']:9s} {gtxt:18s} {ram:6s} {rtxt}")
        if not runnable:
            print(f"     -> {why}")
    print("\nLegend: a stage runs only when its deps' review-gates are PASS.")
    print("Heavy stages acquire a RAM-governor slot — one at a time.")
    print("Run `run.py next` for the exact command to run the next runnable stage.")
    return 0


def cmd_next() -> int:
    man, reg = _load()
    order = _topo(man["stages"])
    tools = reg.get("tools", {})
    for sid in order:
        st = next(s for s in man["stages"] if s["id"] == sid)
        if st.get("review_gate") is None:
            continue                                   # QC / cross-cutting discipline — never a "next" stage
        c = ckpt_store.load(sid)
        if c["status"] == "gated":
            continue                                   # gate cleared (PASS) -> done for planning
        # NOTE: a `verified` stage is NOT skipped — it still needs its gate stamped
        # before downstream unblocks, so it must remain visible in `next`.
        runnable, why = _stage_runnable(st)
        if not runnable:
            continue
        tool = tools.get(st.get("tool"), {})
        print(f"NEXT RUNNABLE STAGE: {sid}  ({st.get('name')})")
        print(f"  status      : {c['status']}")
        print(f"  tool        : {st.get('tool')}  (runtime {tool.get('runtime')})")
        print(f"  director     : {st.get('director_skill')}")
        gb = tool.get("governor_est_gb", 0.0)
        if gb and gb > 0:
            print(f"  governor    : acquire_slot('{sid}_<tag>', est_gb={gb}, timeout_s=7200)  # one heavy job at a time")
        else:
            print(f"  governor    : none needed ({tool.get('runtime')}, est_gb={gb})")
        inv = tool.get("invocation", {})
        if inv:
            print("  invocation  :")
            for k, v in inv.items():
                print(f"      ({k}) {v}")
        print(f"  gate        : {st.get('review_gate')} — stamp it after the gate QC passes:")
        print(f"      python3 checkpoint.py record {sid} --produced '<glob>'")
        print(f"      python3 checkpoint.py gate   {sid} --verdict PASS --by <you>")
        return 0
    print("No runnable stage — all stages are either done or blocked on an unstamped gate.")
    print("Run `run.py plan` to see what's blocking.")
    return 0


def main() -> int:
    cmd = sys.argv[1] if len(sys.argv) > 1 else "plan"
    return {"plan": cmd_plan, "next": cmd_next, "order": cmd_order, "gates": cmd_gates}.get(cmd, cmd_plan)()


if __name__ == "__main__":
    sys.exit(main())
