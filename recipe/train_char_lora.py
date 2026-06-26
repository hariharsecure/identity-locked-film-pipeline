#!/usr/bin/env python3
"""
train_char_lora.py — REFERENCE: train YOUR OWN character LoRA for SDXL.
======================================================================
Project-agnostic reference for training a per-character PEFT LoRA on SDXL so you
can hold ONE character across a film (the identity-lock recipe). Train on YOUR OWN
character. The demo dataset MUST be a PUBLIC-DOMAIN or SYNTHETIC face — never a
real person's likeness without consent.

This is a thin wrapper / launcher around a standard SDXL LoRA (DreamBooth-style)
trainer. We recommend the well-maintained `diffusers` example
`train_dreambooth_lora_sdxl.py` (Apache-2.0) rather than re-implementing the
training loop. This script just documents the recommended hyper-params and shells
out to that trainer so the recipe is reproducible.

Dataset guidance (see recipe/IDENTITY_LOCK.md):
  - 15-30 images of the SAME character, varied pose/expression/lighting, plain-ish
    backgrounds, consistent wardrobe (or caption the wardrobe out if it should vary).
  - One canonical TIGHT FACE CROP saved separately for IP-Adapter at inference.
  - A unique, rare trigger token (e.g. "demochar") that the captions all use.

Usage:
  python3 train_char_lora.py --instance-dir ./examples/demo_character/dataset \
      --trigger demochar --output ./examples/demo_character/demo_character_lora_unet_peft
"""
from __future__ import annotations

import argparse
import shutil
import subprocess
import sys
from pathlib import Path

SDXL = "stabilityai/stable-diffusion-xl-base-1.0"
VAE = "madebyollin/sdxl-vae-fp16-fix"   # optional fp16-safe VAE for training

# Recommended hyper-params for a single-character identity LoRA on SDXL.
RECOMMENDED = dict(
    resolution=1024,
    train_batch_size=1,
    gradient_accumulation_steps=4,
    learning_rate=1e-4,
    lr_scheduler="constant",
    lr_warmup_steps=0,
    max_train_steps=1200,        # 800-1500 typical; watch for over-fit (identity rigidity)
    rank=16,                     # LoRA rank; 8-32 typical
    mixed_precision="no",        # fp32 on MPS; "bf16"/"fp16" on CUDA
    seed=42,
)


def main() -> int:
    ap = argparse.ArgumentParser(description="Train a per-character SDXL LoRA (reference launcher)")
    ap.add_argument("--instance-dir", required=True, help="folder of YOUR character's training images")
    ap.add_argument("--trigger", required=True, help="rare trigger token used in captions, e.g. demochar")
    ap.add_argument("--output", required=True, help="output dir for the PEFT LoRA")
    ap.add_argument("--trainer", default="train_dreambooth_lora_sdxl.py",
                    help="path to the diffusers SDXL LoRA trainer (Apache-2.0)")
    ap.add_argument("--dry-run", action="store_true", help="print the command, do not launch")
    args = ap.parse_args()

    instance = Path(args.instance_dir)
    if not instance.exists():
        print(f"[error] instance dir not found: {instance}", file=sys.stderr)
        print("        Put 15-30 images of YOUR (public-domain/synthetic/consented) character there.",
              file=sys.stderr)
        return 1

    trainer = shutil.which(args.trainer) or args.trainer
    prompt = f"a photo of {args.trigger} character"
    cmd = [
        sys.executable, str(trainer),
        f"--pretrained_model_name_or_path={SDXL}",
        f"--pretrained_vae_model_name_or_path={VAE}",
        f"--instance_data_dir={instance}",
        f"--instance_prompt={prompt}",
        f"--output_dir={args.output}",
        f"--resolution={RECOMMENDED['resolution']}",
        f"--train_batch_size={RECOMMENDED['train_batch_size']}",
        f"--gradient_accumulation_steps={RECOMMENDED['gradient_accumulation_steps']}",
        f"--learning_rate={RECOMMENDED['learning_rate']}",
        f"--lr_scheduler={RECOMMENDED['lr_scheduler']}",
        f"--lr_warmup_steps={RECOMMENDED['lr_warmup_steps']}",
        f"--max_train_steps={RECOMMENDED['max_train_steps']}",
        f"--rank={RECOMMENDED['rank']}",
        f"--mixed_precision={RECOMMENDED['mixed_precision']}",
        f"--seed={RECOMMENDED['seed']}",
    ]
    print("[train] recommended command:\n  " + " \\\n  ".join(cmd), flush=True)
    if args.dry_run:
        print("[dry-run] not launching. Remove --dry-run to train.")
        return 0
    print("[train] launching the diffusers SDXL LoRA trainer ...", flush=True)
    subprocess.run(cmd, check=True)
    print(f"[done] LoRA -> {args.output}", flush=True)
    print("Next: save ONE tight face crop as <char>_canonical_face.png for IP-Adapter at inference.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
