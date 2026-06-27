#!/usr/bin/env python3
"""
keyframe_identity_lock.py — REFERENCE: SDXL + per-character LoRA + IP-Adapter face-lock.
=======================================================================================
This is a project-agnostic REFERENCE implementation of the identity-lock keyframe
recipe (see recipe/IDENTITY_LOCK.md). It demonstrates the wiring on a NEUTRAL,
PUBLIC-DOMAIN demo character (Robin Hood) with PLACEHOLDER triggers/wardrobe — it
is not tuned to any real or proprietary likeness. Train your own character LoRA
(see recipe/train_char_lora.py), drop a canonical face crop in assets/, and edit
the SHOTS table + wardrobe constants below.

Stack: SDXL-base-1.0, fp32 on MPS, 1216x704, 34 steps, CFG 6.5.
  - Identity HARD-LOCK: a per-character PEFT LoRA (PeftModel.from_pretrained), the
    LoRA weight set by a set_scale() loop (NOT cross_attention_kwargs, which is a
    no-op on a wrapped UNet), optionally + IP-Adapter ViT-H on a canonical face crop.
  - Multi-char: generate a no-LoRA "plate" for composition, then per-region inpaint
    each character with that character's LoRA (a single PEFT UNet holds ONE identity).
  - A wardrobe colour is carried as a TARGETED NEGATIVE so a background colour cannot
    bleed into a garment.

Governor: wraps acquire_slot(name, est_gb=20.0) — one heavy job at a time. The
acquire_slot import is OPTIONAL; if you have no governor, the no-op shim below runs
the job directly (single-job machines only — DO run heavy jobs serially yourself).

Usage:
  python3 keyframe_identity_lock.py --shot S01 --seed 1234 --char demo_character
  python3 keyframe_identity_lock.py --shot S02 --multichar --stage plate
  python3 keyframe_identity_lock.py --shot S02 --multichar --stage faces --plate plate.png
"""
from __future__ import annotations

import argparse
import contextlib
import gc
import importlib.util
import json
import sys
import warnings
from pathlib import Path

warnings.filterwarnings("ignore")

# --- OPTIONAL: hard-block onnxruntime at import (avoids an insightface/FaceID dep) -----
_orig_find_spec = importlib.util.find_spec
def _no_onnx(name, *a, **k):
    if name == "onnxruntime" or name.startswith("onnxruntime."):
        return None
    return _orig_find_spec(name, *a, **k)
importlib.util.find_spec = _no_onnx

# --- OPTIONAL governor: use yours if you have one, else a no-op context manager --------
try:
    # Point PYTHONPATH at your governor, or replace this import. See recipe/GOVERNOR.md.
    from memory_governor import acquire_slot  # type: ignore
except Exception:  # pragma: no cover - reference fallback
    @contextlib.contextmanager
    def acquire_slot(name: str, est_gb: float = 0.0, timeout_s: int = 7200):
        # NO governor available: run directly. On a single workstation, still run
        # heavy jobs ONE AT A TIME yourself to avoid an out-of-memory kill.
        print(f"[governor] (no-op) would acquire '{name}' est_gb={est_gb}", flush=True)
        yield

# --- CONFIG (edit these for your project) ----------------------------------------------
SDXL = "stabilityai/stable-diffusion-xl-base-1.0"
ROOT = Path(__file__).resolve().parent.parent          # repo root (set as you like)
sys.path.insert(0, str(ROOT / "pipeline"))
from project import ProjectError, load_project, project_paths  # noqa: E402

ASSETS = ROOT / "examples" / "demo_character"
OUT = ROOT / "examples" / "demo_character" / "frames"
W, H, STEPS, CFG = 1216, 704, 34, 6.5

# PLACEHOLDER identity constants — replace with YOUR trained trigger + wardrobe canon.
TRIGGER = "demochar"                                     # your LoRA trigger token
WARDROBE = "in a green hood and tunic, a longbow on his back"   # neutral, public-domain demo
STYLE = "watercolor storybook, warm earth palette, painterly"
NEG = (
    "photo, realistic, 3d render, cgi, plastic, harsh light, text, watermark, "
    "deformed, extra limbs, bad hands, fused fingers, lowres, off-model, identity change, "
    # Example wardrobe-colour guard: keep the garment colour, block a background colour
    # from bleeding into it (swap to YOUR garment/background colours):
    "blue tunic, blue hood, blue garment, blue clothing"
)
SOLO_NEG = ", multiple people, two people, second person, duplicate person, crowd"
# Drop the duplicate/identity-change terms for DELIBERATE multi-figure shots:
TWO_FIGURE_NEG = (
    "photo, realistic, 3d render, cgi, plastic, harsh light, text, watermark, "
    "deformed, extra limbs, bad hands, fused fingers, lowres, off-model"
)

