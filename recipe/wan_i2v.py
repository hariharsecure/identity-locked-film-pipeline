#!/usr/bin/env python3
"""
wan_i2v.py — REFERENCE: seed-locked, low-motion Wan2.2 image-to-video invocation.
=================================================================================
Project-agnostic reference for the ANIMATE stage. Turns a LOCKED keyframe PNG into
a short, low-motion clip via a Wan2.2 image-to-video generator, anchored to the
keyframe and seeded to the keyframe's seed. Motion lives entirely in the PROMPT.

Recipe (see recipe/IDENTITY_LOCK.md "Animate" + the manifest):
  - keyframe-anchored I2V; FIXED seed = the keyframe seed.
  - 4n+1 frame counts at 24fps: 73=3s, 97=4s, 121=5s, 145=6s, 169=7s.
  - --steps 24 for low-motion cinemagraphs, 30 for fix-shots / payoffs.
  - --guide-scale 5.0 --shift 5.0 --scheduler unipc.
  - heavy anatomy/temporal NEGATIVE on every shot.
  - deliberate two-figure shots drop duplicate/identity-change negatives (TWO_FIGURE_NEG).
  - NO IP-Adapter in this pass — anchor coherence is a keyframe-stage property.

This reference shells out to a Wan2.2 MLX generator via subprocess. Set WAN_PY and
MODEL_DIR to YOUR paths (they are PLACEHOLDERS here). Skip-if-exists -> resumable.
Governor: wraps acquire_slot(est_gb=22.0) — strictly serial, one I2V at a time.

Usage:
  python3 wan_i2v.py            # all shots (skip-if-exists)
  python3 wan_i2v.py S01 S02    # a subset by tag prefix
"""
from __future__ import annotations

import contextlib
import argparse
import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "pipeline"))
from project import ProjectError, frame_count_for_seconds, load_project, project_paths  # noqa: E402

# --- OPTIONAL governor (use yours, else a no-op; see recipe/GOVERNOR.md) ----------------
try:
    from memory_governor import acquire_slot  # type: ignore
except Exception:  # pragma: no cover
    @contextlib.contextmanager
    def acquire_slot(name: str, est_gb: float = 0.0, timeout_s: int = 7200):
        print(f"[governor] (no-op) would acquire '{name}' est_gb={est_gb}", flush=True)
        yield

# --- ENGINE (PLACEHOLDERS — set to your Wan2.2 MLX install) -----------------------------
WAN_PY = "<PATH_TO>/python"                                  # the venv python that has mlx_video
MODEL_DIR = "<PATH_TO>/Wan2.2-TI2V-5B-MLX"                   # the local Wan2.2 checkpoint dir

KF_DIR = ROOT / "examples" / "demo_character" / "frames"
OUT_DIR = ROOT / "examples" / "demo_character" / "anim"

W, H = 1216, 704
GUIDE, SHIFT, FPS = 5.0, 5.0, 24
DUR_FRAMES = {3: 73, 4: 97, 5: 121, 6: 145, 7: 169}         # 4n+1

STYLE_NEG = (
    "ugly, deformed, distorted, watermark, text, blurry, overexposed, "
    "fast jerky motion, flickering, frame border, black frame, static, "
    "extra fingers, poorly drawn hands, deformed hands, malformed limbs, "
    "fused fingers, distorted face, morphing, warping, bad anatomy, "
    "limb deformation, duplicate person, extra person, identity change"
)
# For deliberate two-/multi-figure shots: drop the duplicate/identity-change terms
# (they make I2V collapse the second figure into one). Keep all anatomy/quality terms.
TWO_FIGURE_NEG = (
    "ugly, deformed, distorted, watermark, text, blurry, overexposed, "
    "fast jerky motion, flickering, frame border, black frame, static, "
    "extra fingers, poorly drawn hands, deformed hands, malformed limbs, "
    "fused fingers, distorted face, morphing, warping, bad anatomy, limb deformation"
)
TWO_FIGURE_TAGS = ("S02",)

# EXAMPLE shots: (tag, keyframe_path, num_frames, seed, prompt, motion_note).
# Seeds = the keyframe seeds. Motion lives in the PROMPT.
SHOTS = [
    ("S01", KF_DIR / "S01.png", DUR_FRAMES[5], 1234,
     "watercolor storybook animation, a young outlaw standing calmly in a sunlit forest "
     "clearing, leaves drifting slowly, gentle dappled light shifting, his body still and "
     "steady, only the foliage and light move, painterly, warm",
     "ambient leaf/light drift, figure held"),
    ("S02", KF_DIR / "S02.png", DUR_FRAMES[3], 2345,
     "watercolor storybook animation, two figures walking a forest path together at an easy "
     "pace, both remain present, neither fades nor merges, soft secondary motion in the trees, "
     "painterly, warm",
     "two-figure walk, both remain"),
]


def default_context() -> dict:
    shots = []
    for tag, kf, nframes, seed, prompt, note in SHOTS:
        shots.append({
            "tag": tag,
            "keyframe": kf,
            "out_dir": OUT_DIR,
            "frames": nframes,
            "seed": seed,
            "prompt": prompt,
            "motion_note": note,
            "two_figure": tag in TWO_FIGURE_TAGS,
        })
    return {
        "shots": shots,
        "manifest_dir": OUT_DIR,
        "res": [W, H],
        "guide": GUIDE,
        "shift": SHIFT,
        "fps": FPS,
        "scheduler": "unipc",
        "steps_low": 24,
        "steps_fix": 30,
        "wan_py": WAN_PY,
        "model_dir": MODEL_DIR,
    }


