#!/usr/bin/env python3
# Project manifest loader.
# ========================
# Schema fields:
#   schema_version: "1.0"              # manifest contract version
#   project_id: <slug>                # stable project slug, e.g. demo_character
#   title: <str>                      # human-readable film title
#   logline: <str>                    # optional one-line description
#   paths:                            # paths are relative to the project root
#     root: .                         # base artifact dir inside the project dir
#     frames: frames                  # keyframe PNGs
#     anim: anim                      # per-shot animation clips
#     vo_clips: vo_clips              # voiceover clips
#     score: score                    # score cues
#     output: output                  # finished cuts
#     work: _assemble_work            # assembly scratch/intermediates
#   identity:                         # one block per character id
#     <char_id>:
#       trigger: <lora-trigger-token> # LoRA trigger token
#       wardrobe: <str>               # wardrobe and colour canon line
#       lora_dir: <relpath or null>   # runtime LoRA dir, gitignored
#       face_crop: <relpath or null>  # runtime face crop, gitignored
#   style: <str>                      # global visual style clause
#   negatives:                        # optional named negative prompt banks
#     base: <str>
#     solo_extra: <str>
#     two_figure: <str>
#   render:                           # shared render settings
#     res: [1216, 704]
#     fps: 24
#     keyframe: {steps: 34, cfg: 6.5}
#     animate: {guide_scale: 5.0, shift: 5.0, scheduler: unipc,
#               steps_low: 24, steps_fix: 30}
#   shots:                            # ordered shot list
#     - id: S01
#       who: [<char_id>, ...]
#       scene: scene1
#       seed: 1234
#       solo: true
#       keyframe_prompt: <str>
#       motion_prompt: <str>
#       motion_note: <str>
#       duration_s: 5
#   vo:
#     casting: {<speaker>: <locale-voice>}
#     lines:
#       - {tag: S01, speaker: narrator, text: <str>}
#   score:
#     cues:
#       - {name: C01_open, prompt: <str>, target_s: 8}
#   mode: full                        # full | proof
from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

import yaml

PATH_KEYS = ("frames", "anim", "vo_clips", "score", "output", "work")
REQUIRED_PATH_KEYS = ("root",) + PATH_KEYS


class ProjectError(Exception):
    """A user-facing project.yaml load/parse error (clean message, no traceback)."""


def load_project(project_root_or_yaml) -> dict:
    """Load a project.yaml from a directory or direct YAML path.

    Raises ProjectError (with a readable message) if the path is missing or the
    YAML is malformed, so callers can surface a clean error instead of a traceback.
    """
    src = Path(project_root_or_yaml).expanduser()
    yaml_path = src / "project.yaml" if src.is_dir() else src
    yaml_path = yaml_path.resolve()
    try:
        text = yaml_path.read_text()
    except FileNotFoundError:
        hint = " (expected a project.yaml inside it)" if src.is_dir() else ""
        raise ProjectError(f"no project.yaml found at: {yaml_path}{hint}")
    except OSError as exc:
        raise ProjectError(f"could not read project.yaml at {yaml_path}: {exc}")
    try:
        data = yaml.safe_load(text) or {}
    except yaml.YAMLError as exc:
        raise ProjectError(f"malformed YAML in {yaml_path}: {exc}")
    if not isinstance(data, dict):
        data = {"_error": "project.yaml must contain a mapping at the top level"}
    data["_yaml_path"] = yaml_path
    data["_root"] = yaml_path.parent
    return data


def _join(base: Path, value) -> Path:
    p = Path(str(value))
    if p.is_absolute():
        return p.resolve()
    return (base / p).resolve()


def project_paths(proj: dict) -> dict[str, Path]:
    """Return resolved artifact paths. Callers decide when to create them."""
    raw_paths = proj.get("paths") or {}
    root_rel = raw_paths.get("root", ".")
    root = _join(proj["_root"], root_rel)
    out = {"root": root}
    for key in PATH_KEYS:
        out[key] = _join(root, raw_paths.get(key, key))
    return out


def frame_count_for_seconds(sec, fps: int = 24) -> int:
    """Return the nearest Wan-friendly 4n+1 frame count for a duration."""
    try:
        seconds = float(sec)
    except Exception:
        seconds = 0.0
    try:
        rate = int(fps)
    except Exception:
        rate = 24
    rate = max(rate, 1)
    frames = int(4 * round((seconds * rate - 1) / 4) + 1)
    if seconds >= 3:
        frames = max(frames, 73)
    return max(frames, 1)


