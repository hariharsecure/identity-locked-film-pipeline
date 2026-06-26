#!/usr/bin/env python3
"""
Tool registry loader + auto-discovery + validation.
====================================================
Loads tool_registry.yaml, auto-discovers each tool's entrypoint script(s) on
disk, and validates the registry against reality:
  - every declared entrypoint exists (the real generation script for that stage)
  - every governor_est_gb is a number (feeds a RAM governor's acquire_slot)
  - every director_skill file exists
  - every stage referenced by pipeline.yaml has a registered tool, and vice-versa

This is a clean re-implementation of the auto-discovering-tool-registry PATTERN
(declarative catalog of "what tool runs this stage, what does it cost, what's its
fallback, how do I drive it"). Here the registry is a declarative YAML and the
discovery asserts the entrypoints exist on disk.

CLI:
  tools.py list                      # one line per tool: stage / runtime / est_gb / entrypoint
  tools.py show <tool>               # full metadata for one tool
  tools.py validate                  # auto-discover + assert everything resolves (exit 1 on any miss)
  tools.py governor <tool>           # print the exact acquire_slot(...) call for that tool
"""
from __future__ import annotations

import sys
from pathlib import Path

import yaml

PIPE_DIR = Path(__file__).resolve().parent
PROJ_ROOT = PIPE_DIR.parent                                   # project root
REGISTRY = PIPE_DIR / "tool_registry.yaml"
MANIFEST = PIPE_DIR / "pipeline.yaml"


def load_registry() -> dict:
    return yaml.safe_load(REGISTRY.read_text())


def load_manifest() -> dict:
    return yaml.safe_load(MANIFEST.read_text())


def _entrypoints(tool: dict) -> list[str]:
    """All declared entrypoint scripts for a tool (relative to PROJ_ROOT)."""
    eps = tool.get("entrypoints", {})
    if isinstance(eps, dict):
        return list(eps.values())
    if isinstance(eps, list):
        return list(eps)
    return []


def discover(tool_name: str, tool: dict) -> dict:
    """Resolve a tool's entrypoints + director-skill against the filesystem."""
    found, missing = [], []
    for ep in _entrypoints(tool):
        p = (PROJ_ROOT / ep)
        (found if p.exists() else missing).append(ep)
    ds = tool.get("director_skill")
    ds_ok = bool(ds) and (PIPE_DIR / ds).exists()
    return {"tool": tool_name, "found": found, "missing": missing,
            "director_skill": ds, "director_skill_ok": ds_ok}


def validate() -> int:
    """Auto-discover + cross-check registry <-> manifest. Returns process exit code."""
    reg = load_registry()
    man = load_manifest()
    tools = reg.get("tools", {})
    errs: list[str] = []
    warns: list[str] = []

    # 1. every entrypoint + director-skill resolves
    for name, tool in tools.items():
        d = discover(name, tool)
        for m in d["missing"]:
            errs.append(f"[{name}] entrypoint not found on disk: {m}")
        if not d["found"] and _entrypoints(tool):
            errs.append(f"[{name}] NONE of its entrypoints exist")
        if tool.get("director_skill") and not d["director_skill_ok"]:
            warns.append(f"[{name}] director_skill missing: {tool['director_skill']}")
        if not isinstance(tool.get("governor_est_gb", None), (int, float)):
            errs.append(f"[{name}] governor_est_gb must be a number")

    # 2. manifest stages <-> registry tools are consistent
    stage_tools = {s["id"]: s.get("tool") for s in man.get("stages", [])}
    reg_stages = {t.get("stage") for t in tools.values()}
    for sid, tname in stage_tools.items():
        if tname and tname not in tools:
            errs.append(f"manifest stage '{sid}' references unknown tool '{tname}'")
    for tname, tool in tools.items():
        if tool.get("stage") not in stage_tools:
            warns.append(f"registry tool '{tname}' has stage '{tool.get('stage')}' not in manifest")

    # 3. governor present
    gov = Path(reg.get("governor", ""))
    if not gov.exists():
        warns.append(f"governor not found at {gov} (heavy stages need a RAM governor's acquire_slot)")

    print("=" * 64)
    print("TOOL REGISTRY VALIDATION")
    print("=" * 64)
    for name, tool in tools.items():
        d = discover(name, tool)
        mark = "OK " if not d["missing"] and (d["found"] or not _entrypoints(tool)) else "ERR"
        print(f"  [{mark}] {name:22s} stage={tool.get('stage'):11s} "
              f"runtime={tool.get('runtime'):10s} est_gb={tool.get('governor_est_gb')} "
              f"entrypoints={len(d['found'])}/{len(d['found'])+len(d['missing'])}")
    if warns:
        print("\nWARNINGS:")
        for w in warns:
            print(f"  ! {w}")
    if errs:
        print("\nERRORS:")
        for e in errs:
            print(f"  X {e}")
        print(f"\nVALIDATION FAILED ({len(errs)} error(s)).")
        return 1
    print(f"\nVALIDATION PASSED ({len(tools)} tools; {len(warns)} warning(s)).")
    return 0


def _cmd_list() -> int:
    reg = load_registry()
    for name, tool in reg.get("tools", {}).items():
        eps = _entrypoints(tool)
        ep0 = eps[0] if eps else "(none)"
        print(f"{name:22s} {tool.get('stage'):11s} {tool.get('runtime'):10s} "
              f"est_gb={tool.get('governor_est_gb'):<5} -> {ep0}")
    return 0


def _cmd_show(name: str) -> int:
    reg = load_registry()
    tool = reg.get("tools", {}).get(name)
    if not tool:
        print(f"no such tool: {name}", file=sys.stderr)
        return 1
    print(yaml.safe_dump({name: tool}, sort_keys=False))
    d = discover(name, tool)
    print(f"# discovery: found={d['found']} missing={d['missing']} "
          f"director_skill_ok={d['director_skill_ok']}")
    return 0


def _cmd_governor(name: str) -> int:
    reg = load_registry()
    tool = reg.get("tools", {}).get(name)
    if not tool:
        print(f"no such tool: {name}", file=sys.stderr)
        return 1
    gb = tool.get("governor_est_gb", 0.0)
    if gb and gb > 0:
        print(f"with acquire_slot('{tool.get('stage')}_<tag>', est_gb={gb}, timeout_s=7200):")
        print(f"    # run {name} ({tool.get('runtime')}) — one heavy job at a time")
    else:
        print(f"# {name} is {tool.get('runtime')} (est_gb={gb}) — NO governor slot needed")
    return 0


def main() -> int:
    if len(sys.argv) < 2:
        print(__doc__)
        return 0
    cmd = sys.argv[1]
    if cmd == "list":
        return _cmd_list()
    if cmd == "show" and len(sys.argv) > 2:
        return _cmd_show(sys.argv[2])
    if cmd == "validate":
        return validate()
    if cmd == "governor" and len(sys.argv) > 2:
        return _cmd_governor(sys.argv[2])
    print(__doc__)
    return 0


if __name__ == "__main__":
    sys.exit(main())
