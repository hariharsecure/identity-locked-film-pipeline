#!/usr/bin/env python3
"""
tts_vo.py — REFERENCE: per-line voiceover (network TTS temp pass) + loudnorm + verify.
======================================================================================
Project-agnostic reference for the AUDIO/VO stage temp pass. Synthesizes each VO
line with a light NETWORK TTS (edge-tts here), normalizes loudness, and verifies
that each clip's duration is proportional to its text (a too-short clip = a dropped
or garbled line). The emotional FINAL pass (a local TTS, governor-slotted) is a
separate, heavier step — see director_skills/04_audio_vo.md.

Casting: define a {speaker: voice} table and tag the voice into the filename so the
QA can confirm the right voice per speaker. The voices below are PLACEHOLDERS.

Usage:
  python3 tts_vo.py
Requires: edge-tts (pip install edge-tts), ffmpeg/ffprobe on PATH.
"""
from __future__ import annotations

import asyncio
import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "examples" / "demo_character" / "vo_clips"

LOUDNORM = "loudnorm=I=-16:TP=-1.5:LRA=11"

# EXAMPLE casting (replace locale/voice with your own). Filename tag = voice.
CASTING = {
    "narrator": "<your-locale>-<VoiceName>Neural",
    "character_a": "<your-locale>-<VoiceName>Neural",
}

# EXAMPLE VO lines: (tag, speaker, text). Neutral, non-narrative placeholders.
LINES = [
    ("S01", "narrator", "The forest was quiet that morning."),
    ("S02", "character_a", "We should keep moving while the light holds."),
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


async def synth_line(tag: str, speaker: str, text: str) -> dict:
    import edge_tts  # imported here so the file imports even without the dep installed
    voice = CASTING.get(speaker, "<your-locale>-<VoiceName>Neural")
    raw = OUT / f"{tag}_{speaker}_{voice}.raw.mp3"
    final = OUT / f"{tag}_{speaker}_{voice}.mp3"
    await edge_tts.Communicate(text, voice).save(str(raw))
    subprocess.run(
        ["ffmpeg", "-y", "-i", str(raw), "-af", LOUDNORM, "-ar", "44100", str(final)],
        check=True)
    raw.unlink(missing_ok=True)
    secs = ffprobe_seconds(final)
    ok = secs > 0 and secs >= 0.04 * max(len(text), 1)   # crude duration-proportional check
    print(f"[vo] {tag} {speaker} {secs:.2f}s {'OK' if ok else 'SHORT?'} -> {final.name}", flush=True)
    return {"tag": tag, "speaker": speaker, "voice": voice, "seconds": secs,
            "text_len": len(text), "ok": ok, "file": str(final)}


async def run() -> list[dict]:
    OUT.mkdir(parents=True, exist_ok=True)
    results = []
    for tag, speaker, text in LINES:
        results.append(await synth_line(tag, speaker, text))
    return results


def main() -> int:
    try:
        import edge_tts  # noqa: F401
    except Exception:
        print("[error] edge-tts not installed. `pip install edge-tts` (a network TTS).", file=sys.stderr)
        print("        The recipe is TTS-agnostic — swap in any TTS that emits per-line audio.",
              file=sys.stderr)
        return 1
    results = asyncio.run(run())
    (OUT / "VO_MANIFEST.json").write_text(json.dumps(
        {"loudnorm": LOUDNORM, "casting": CASTING, "results": results}, indent=2))
    print(f"[done] {len(results)} VO line(s) -> {OUT}", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
