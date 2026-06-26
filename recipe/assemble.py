#!/usr/bin/env python3
"""
assemble.py — REFERENCE: frame-exact ffmpeg swap / retime / concat / mux.
=========================================================================
Project-agnostic reference for the ASSEMBLE stage. Pure ffmpeg, zero model, zero
identity risk. Swaps per-shot clips into a source timeline at frame-exact windows,
re-encodes to a uniform codec/fps so the concat is clean, concatenates in film
order, and muxes a mixed audio stream onto the cut.

Key safety properties (see director_skills/03_assemble.md):
  - NEVER overwrites a delivered master — writes to a `_<label>` output.
  - FRAME-EXACT GUARD: asserts produced_frames == source_frames (trips on drift).
  - HOLD fallback: hold.json ({"hold": ["S18", ...]}) swaps a drifting shot to a
    static / Ken-Burns fallback clip WITHOUT a code edit.
  - Resumable intermediates (concat lists, video-noaudio timeline).

This is a skeleton: fill in YOUR per-shot windows and clip paths. The ffmpeg
invocations are the load-bearing part; the timeline bookkeeping is project-specific.

Usage:
  python3 assemble.py all     # base (swap) + retime + mux
  python3 assemble.py base    # just the swap+concat -> video-noaudio
  python3 assemble.py mux     # retime + mux audio onto the base
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DEMO = ROOT / "examples" / "demo_character"
ANIM = DEMO / "anim"
WORK = DEMO / "_assemble_work"
OUT = DEMO / "output"

FPS = 24
CRF = 18
LABEL = "v1"
# A delivered master, if any, is sacred — never write to it.
SOURCE_TIMELINE = DEMO / "timeline_noaudio_source.mp4"      # your prior cut to swap INTO (optional)
MIXED_AUDIO = DEMO / "mixed_audio.m4a"                       # VO + score + beds, produced by a mix pass

# Per-shot windows: tag -> (start_frame, end_frame) in the source timeline.
# (Fill these in for your film; placeholders below.)
WINDOWS = {
    "S01": (0, 121),
    "S02": (121, 194),
}


def _ff(cmd: list[str]) -> None:
    print("[ffmpeg]", " ".join(str(c) for c in cmd), flush=True)
    subprocess.run(cmd, check=True)


def frames_of(mp4: Path) -> int:
    out = subprocess.run(
        ["ffprobe", "-v", "error", "-select_streams", "v:0", "-count_frames",
         "-show_entries", "stream=nb_read_frames", "-of", "default=nk=1:nw=1", str(mp4)],
        capture_output=True, text=True)
    try:
        return int(out.stdout.strip())
    except Exception:
        return -1


def load_holds() -> set[str]:
    hp = DEMO / "hold.json"
    if hp.exists():
        return set(json.loads(hp.read_text()).get("hold", []))
    return set()


def reencode_uniform(src: Path, dst: Path) -> None:
    """Re-encode a clip to the uniform codec/fps/pix_fmt so the concat is clean."""
    _ff(["ffmpeg", "-y", "-i", str(src), "-r", str(FPS), "-c:v", "libx264",
         "-profile:v", "high", "-pix_fmt", "yuv420p", "-crf", str(CRF), "-an", str(dst)])


def build_base() -> Path:
    """Re-encode each per-shot clip uniformly and concat in film order -> video-noaudio."""
    WORK.mkdir(parents=True, exist_ok=True)
    holds = load_holds()
    concat_list = WORK / "concat_base.txt"
    lines = []
    for tag in WINDOWS:
        clip = ANIM / f"{tag}_anim.mp4"
        if tag in holds:
            # HOLD: use the static/Ken-Burns fallback clip instead (no code edit).
            clip = ANIM / f"{tag}_hold.mp4"
            print(f"[hold] {tag} -> static fallback {clip.name}", flush=True)
        if not clip.exists():
            print(f"[warn] missing clip for {tag}: {clip} (skipping in this reference run)", flush=True)
            continue
        uni = WORK / f"{tag}_uni.mp4"
        reencode_uniform(clip, uni)
        lines.append(f"file '{uni.as_posix()}'")
    concat_list.write_text("\n".join(lines) + "\n")
    base = WORK / f"full_video_noaudio_{LABEL}.mp4"
    _ff(["ffmpeg", "-y", "-f", "concat", "-safe", "0", "-i", str(concat_list),
         "-c", "copy", str(base)])
    # Frame-exact guard: if you have a SOURCE_TIMELINE, the produced frames must match it.
    if SOURCE_TIMELINE.exists():
        bf, sf = frames_of(base), frames_of(SOURCE_TIMELINE)
        assert bf == sf, f"FRAME DRIFT: produced {bf} != source {sf} (timeline-drift trip)"
        print(f"[guard] frame-exact OK ({bf} == {sf})", flush=True)
    return base


def mux(base: Path) -> Path:
    """Mux the mixed audio onto the base cut (byte-for-byte audio copy)."""
    OUT.mkdir(parents=True, exist_ok=True)
    out = OUT / f"film_{LABEL}.mp4"
    if MIXED_AUDIO.exists():
        _ff(["ffmpeg", "-y", "-i", str(base), "-i", str(MIXED_AUDIO),
             "-map", "0:v:0", "-map", "1:a:0", "-c:v", "copy", "-c:a", "copy",
             "-shortest", str(out)])
    else:
        print(f"[warn] no mixed audio at {MIXED_AUDIO}; emitting video-only", flush=True)
        _ff(["ffmpeg", "-y", "-i", str(base), "-c", "copy", str(out)])
    print(f"[done] -> {out}", flush=True)
    return out


def main() -> int:
    cmd = sys.argv[1] if len(sys.argv) > 1 else "all"
    if cmd in ("base", "all"):
        base = build_base()
    else:
        base = WORK / f"full_video_noaudio_{LABEL}.mp4"
    if cmd in ("mux", "all"):
        mux(base)
    return 0


if __name__ == "__main__":
    sys.exit(main())