def load_project_context(project_arg: str) -> dict:
    proj = load_project(project_arg)
    paths = project_paths(proj)
    render = proj.get("render") or {}
    animate = render.get("animate") or {}
    res = render.get("res") or [W, H]
    fps = int(render.get("fps") or FPS)
    shots = []
    for shot in proj.get("shots") or []:
        tag = shot.get("id", "")
        scene = shot.get("scene")
        kf_dir = paths["frames"] / scene if scene else paths["frames"]
        out_dir = paths["anim"] / scene if scene else paths["anim"]
        shots.append({
            "tag": tag,
            "keyframe": kf_dir / f"{tag}.png",
            "out_dir": out_dir,
            "frames": frame_count_for_seconds(shot.get("duration_s", 0), fps=fps),
            "seed": int(shot.get("seed") or 0),
            "prompt": shot.get("motion_prompt", ""),
            "motion_note": shot.get("motion_note", ""),
            "two_figure": shot.get("solo") is False,
        })
    return {
        "shots": shots,
        "manifest_dir": paths["anim"],
        "res": res,
        "guide": float(animate.get("guide_scale", GUIDE)),
        "shift": float(animate.get("shift", SHIFT)),
        "fps": fps,
        "scheduler": animate.get("scheduler", "unipc"),
        "steps_low": int(animate.get("steps_low", 24)),
        "steps_fix": int(animate.get("steps_fix", 30)),
        "wan_py": WAN_PY,
        "model_dir": MODEL_DIR,
    }


def frames_of(mp4: Path) -> int:
    out = subprocess.run(
        ["ffprobe", "-v", "error", "-select_streams", "v:0", "-count_frames",
         "-show_entries", "stream=nb_read_frames", "-of", "default=nk=1:nw=1", str(mp4)],
        capture_output=True, text=True)
    try:
        return int(out.stdout.strip())
    except Exception:
        return -1


def run_shot(shot: dict, ctx: dict, steps: int) -> dict:
    tag = shot["tag"]
    out_dir = shot["out_dir"]
    out_dir.mkdir(parents=True, exist_ok=True)
    out_mp4 = out_dir / f"{tag}_anim.mp4"
    if out_mp4.exists():
        print(f"[skip] {tag} exists -> {out_mp4.name}", flush=True)
        return {"shot": tag, "skipped": True, "file": str(out_mp4)}
    neg = TWO_FIGURE_NEG if shot["two_figure"] else STYLE_NEG
    w, h = ctx["res"]
    cmd = [
        ctx["wan_py"], "-m", "mlx_video.models.wan_2.generate",
        "--model-dir", ctx["model_dir"], "--image", str(shot["keyframe"]), "--prompt", shot["prompt"],
        "--negative-prompt", neg, "--width", str(w), "--height", str(h),
        "--num-frames", str(shot["frames"]), "--steps", str(steps),
        "--guide-scale", str(ctx["guide"]), "--shift", str(ctx["shift"]),
        "--scheduler", ctx["scheduler"], "--seed", str(shot["seed"]), "--fps", str(ctx["fps"]),
        "--output", str(out_mp4),
    ]
    print(f"[gen] {tag} seed={shot['seed']} frames={shot['frames']} steps={steps} :: {shot['motion_note']}", flush=True)
    # NOTE: flag names follow a typical Wan2.2 MLX CLI; adjust to your generator's CLI.
    subprocess.run(cmd, check=True)
    return {"shot": tag, "seed": shot["seed"], "frames_requested": shot["frames"],
            "frames_actual": frames_of(out_mp4), "file": str(out_mp4)}


def main() -> int:
    ap = argparse.ArgumentParser(description="Wan2.2 I2V animate pass (reference)")
    ap.add_argument("tags", nargs="*", help="optional shot ids or prefixes")
    ap.add_argument("--project", help="project root or project.yaml")
    args = ap.parse_args()
    try:
        ctx = load_project_context(args.project) if args.project else default_context()
    except ProjectError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    want = set(args.tags)
    shots = [s for s in ctx["shots"] if not want or s["tag"] in want or any(s["tag"].startswith(w) for w in want)]
    results = []
    for shot in shots:
        steps = ctx["steps_fix"] if shot["two_figure"] else ctx["steps_low"]
        with acquire_slot(f"animate_{shot['tag']}", est_gb=22.0, timeout_s=10800):
            results.append(run_shot(shot, ctx, steps))
    ctx["manifest_dir"].mkdir(parents=True, exist_ok=True)
    (ctx["manifest_dir"] / "animation_manifest.json").write_text(json.dumps({
        "engine": "Wan2.2 I2V (MLX)", "res": ctx["res"], "fps": ctx["fps"],
        "guide": ctx["guide"], "shift": ctx["shift"], "scheduler": ctx["scheduler"],
        "results": results}, indent=2))
    print(f"[done] {len(results)} shot(s) -> {ctx['manifest_dir']}", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