# Per-character LoRA dirs (train your own — see recipe/train_char_lora.py).
LORA_DIRS = {
    "demo_character": ASSETS / "demo_character_lora_unet_peft",
}
# Optional IP-Adapter face crop per character (None -> LoRA-only for that char).
FACE_CROPS = {
    "demo_character": ASSETS / "demo_character_canonical_face.png",
}

# EXAMPLE shots (replace with your shot list). PLACEHOLDER public-domain content.
SHOTS = {
    "S01": dict(seed=1234, solo=True,
                body=f"{TRIGGER}, a young outlaw {WARDROBE}, standing in a sunlit forest clearing"),
    "S02": dict(seed=2345, solo=False,
                body=f"{TRIGGER} and a companion {WARDROBE}, walking a forest path together"),
}


def default_context() -> dict:
    return {
        "assets": ASSETS,
        "frames": OUT,
        "shots": {tag: dict(spec, out_dir=OUT, who=["demo_character"]) for tag, spec in SHOTS.items()},
        "style": STYLE,
        "neg": NEG,
        "solo_neg": SOLO_NEG,
        "two_figure_neg": TWO_FIGURE_NEG,
        "use_two_figure_neg": False,
        "res": [W, H],
        "steps": STEPS,
        "cfg": CFG,
        "triggers": {"demo_character": TRIGGER},
        "wardrobe": {"demo_character": WARDROBE},
        "lora_dirs": dict(LORA_DIRS),
        "face_crops": dict(FACE_CROPS),
    }


def _maybe_path(base: Path, value):
    if value is None:
        return None
    p = Path(str(value))
    return p if p.is_absolute() else base / p


def load_project_context(project_arg: str) -> dict:
    proj = load_project(project_arg)
    paths = project_paths(proj)
    render = proj.get("render") or {}
    keyframe = render.get("keyframe") or {}
    identity = proj.get("identity") or {}
    triggers = {}
    wardrobe = {}
    lora_dirs = {}
    face_crops = {}
    for char_id, spec in identity.items():
        triggers[char_id] = spec.get("trigger", "")
        wardrobe[char_id] = spec.get("wardrobe", "")
        lora_dirs[char_id] = _maybe_path(paths["root"], spec.get("lora_dir"))
        face_crops[char_id] = _maybe_path(paths["root"], spec.get("face_crop"))
    shots = {}
    for shot in proj.get("shots") or []:
        tag = shot.get("id", "")
        scene = shot.get("scene")
        out_dir = paths["frames"] / scene if scene else paths["frames"]
        shots[tag] = {
            "seed": int(shot.get("seed") or 0),
            "solo": bool(shot.get("solo")),
            "body": shot.get("keyframe_prompt", ""),
            "who": list(shot.get("who") or []),
            "out_dir": out_dir,
        }
    negatives = proj.get("negatives") or {}
    res = render.get("res") or [W, H]
    return {
        "assets": paths["root"],
        "frames": paths["frames"],
        "shots": shots,
        "style": proj.get("style", STYLE),
        "neg": negatives.get("base", NEG),
        "solo_neg": negatives.get("solo_extra", SOLO_NEG),
        "two_figure_neg": negatives.get("two_figure", TWO_FIGURE_NEG),
        "use_two_figure_neg": True,
        "res": res,
        "steps": int(keyframe.get("steps", STEPS)),
        "cfg": float(keyframe.get("cfg", CFG)),
        "triggers": triggers,
        "wardrobe": wardrobe,
        "lora_dirs": lora_dirs,
        "face_crops": face_crops,
    }


def set_lora_weight(unet, w: float) -> int:
    """Set LoRA scale via set_scale() (cross_attention_kwargs is a no-op on a wrapped UNet)."""
    n = 0
    for m in unet.modules():
        if hasattr(m, "lora_A") and hasattr(m, "set_scale"):
            try:
                m.set_scale("default", w)
                n += 1
            except Exception:
                pass
    return n


