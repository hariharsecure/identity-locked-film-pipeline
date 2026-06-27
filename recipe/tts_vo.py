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
import argparse
import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "pipeline"))
from project import ProjectError, load_project, project_paths  # noqa: E402

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


def load_project_context(project_arg: str) -> tuple[Path, dict, list[tuple[str, str, str]]]:
    proj = load_project(project_arg)
    paths = project_paths(proj)
    vo = proj.get("vo") or {}
    casting = dict(vo.get("casting") or {})
    lines = []
    for line in vo.get("lines") or []:
        lines.append((line.get("tag", ""), line.get("speaker", ""), line.get("text", "")))
    return paths["vo_clips"], casting, lines


async def synth_line(out_dir: Path, casting: dict, tag: str, speaker: str, text: str) -> dict:
    import edge_tts  # imported here so the file imports even without the dep installed
    voice = casting.get(speaker, "<your-locale>-<VoiceName>Neural")
    raw = out_dir / f"{tag}_{speaker}_{voice}.raw.mp3"
    final = out_dir / f"{tag}_{speaker}_{voice}.mp3"
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


async def run(out_dir: Path, casting: dict, lines: list[tuple[str, str, str]]) -> list[dict]:
    out_dir.mkdir(parents=True, exist_ok=True)
    results = []
    for tag, speaker, text in lines:
        results.append(await synth_line(out_dir, casting, tag, speaker, text))
    return results


def main() -> int:
    ap = argparse.ArgumentParser(description="Voiceover temp pass (reference)")
    ap.add_argument("--project", help="project root or project.yaml")
    args = ap.parse_args()
    out_dir, casting, lines = OUT, CASTING, LINES
    if args.project:
        try:
            out_dir, casting, lines = load_project_context(args.project)
        except ProjectError as exc:
            print(f"error: {exc}", file=sys.stderr)
            return 1
    try:
        import edge_tts  # noqa: F401
    except Exception:
        print("[error] edge-tts not installed. `pip install edge-tts` (a network TTS).", file=sys.stderr)
        print("        The recipe is TTS-agnostic — swap in any TTS that emits per-line audio.",
              file=sys.stderr)
        return 1
    results = asyncio.run(run(out_dir, casting, lines))
    (out_dir / "VO_MANIFEST.json").write_text(json.dumps(
        {"loudnorm": LOUDNORM, "casting": casting, "results": results}, indent=2))
    print(f"[done] {len(results)} VO line(s) -> {out_dir}", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
