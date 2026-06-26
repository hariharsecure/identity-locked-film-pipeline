#!/usr/bin/env python3
"""
Pipeline checkpoint store.
==========================
JSON checkpoints, one per stage, that make a multi-stage pipeline RESUMABLE and
AUDITABLE. A checkpoint records, per stage:
  - status            : pending | running | produced | verified | gated | failed | held
  - produced_artifacts: the files the stage wrote (path + size + mtime — proof of existence)
  - verified_artifacts: the subset that passed the stage's gate (the review-gate stamps these)
  - gate              : the review-gate record (name / policy / verdict / who / when / notes)
  - settings          : the key gen settings used (seed/steps/etc.) for reproducibility
  - log               : a free-form append-only event list

It is intentionally tiny and dependency-free (stdlib only) so it runs under any
Python env. It does NOT run any stage. It records what a stage (a real generation
script, run separately) produced, and lets a human/agent stamp a gate verdict.
The runner (run.py) reads these to decide what to skip and what is blocked on a gate.

CLI:
  checkpoint.py status                      # board: every stage's status + gate verdict
  checkpoint.py show <stage>                # full JSON for one stage
  checkpoint.py record <stage> --produced <glob> [--settings k=v ...]
  checkpoint.py verify <stage> <artifact> [<artifact> ...]   # move produced -> verified
  checkpoint.py gate <stage> --verdict PASS|REWORK|HOLD --by <who> [--notes ...]
  checkpoint.py reset <stage>               # back to pending (re-do the stage)
"""
from __future__ import annotations

import argparse
import glob as _glob
import json
import os
import sys
import time
from pathlib import Path

PIPE_DIR = Path(__file__).resolve().parent
PROJ_ROOT = PIPE_DIR.parent                    # project root — globs resolve against this
CKPT_DIR = PIPE_DIR / "checkpoints"
CKPT_DIR.mkdir(parents=True, exist_ok=True)

STATUSES = ("pending", "running", "produced", "verified", "gated", "failed", "held")


def _ckpt_path(stage: str) -> Path:
    return CKPT_DIR / f"{stage}.json"


def _now() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%S%z")


def load(stage: str) -> dict:
    p = _ckpt_path(stage)
    if p.exists():
        return json.loads(p.read_text())
    return {
        "stage": stage,
        "status": "pending",
        "produced_artifacts": [],
        "verified_artifacts": [],
        "gate": None,
        "settings": {},
        "log": [],
        "created": _now(),
        "updated": _now(),
    }


def save(ckpt: dict) -> Path:
    ckpt["updated"] = _now()
    p = _ckpt_path(ckpt["stage"])
    p.write_text(json.dumps(ckpt, indent=2))
    return p


def _rel_to_root(path: str) -> str:
    """Store a project-relative path when the artifact is under PROJ_ROOT.

    This keeps committed checkpoints free of absolute machine paths (a leak vector
    if a checkpoint JSON is ever committed despite the .gitignore). Out-of-tree
    paths are stored as-is.
    """
    fp = Path(path)
    try:
        return str(fp.resolve().relative_to(PROJ_ROOT.resolve()))
    except Exception:
        return str(fp)


def _artifact_record(path: str) -> dict:
    fp = Path(path)
    rec = {"path": _rel_to_root(path), "exists": fp.exists()}
    if fp.exists():
        st = fp.stat()
        rec["size_bytes"] = st.st_size
        rec["mtime"] = time.strftime("%Y-%m-%dT%H:%M:%S", time.localtime(st.st_mtime))
    return rec


def record_produced(stage: str, globs: list[str], settings: dict | None = None) -> dict:
    """Mark a stage as having PRODUCED artifacts (resolved from globs).

    Globs are resolved relative to the PROJECT ROOT, not the cwd, so a glob like
    `frames_scene6/*.png` works regardless of where you invoke this (a bare
    relative glob from the pipeline/ dir would otherwise miss the root). Refuses
    to advance status to `produced` if ZERO artifacts matched (a glob that matched
    nothing is almost always a typo, not a finished stage).
    """
    ckpt = load(stage)
    paths: list[str] = []
    for g in globs:
        # resolve relative globs against PROJECT_ROOT; honor absolute globs as-is
        pattern = g if os.path.isabs(g) else str(PROJ_ROOT / g)
        hits = sorted(_glob.glob(pattern))
        paths.extend(hits if hits else [])
        if not hits:
            ckpt["log"].append({"t": _now(), "warn": f"glob matched nothing: {g} (-> {pattern})"})
    seen = {r["path"] for r in ckpt["produced_artifacts"]}
    added = 0
    for pth in paths:
        if pth not in seen:
            ckpt["produced_artifacts"].append(_artifact_record(pth))
            seen.add(pth)
            added += 1
    if settings:
        ckpt["settings"].update(settings)
    # Only advance to `produced` if SOMETHING was recorded (this call or a prior one).
    if ckpt["produced_artifacts"]:
        ckpt["status"] = "produced"
    ckpt["log"].append({"t": _now(), "event": "record_produced", "matched": len(paths), "added": added})
    save(ckpt)
    if not paths:
        ckpt["log"].append({"t": _now(), "warn": "record_produced matched 0 artifacts — status NOT advanced"})
        save(ckpt)
    return ckpt


