#!/usr/bin/env python3
"""
musicgen_score.py — REFERENCE: per-beat music cues via a local music model.
===========================================================================
Project-agnostic reference for the AUDIO/SCORE stage. Generates one short musical
cue per beat with a LOCAL music model (MusicGen-small here), normalizes loudness,
and records actual vs target duration so the QA can catch a truncated cue.

LICENSE CAVEAT (important): MusicGen-small WEIGHTS are CC-BY-NC-4.0 — NON-COMMERCIAL.
This is fine as a fully-local TEMP score, but a COMMERCIAL release MUST swap to a
commercially-licensed model/library or original music. Do NOT claim "commercial-clean"
for a MusicGen score. See THIRD_PARTY_LICENSES.md.

Governor: ONE slot for the whole batch (acquire_slot est_gb=6.0) — serial with all
other heavy generation.

Usage:
  python3 musicgen_score.py
Requires: transformers + torch (and ffmpeg on PATH). Runs on MPS/CUDA/CPU.
"""
from __future__ import annotations

import contextlib
import json
import subprocess
import sys
from pathlib import Path

# --- OPTIONAL governor (use yours, else a no-op; see recipe/GOVERNOR.md) ----------------
try:
    from memory_governor import acquire_slot  # type: ignore
except Exception:  # pragma: no cover
    @contextlib.contextmanager
    def acquire_slot(name: str, est_gb: float = 0.0, timeout_s: int = 7200):
        print(f"[governor] (no-op) would acquire '{name}' est_gb={est_gb}", flush=True)
        yield

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "examples" / "demo_character" / "score"
MODEL = "facebook/musicgen-small"
LOUDNORM = "loudnorm=I=-18:TP=-2:LRA=11"

# EXAMPLE cues: (name, prompt, target_seconds). Define your own palette + arc.
CUES = [
    ("C01_open", "soft solo piano, gentle and warm, slow, intimate, no drums", 8),
    ("C02_wander", "light strings and a bamboo flute, wandering and curious, no percussion", 10),
    ("C03_resolve", "warm strings resolving, hopeful but quiet, gentle, no drums", 8),
]


def ffprobe_seconds(path: Path) -> float:
    out = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration",
         "-of", "default=nk=1:nw=1", str(path)],
        capture_output=True, text=True)
    try:
        return float(out.stdout.strip())
    except Exception:
        return 0.0


def main() -> int:
    try:
        import torch
        from transformers import AutoProcessor, MusicgenForConditionalGeneration
    except Exception:
        print("[error] transformers/torch not installed. `pip install transformers torch`.",
              file=sys.stderr)
        print("        The recipe is model-agnostic — swap in any local music model.", file=sys.stderr)
        return 1
    import scipy.io.wavfile  # type: ignore

    OUT.mkdir(parents=True, exist_ok=True)
    device = "mps" if torch.backends.mps.is_available() else ("cuda" if torch.cuda.is_available() else "cpu")
    results = []
    with acquire_slot("score_musicgen", est_gb=6.0, timeout_s=7200):
        print(f"[load] {MODEL} on {device}", flush=True)
        proc = AutoProcessor.from_pretrained(MODEL)
        model = MusicgenForConditionalGeneration.from_pretrained(MODEL).to(device)
        sr = model.config.audio_encoder.sampling_rate
        for name, prompt, target_s in CUES:
            inputs = proc(text=[prompt], padding=True, return_tensors="pt").to(device)
            max_tokens = int(target_s * 50)   # ~50 tokens/sec for MusicGen
            audio = model.generate(**inputs, max_new_tokens=max_tokens, do_sample=True, guidance_scale=3.0)
            raw = OUT / f"{name}.raw.wav"
            scipy.io.wavfile.write(str(raw), rate=sr, data=audio[0, 0].cpu().numpy())
            final = OUT / f"{name}.wav"
            subprocess.run(["ffmpeg", "-y", "-i", str(raw), "-af", LOUDNORM, "-ar", "44100", str(final)],
                           check=True)
            raw.unlink(missing_ok=True)
            actual = ffprobe_seconds(final)
            print(f"[cue] {name} target={target_s}s actual={actual:.1f}s -> {final.name}", flush=True)
            results.append({"cue": name, "prompt": prompt, "target_s": target_s,
                            "actual_s": actual, "file": str(final)})
    (OUT / "SCORE_MANIFEST.json").write_text(json.dumps(
        {"model": MODEL, "license": "CC-BY-NC-4.0 (non-commercial)", "loudnorm": LOUDNORM,
         "results": results}, indent=2))
    print(f"[done] {len(results)} cue(s) -> {OUT}", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