def _is_nonempty_str(value) -> bool:
    return isinstance(value, str) and bool(value.strip())


def _is_relpath(value) -> bool:
    return value is None or (_is_nonempty_str(value) and not Path(value).is_absolute())


def _need(mapping: dict, key: str, where: str, problems: list[str]) -> None:
    if key not in mapping:
        problems.append(f"{where}: missing required key '{key}'")


def validate_project(proj: dict) -> list[str]:
    """Return human-readable schema problems. Empty list means valid."""
    problems: list[str] = []
    if not isinstance(proj, dict):
        return ["project: expected a mapping"]
    if proj.get("_error"):
        problems.append(str(proj["_error"]))

    for key in ("schema_version", "project_id", "title", "paths", "identity",
                "style", "render", "shots", "vo", "score", "mode"):
        _need(proj, key, "project", problems)

    if proj.get("schema_version") != "1.0":
        problems.append("schema_version: expected '1.0'")
    project_id = proj.get("project_id")
    if not _is_nonempty_str(project_id):
        problems.append("project_id: required non-empty slug")
    elif not re.match(r"^[a-z0-9][a-z0-9_-]*$", project_id):
        problems.append("project_id: use a lowercase slug with letters, digits, '_' or '-'")
    if not _is_nonempty_str(proj.get("title")):
        problems.append("title: required non-empty string")
    if "logline" in proj and proj.get("logline") is not None and not isinstance(proj.get("logline"), str):
        problems.append("logline: expected string if present")
    if not _is_nonempty_str(proj.get("style")):
        problems.append("style: required non-empty string")
    if proj.get("mode") not in ("full", "proof"):
        problems.append("mode: expected 'full' or 'proof'")

    raw_paths = proj.get("paths")
    if not isinstance(raw_paths, dict):
        problems.append("paths: expected mapping")
    else:
        for key in REQUIRED_PATH_KEYS:
            if not _is_nonempty_str(raw_paths.get(key)):
                problems.append(f"paths.{key}: required relative path string")
            elif Path(raw_paths[key]).is_absolute():
                problems.append(f"paths.{key}: must be relative to the project root")

    identity = proj.get("identity")
    char_ids: set[str] = set()
    if not isinstance(identity, dict) or not identity:
        problems.append("identity: expected non-empty mapping")
    else:
        for char_id, spec in identity.items():
            if not _is_nonempty_str(char_id):
                problems.append("identity: character ids must be non-empty strings")
                continue
            char_ids.add(char_id)
            where = f"identity.{char_id}"
            if not isinstance(spec, dict):
                problems.append(f"{where}: expected mapping")
                continue
            for key in ("trigger", "wardrobe"):
                if not _is_nonempty_str(spec.get(key)):
                    problems.append(f"{where}.{key}: required non-empty string")
            for key in ("lora_dir", "face_crop"):
                if key not in spec:
                    problems.append(f"{where}.{key}: missing required key")
                elif not _is_relpath(spec.get(key)):
                    problems.append(f"{where}.{key}: expected relative path or null")

    negatives = proj.get("negatives", {})
    if negatives is not None:
        if not isinstance(negatives, dict):
            problems.append("negatives: expected mapping if present")
        else:
            for key, value in negatives.items():
                if value is not None and not isinstance(value, str):
                    problems.append(f"negatives.{key}: expected string")

    render = proj.get("render")
    if not isinstance(render, dict):
        problems.append("render: expected mapping")
    else:
        res = render.get("res")
        if (not isinstance(res, list) or len(res) != 2 or
                not all(isinstance(v, int) and v > 0 for v in res)):
            problems.append("render.res: expected [width, height] positive integers")
        if not isinstance(render.get("fps"), int) or render.get("fps", 0) <= 0:
            problems.append("render.fps: expected positive integer")
        for block in ("keyframe", "animate"):
            if not isinstance(render.get(block), dict):
                problems.append(f"render.{block}: expected mapping")

    shots = proj.get("shots")
    shot_ids: set[str] = set()
    if not isinstance(shots, list):
        problems.append("shots: expected list")
    elif not shots:
        problems.append("shots: expected at least one shot")
    else:
        for idx, shot in enumerate(shots):
            where = f"shots[{idx}]"
            if not isinstance(shot, dict):
                problems.append(f"{where}: expected mapping")
                continue
            sid = shot.get("id")
            if not _is_nonempty_str(sid):
                problems.append(f"{where}.id: required non-empty string")
            elif sid in shot_ids:
                problems.append(f"{where}.id: duplicate shot id '{sid}'")
            else:
                shot_ids.add(sid)
            who = shot.get("who")
            if not isinstance(who, list) or not who:
                problems.append(f"{where}.who: expected non-empty list")
            else:
                for char_id in who:
                    if char_id not in char_ids:
                        problems.append(f"{where}.who: unknown identity '{char_id}'")
            for key in ("scene", "keyframe_prompt", "motion_prompt", "motion_note"):
                if not _is_nonempty_str(shot.get(key)):
                    problems.append(f"{where}.{key}: required non-empty string")
            if not isinstance(shot.get("seed"), int):
                problems.append(f"{where}.seed: expected integer")
            if not isinstance(shot.get("solo"), bool):
                problems.append(f"{where}.solo: expected boolean")
            try:
                if float(shot.get("duration_s")) <= 0:
                    problems.append(f"{where}.duration_s: expected positive number")
            except Exception:
                problems.append(f"{where}.duration_s: expected positive number")

    vo = proj.get("vo")
    casting = {}
    if not isinstance(vo, dict):
        problems.append("vo: expected mapping")
    else:
        casting = vo.get("casting")
        if not isinstance(casting, dict):
            problems.append("vo.casting: expected mapping")
            casting = {}
        lines = vo.get("lines")
        if not isinstance(lines, list):
            problems.append("vo.lines: expected list")
        else:
            for idx, line in enumerate(lines):
                where = f"vo.lines[{idx}]"
                if not isinstance(line, dict):
                    problems.append(f"{where}: expected mapping")
                    continue
                for key in ("tag", "speaker", "text"):
                    if not _is_nonempty_str(line.get(key)):
                        problems.append(f"{where}.{key}: required non-empty string")
                if _is_nonempty_str(line.get("tag")) and line.get("tag") not in shot_ids:
                    problems.append(f"{where}.tag: unknown shot id '{line.get('tag')}'")
                speaker = line.get("speaker")
                if _is_nonempty_str(speaker) and speaker not in casting:
                    problems.append(f"{where}.speaker: not present in vo.casting")

    score = proj.get("score")
    if not isinstance(score, dict):
        problems.append("score: expected mapping")
    else:
        cues = score.get("cues")
        if not isinstance(cues, list):
            problems.append("score.cues: expected list")
        else:
            for idx, cue in enumerate(cues):
                where = f"score.cues[{idx}]"
                if not isinstance(cue, dict):
                    problems.append(f"{where}: expected mapping")
                    continue
                for key in ("name", "prompt"):
                    if not _is_nonempty_str(cue.get(key)):
                        problems.append(f"{where}.{key}: required non-empty string")
                try:
                    if float(cue.get("target_s")) <= 0:
                        problems.append(f"{where}.target_s: expected positive number")
                except Exception:
                    problems.append(f"{where}.target_s: expected positive number")

    return problems