def mark_verified(stage: str, artifacts: list[str]) -> dict:
    """Move named artifacts from produced -> verified (they passed the stage's gate)."""
    ckpt = load(stage)
    produced = {r["path"]: r for r in ckpt["produced_artifacts"]}
    vset = {r["path"] for r in ckpt["verified_artifacts"]}
    for a in artifacts:
        # accept a bare filename or a full path; match by suffix
        match = next((p for p in produced if p == a or p.endswith("/" + a) or Path(p).name == a), None)
        if match is None:
            ckpt["log"].append({"t": _now(), "warn": f"verify: not in produced set: {a}"})
            continue
        if match not in vset:
            rec = dict(produced[match])
            rec["verified_at"] = _now()
            ckpt["verified_artifacts"].append(rec)
            vset.add(match)
    if ckpt["verified_artifacts"]:
        ckpt["status"] = "verified"
    ckpt["log"].append({"t": _now(), "event": "mark_verified", "count": len(artifacts)})
    save(ckpt)
    return ckpt


def stamp_gate(stage: str, verdict: str, by: str, notes: str = "", allow_empty: bool = False) -> dict:
    """Record a review-gate verdict (the human / self-review decision).

    A PASS is REFUSED unless the stage has at least one VERIFIED artifact (you
    cannot approve a gate on a stage that has produced nothing that passed QC).
    Override with allow_empty=True only for a documentation/discipline stage.
    """
    verdict = verdict.upper()
    if verdict not in ("PASS", "REWORK", "HOLD"):
        raise SystemExit(f"verdict must be PASS|REWORK|HOLD, got {verdict}")
    ckpt = load(stage)
    if verdict == "PASS" and not ckpt.get("verified_artifacts") and not allow_empty:
        raise SystemExit(
            f"refusing PASS on '{stage}': no verified artifacts. "
            f"Run `checkpoint.py verify {stage} <artifact> ...` first "
            f"(or pass --allow-empty for a doc/discipline stage).")
    ckpt["gate"] = {"verdict": verdict, "by": by, "notes": notes, "at": _now()}
    if verdict == "PASS":
        ckpt["status"] = "gated"          # gate cleared -> downstream may run
    elif verdict == "HOLD":
        ckpt["status"] = "held"
    else:
        ckpt["status"] = "produced"       # REWORK -> back to needing work, gate not cleared
    ckpt["log"].append({"t": _now(), "event": "gate", "verdict": verdict, "by": by})
    save(ckpt)
    return ckpt


def reset(stage: str) -> dict:
    ckpt = load(stage)
    ckpt.update(status="pending", produced_artifacts=[], verified_artifacts=[], gate=None)
    ckpt["log"].append({"t": _now(), "event": "reset"})
    save(ckpt)
    return ckpt


def is_gate_clear(stage: str) -> bool:
    """True iff the stage's review-gate has a PASS verdict (downstream may proceed)."""
    ckpt = load(stage)
    return bool(ckpt.get("gate") and ckpt["gate"].get("verdict") == "PASS")


# --------------------------------------------------------------------------- CLI
def _kv(pairs: list[str]) -> dict:
    out = {}
    for p in pairs or []:
        if "=" in p:
            k, v = p.split("=", 1)
            out[k.strip()] = v.strip()
    return out


def _cmd_status(_args) -> int:
    files = sorted(CKPT_DIR.glob("*.json"))
    if not files:
        print("(no checkpoints yet — run `checkpoint.py record <stage> ...` after a stage produces output)")
        return 0
    print(f"{'STAGE':18s} {'STATUS':10s} {'PROD':>5s} {'VRFD':>5s}  GATE")
    print("-" * 62)
    for f in files:
        c = json.loads(f.read_text())
        gate = c.get("gate")
        g = f"{gate['verdict']} by {gate['by']}" if gate else "-"
        print(f"{c['stage']:18s} {c['status']:10s} "
              f"{len(c['produced_artifacts']):>5d} {len(c['verified_artifacts']):>5d}  {g}")
    return 0


def _cmd_show(args) -> int:
    print(json.dumps(load(args.stage), indent=2))
    return 0


def _cmd_record(args) -> int:
    c = record_produced(args.stage, args.produced, _kv(args.settings))
    print(f"[{args.stage}] produced -> {len(c['produced_artifacts'])} artifact(s); status={c['status']}")
    return 0


def _cmd_verify(args) -> int:
    c = mark_verified(args.stage, args.artifacts)
    print(f"[{args.stage}] verified -> {len(c['verified_artifacts'])} artifact(s); status={c['status']}")
    return 0


def _cmd_gate(args) -> int:
    c = stamp_gate(args.stage, args.verdict, args.by, args.notes or "", allow_empty=args.allow_empty)
    print(f"[{args.stage}] gate={c['gate']['verdict']} by {c['gate']['by']}; status={c['status']}")
    return 0


def _cmd_reset(args) -> int:
    reset(args.stage)
    print(f"[{args.stage}] reset -> pending")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description="Pipeline checkpoint store")
    sub = ap.add_subparsers(dest="cmd", required=True)

    sub.add_parser("status").set_defaults(fn=_cmd_status)

    s = sub.add_parser("show"); s.add_argument("stage"); s.set_defaults(fn=_cmd_show)

    s = sub.add_parser("record")
    s.add_argument("stage"); s.add_argument("--produced", nargs="+", required=True)
    s.add_argument("--settings", nargs="*", default=[]); s.set_defaults(fn=_cmd_record)

    s = sub.add_parser("verify")
    s.add_argument("stage"); s.add_argument("artifacts", nargs="+"); s.set_defaults(fn=_cmd_verify)

    s = sub.add_parser("gate")
    s.add_argument("stage"); s.add_argument("--verdict", required=True)
    s.add_argument("--by", required=True); s.add_argument("--notes")
    s.add_argument("--allow-empty", action="store_true",
                   help="permit PASS with no verified artifacts (doc/discipline stages only)")
    s.set_defaults(fn=_cmd_gate)

    s = sub.add_parser("reset"); s.add_argument("stage"); s.set_defaults(fn=_cmd_reset)

    args = ap.parse_args()
    return args.fn(args)


if __name__ == "__main__":
    sys.exit(main())
