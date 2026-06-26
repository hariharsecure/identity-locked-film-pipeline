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

import torch  # noqa: E402
from diffusers import StableDiffusionXLPipeline  # noqa: E402
from peft import PeftModel  # noqa: E402

# --- CONFIG (edit these for your project) ----------------------------------------------
SDXL = "stabilityai/stable-diffusion-xl-base-1.0"
ROOT = Path(__file__).resolve().parent.parent          # repo root (set as you like)
ASSETS = ROOT / "examples" / "demo_character"
OUT = ROOT / "examples" / "demo_character" / "frames"
DEVICE = "mps" if torch.backends.mps.is_available() else "cpu"
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


def load_pipe(char: str, lora_w: float = 1.0):
    print(f"[load] SDXL + {char} LoRA on {DEVICE}", flush=True)
    pipe = StableDiffusionXLPipeline.from_pretrained(
        SDXL, torch_dtype=torch.float32, use_safetensors=True).to(DEVICE)
    pipe.set_progress_bar_config(disable=True)
    lora_dir = LORA_DIRS.get(char)
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


def gen_single(args) -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    s = SHOTS[args.shot]
    results = []
    with acquire_slot(f"keyframe_{args.shot}", est_gb=20.0, timeout_s=10800):
        pipe = load_pipe(args.char, lora_w=1.0)
        neg = NEG + (SOLO_NEG if s["solo"] else "")
        prompt = f"{s['body']}, {STYLE}"
        g = torch.Generator(device=DEVICE).manual_seed(args.seed or s["seed"])
        img = pipe(prompt=prompt, negative_prompt=neg, width=W, height=H,
                   num_inference_steps=STEPS, guidance_scale=CFG, generator=g).images[0]
        fn = OUT / f"{args.shot}.png"
        img.save(fn)
        results.append({"shot": args.shot, "seed": args.seed or s["seed"], "file": str(fn)})
        print(f"[gen] {args.shot} -> {fn.name}", flush=True)
        del pipe
        gc.collect()
        if DEVICE == "mps":
            torch.mps.empty_cache()
    (OUT / f"{args.shot}_buildlog.json").write_text(json.dumps({
        "stack": "SDXL + char LoRA (w1.0)", "res": [W, H], "steps": STEPS, "cfg": CFG,
        "trigger": TRIGGER, "results": results}, indent=2))


def main() -> int:
    ap = argparse.ArgumentParser(description="Identity-lock keyframe (reference)")
    ap.add_argument("--shot", default="S01", choices=list(SHOTS))
    ap.add_argument("--seed", type=int, default=0)
    ap.add_argument("--char", default="demo_character")
    ap.add_argument("--multichar", action="store_true",
                    help="multi-character shot: plate->region-inpaint (see recipe/IDENTITY_LOCK.md)")
    ap.add_argument("--stage", choices=["plate", "faces"], default="plate")
    ap.add_argument("--plate", help="chosen plate PNG for the faces stage")
    args = ap.parse_args()
    if args.multichar:
        print("[multichar] plate->region-inpaint is described in recipe/IDENTITY_LOCK.md; "
              "this reference ships the single-character path. Wire your inpaint pipeline per that doc.")
        return 0
    gen_single(args)
    return 0


if __name__ == "__main__":
    sys.exit(main())