def _cmd_validate(args) -> int:
    try:
        proj = load_project(args.project)
    except Exception as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    problems = validate_project(proj)
    if problems:
        for p in problems:
            print(f"- {p}")
        return 1
    print(f"OK: {proj.get('project_id')} ({proj.get('title')})")
    return 0


def _cmd_show(args) -> int:
    try:
        proj = load_project(args.project)
    except Exception as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    paths = project_paths(proj)
    print(f"project_id : {proj.get('project_id')}")
    print(f"title      : {proj.get('title')}")
    print(f"mode       : {proj.get('mode')}")
    print(f"yaml       : {proj.get('_yaml_path')}")
    print("paths:")
    for key in ("root",) + PATH_KEYS:
        print(f"  {key:8s}: {paths[key]}")
    print("counts:")
    print(f"  shots   : {len(proj.get('shots') or [])}")
    print(f"  vo      : {len((proj.get('vo') or {}).get('lines') or [])}")
    print(f"  cues    : {len((proj.get('score') or {}).get('cues') or [])}")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description="Project manifest loader")
    sub = ap.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("validate")
    s.add_argument("project")
    s.set_defaults(fn=_cmd_validate)
    s = sub.add_parser("show")
    s.add_argument("project")
    s.set_defaults(fn=_cmd_show)
    args = ap.parse_args()
    return args.fn(args)


if __name__ == "__main__":
    sys.exit(main())