def _device(torch_mod) -> str:
    return "mps" if torch_mod.backends.mps.is_available() else "cpu"


def load_pipe(char: str, ctx: dict, torch_mod, device: str, lora_w: float = 1.0):
    from diffusers import StableDiffusionXLPipeline
    from peft import PeftModel

    print(f"[load] SDXL + {char} LoRA on {device}", flush=True)
    pipe = StableDiffusionXLPipeline.from_pretrained(
        SDXL, torch_dtype=torch_mod.float32, use_safetensors=True).to(device)
    pipe.set_progress_bar_config(disable=True)
    lora_dir = ctx["lora_dirs"].get(char)
    if lora_dir and Path(lora_dir).exists():
        pipe.unet = PeftModel.from_pretrained(pipe.unet, str(lora_dir))
        n = set_lora_weight(pipe.unet, lora_w)
        print(f"[lora] {char} live on {n} modules (w{lora_w})", flush=True)
    else:
        print(f"[lora] (none found at {lora_dir}) — running base SDXL (demo)", flush=True)
    # IP-Adapter face-lock would be loaded here (pipe.load_ip_adapter(...)) and the
    # face crop passed as ip_adapter_image at call time. Omitted in the reference to
    # keep it dependency-light; see recipe/IDENTITY_LOCK.md for the exact wiring.
    return pipe


def gen_single(args, ctx: dict) -> None:
    import torch

    s = ctx["shots"][args.shot]
    char = args.char
    if char not in ctx["lora_dirs"] and s.get("who"):
        char = s["who"][0]
    out_dir = s["out_dir"]
    out_dir.mkdir(parents=True, exist_ok=True)
    device = _device(torch)
    w, h = ctx["res"]
    results = []
    with acquire_slot(f"keyframe_{args.shot}", est_gb=20.0, timeout_s=10800):
        pipe = load_pipe(char, ctx, torch, device, lora_w=1.0)
        if s["solo"]:
            neg = ctx["neg"] + ctx["solo_neg"]
        elif ctx.get("use_two_figure_neg"):
            neg = ctx["two_figure_neg"]
        else:
            neg = ctx["neg"]
        prompt = f"{s['body']}, {ctx['style']}"
        seed = args.seed or s["seed"]
        g = torch.Generator(device=device).manual_seed(seed)
        img = pipe(prompt=prompt, negative_prompt=neg, width=w, height=h,
                   num_inference_steps=ctx["steps"], guidance_scale=ctx["cfg"], generator=g).images[0]
        fn = out_dir / f"{args.shot}.png"
        img.save(fn)
        results.append({"shot": args.shot, "seed": seed, "file": str(fn)})
        print(f"[gen] {args.shot} -> {fn.name}", flush=True)
        del pipe
        gc.collect()
        if device == "mps":
            torch.mps.empty_cache()
    (out_dir / f"{args.shot}_buildlog.json").write_text(json.dumps({
        "stack": "SDXL + char LoRA (w1.0)", "res": [w, h], "steps": ctx["steps"], "cfg": ctx["cfg"],
        "trigger": ctx["triggers"].get(char, ""), "results": results}, indent=2))


def main() -> int:
    ap = argparse.ArgumentParser(description="Identity-lock keyframe (reference)")
    ap.add_argument("--shot", default="S01")
    ap.add_argument("--seed", type=int, default=0)
    ap.add_argument("--char", default="demo_character")
    ap.add_argument("--project", help="project root or project.yaml")
    ap.add_argument("--multichar", action="store_true",
                    help="multi-character shot: plate->region-inpaint (see recipe/IDENTITY_LOCK.md)")
    ap.add_argument("--stage", choices=["plate", "faces"], default="plate")
    ap.add_argument("--plate", help="chosen plate PNG for the faces stage")
    args = ap.parse_args()
    if args.multichar:
        print("[multichar] plate->region-inpaint is described in recipe/IDENTITY_LOCK.md; "
            "this reference ships the single-character path. Wire your inpaint pipeline per that doc.")
        return 0
    try:
        ctx = load_project_context(args.project) if args.project else default_context()
    except ProjectError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    if args.shot not in ctx["shots"]:
        print(f"[error] unknown shot {args.shot}; known shots: {', '.join(ctx['shots'])}", file=sys.stderr)
        return 1
    gen_single(args, ctx)
    return 0


if __name__ == "__main__":
    sys.exit(main())
