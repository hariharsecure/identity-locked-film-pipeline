#!/usr/bin/env python3
"""
proof_assets.py — GPU-free proof executor for a project.yaml.
=============================================================
Builds a low-resolution, muxed proof film with the same pipeline shape as the
heavy path: keyframes -> animations, VO + score, mix, assemble/mux. It imports no
model stacks and invokes no heavy recipe scripts.

Usage:
  python3 recipe/proof_assets.py --project <root-or-yaml> [--res 640x360] [--keep]
Requires: Pillow, ffmpeg/ffprobe, and optionally macOS `say`.
"""
from __future__ import annotations

import argparse
import json
import math
import shutil
import subprocess
import sys
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "pipeline"))
from project import (  # noqa: E402
    ProjectError, frame_count_for_seconds, load_project, project_paths, validate_project)

VO_LOUDNORM = "loudnorm=I=-16:TP=-1.5:LRA=11"
SCORE_LOUDNORM = "loudnorm=I=-18:TP=-2:LRA=11"


def _ff(cmd: list[str]) -> None:
    print("[ffmpeg]", " ".join(str(c) for c in cmd), flush=True)
    subprocess.run(cmd, check=True)


def _slug(value: str) -> str:
    out = []
    for ch in value:
        out.append(ch if ch.isalnum() or ch in ("-", "_") else "_")
    return "".join(out).strip("_") or "item"


def _parse_res(value: str) -> tuple[int, int]:
    parts = value.lower().split("x", 1)
    if len(parts) != 2:
        raise argparse.ArgumentTypeError("expected WIDTHxHEIGHT")
    try:
        w, h = int(parts[0]), int(parts[1])
    except Exception:
        raise argparse.ArgumentTypeError("expected WIDTHxHEIGHT")
    if w <= 0 or h <= 0:
        raise argparse.ArgumentTypeError("resolution must be positive")
    return w, h


def _shot_frame_path(paths: dict, shot: dict) -> Path:
    scene = shot.get("scene")
    base = paths["frames"] / scene if scene else paths["frames"]
    return base / f"{shot['id']}.png"


def _shot_anim_path(paths: dict, shot: dict) -> Path:
    scene = shot.get("scene")
    base = paths["anim"] / scene if scene else paths["anim"]
    return base / f"{shot['id']}_anim.mp4"


def _wrap_text(draw: ImageDraw.ImageDraw, text: str, font, max_width: int) -> list[str]:
    words = text.split()
    if not words:
        return [""]
    lines: list[str] = []
    cur = words[0]
    for word in words[1:]:
        test = f"{cur} {word}"
        if draw.textlength(test, font=font) <= max_width:
            cur = test
        else:
            lines.append(cur)
            cur = word
    lines.append(cur)
    return lines


def _draw_centered(draw: ImageDraw.ImageDraw, lines: list[str], y: int, width: int, font, fill) -> None:
    line_h = 16
    for i, line in enumerate(lines):
        text_w = draw.textlength(line, font=font)
        draw.text(((width - text_w) / 2, y + i * line_h), line, fill=fill, font=font)


def build_keyframes(proj: dict, paths: dict, res: tuple[int, int]) -> list[Path]:
    w, h = res
    font = ImageFont.load_default()
    palette = [
        (44, 78, 88),
        (91, 64, 48),
        (78, 88, 54),
        (82, 68, 94),
        (92, 74, 39),
    ]
    written = []
    thumbs = []
    for idx, shot in enumerate(proj.get("shots") or []):
        out = _shot_frame_path(paths, shot)
        out.parent.mkdir(parents=True, exist_ok=True)
        color = palette[idx % len(palette)]
        img = Image.new("RGB", (w, h), color)
        draw = ImageDraw.Draw(img)
        draw.rectangle([12, 12, w - 12, h - 12], outline=(238, 232, 214), width=3)
        title = f"{shot['id']} | {', '.join(shot.get('who') or [])}"
        label = (shot.get("keyframe_prompt") or "")[:90]
        _draw_centered(draw, _wrap_text(draw, title, font, w - 60), h // 2 - 34, w, font, (255, 250, 230))
        _draw_centered(draw, _wrap_text(draw, label, font, w - 80), h // 2 + 6, w, font, (224, 217, 196))
        img.save(out)
        written.append(out)
        thumbs.append(img.resize((160, 90)))
        print(f"[proof:keyframe] {shot['id']} -> {out}", flush=True)
    if thumbs:
        cols = min(4, len(thumbs))
        rows = int(math.ceil(len(thumbs) / cols))
        sheet = Image.new("RGB", (cols * 160, rows * 90), (20, 22, 24))
        for idx, thumb in enumerate(thumbs):
            sheet.paste(thumb, ((idx % cols) * 160, (idx // cols) * 90))
        contact = paths["frames"] / "contact_sheet.png"
        contact.parent.mkdir(parents=True, exist_ok=True)
        sheet.save(contact)
        written.append(contact)
    return written


def frames_of(mp4: Path) -> int:
    out = subprocess.run(
        ["ffprobe", "-v", "error", "-select_streams", "v:0", "-count_frames",
         "-show_entries", "stream=nb_read_frames", "-of", "default=nk=1:nw=1", str(mp4)],
        capture_output=True, text=True)
    try:
        return int(out.stdout.strip())
    except Exception:
        return -1


def seconds_of(path: Path) -> float:
    out = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration",
         "-of", "default=nk=1:nw=1", str(path)],
        capture_output=True, text=True)
    try:
        return float(out.stdout.strip())
    except Exception:
        return 0.0


def has_stream(path: Path, selector: str) -> bool:
    out = subprocess.run(
        ["ffprobe", "-v", "error", "-select_streams", selector,
         "-show_entries", "stream=index", "-of", "csv=p=0", str(path)],
        capture_output=True, text=True)
    return bool(out.stdout.strip())


def build_animations(proj: dict, paths: dict, res: tuple[int, int]) -> tuple[list[Path], int]:
    fps = int((proj.get("render") or {}).get("fps") or 24)
    w, h = res
    clips = []
    expected_total = 0
    for shot in proj.get("shots") or []:
        frames = frame_count_for_seconds(shot.get("duration_s", 0), fps=fps)
        expected_total += frames
        src = _shot_frame_path(paths, shot)
        out = _shot_anim_path(paths, shot)
        out.parent.mkdir(parents=True, exist_ok=True)
        vf = (
            f"scale={w}:{h},"
            f"zoompan=z='min(zoom+0.0008,1.05)':"
            f"x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)':d={frames}:s={w}x{h}:fps={fps},"
            "format=yuv420p"
        )
        _ff(["ffmpeg", "-y", "-loop", "1", "-framerate", str(fps), "-i", str(src),
             "-vf", vf, "-frames:v", str(frames), "-r", str(fps),
             "-c:v", "libx264", "-profile:v", "high", "-pix_fmt", "yuv420p",
             "-an", str(out)])
        actual = frames_of(out)
        if actual != frames:
            raise RuntimeError(f"{out}: expected {frames} frames, got {actual}")
        clips.append(out)
        print(f"[proof:animate] {shot['id']} {frames}f -> {out}", flush=True)
    return clips, expected_total


def _text_duration(text: str) -> float:
    return max(0.8, min(12.0, 0.055 * max(len(text), 1)))


def _fallback_audio(path: Path, seconds: float) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    _ff(["ffmpeg", "-y", "-f", "lavfi", "-i",
         "anullsrc=channel_layout=stereo:sample_rate=44100", "-t", f"{seconds:.3f}",
         "-af", VO_LOUDNORM, "-c:a", "aac", "-b:a", "128k", str(path)])


def build_vo(proj: dict, paths: dict, keep: bool) -> list[Path]:
    out_dir = paths["vo_clips"]
    out_dir.mkdir(parents=True, exist_ok=True)
    vo = proj.get("vo") or {}
    lines = vo.get("lines") or []
    say_bin = shutil.which("say")
    results = []
    clips = []
    for line in lines:
        tag = line.get("tag", "VO")
        speaker = line.get("speaker", "speaker")
        text = line.get("text", "")
        stem = _slug(f"{tag}_{speaker}_proof")
        raw = out_dir / f"{stem}.aiff"
        final = out_dir / f"{stem}.m4a"
        used_say = False
        if say_bin:
            try:
                subprocess.run([say_bin, "-o", str(raw), text], check=True, capture_output=True, text=True)
                _ff(["ffmpeg", "-y", "-i", str(raw), "-af", VO_LOUDNORM,
                     "-ar", "44100", "-c:a", "aac", "-b:a", "128k", str(final)])
                used_say = True
                if not keep:
                    raw.unlink(missing_ok=True)
            except Exception as exc:
                print(f"[proof:vo] say failed for {tag}; using silent stand-in ({exc})", flush=True)
                _fallback_audio(final, _text_duration(text))
        else:
            print(f"[proof:vo] say unavailable for {tag}; using silent stand-in", flush=True)
            _fallback_audio(final, _text_duration(text))
        clips.append(final)
        results.append({"tag": tag, "speaker": speaker, "text_len": len(text),
                        "seconds": seconds_of(final), "used_say": used_say, "file": str(final)})
        print(f"[proof:vo] {tag} -> {final}", flush=True)
    (out_dir / "VO_MANIFEST.json").write_text(json.dumps(
        {"loudnorm": VO_LOUDNORM, "results": results}, indent=2))
    return clips


def build_score(proj: dict, paths: dict) -> list[Path]:
    out_dir = paths["score"]
    out_dir.mkdir(parents=True, exist_ok=True)
    cues = (proj.get("score") or {}).get("cues") or []
    results = []
    clips = []
    for idx, cue in enumerate(cues):
        name = _slug(cue.get("name", f"C{idx + 1:02d}"))
        target_s = float(cue.get("target_s") or 1.0)
        freq = 220 + (idx % 5) * 55
        out = out_dir / f"{name}.wav"
        _ff(["ffmpeg", "-y", "-f", "lavfi", "-i",
             f"sine=frequency={freq}:duration={target_s:.3f}:sample_rate=44100",
             "-af", SCORE_LOUDNORM, "-ar", "44100", str(out)])
        clips.append(out)
        results.append({"cue": name, "target_s": target_s, "seconds": seconds_of(out), "file": str(out)})
        print(f"[proof:score] {name} -> {out}", flush=True)
    (out_dir / "SCORE_MANIFEST.json").write_text(json.dumps(
        {"loudnorm": SCORE_LOUDNORM, "results": results}, indent=2))
    return clips


def _concat_list(paths: list[Path], list_path: Path) -> None:
    lines = [f"file '{p.as_posix()}'" for p in paths]
    list_path.write_text("\n".join(lines) + "\n")


def concat_audio(files: list[Path], out: Path, work: Path) -> Path | None:
    if not files:
        return None
    if len(files) == 1:
        _ff(["ffmpeg", "-y", "-i", str(files[0]), "-c:a", "aac", "-b:a", "160k", str(out)])
        return out
    list_path = work / f"{out.stem}_concat.txt"
    _concat_list(files, list_path)
    _ff(["ffmpeg", "-y", "-f", "concat", "-safe", "0", "-i", str(list_path),
         "-c:a", "aac", "-b:a", "160k", str(out)])
    return out


def mix_audio(vo_clips: list[Path], score_clips: list[Path], paths: dict, total_s: float) -> Path:
    work = paths["work"]
    work.mkdir(parents=True, exist_ok=True)
    vo_bed = concat_audio(vo_clips, work / "proof_vo_concat.m4a", work)
    score_bed = concat_audio(score_clips, work / "proof_score_concat.m4a", work)
    mixed = paths["root"] / "mixed_audio.m4a"
    inputs = [p for p in (vo_bed, score_bed) if p is not None]
    cmd = ["ffmpeg", "-y", "-f", "lavfi", "-t", f"{total_s:.3f}", "-i",
           "anullsrc=channel_layout=stereo:sample_rate=44100"]
    for path in inputs:
        cmd.extend(["-i", str(path)])
    if inputs:
        cmd.extend(["-filter_complex",
                    f"amix=inputs={len(inputs) + 1}:duration=first:dropout_transition=0,{VO_LOUDNORM}",
                    "-c:a", "aac", "-b:a", "160k", str(mixed)])
    else:
        cmd.extend(["-c:a", "aac", "-b:a", "160k", str(mixed)])
    _ff(cmd)
    print(f"[proof:mix] -> {mixed}", flush=True)
    return mixed


def concat_video(clips: list[Path], paths: dict, fps: int) -> Path:
    if not clips:
        raise RuntimeError("no animation clips to assemble")
    work = paths["work"]
    work.mkdir(parents=True, exist_ok=True)
    list_path = work / "proof_video_concat.txt"
    _concat_list(clips, list_path)
    base = work / "proof_video_noaudio.mp4"
    _ff(["ffmpeg", "-y", "-f", "concat", "-safe", "0", "-i", str(list_path),
         "-r", str(fps), "-c:v", "libx264", "-profile:v", "high",
         "-pix_fmt", "yuv420p", "-crf", "18", "-an", str(base)])
    return base


def mux(base_video: Path, mixed_audio: Path, paths: dict) -> Path:
    out = paths["output"] / "film_proof.mp4"
    out.parent.mkdir(parents=True, exist_ok=True)
    _ff(["ffmpeg", "-y", "-i", str(base_video), "-i", str(mixed_audio),
         "-map", "0:v:0", "-map", "1:a:0", "-c:v", "copy", "-c:a", "aac",
         "-movflags", "+faststart", str(out)])
    return out


def run(project_arg: str, res: tuple[int, int], keep: bool) -> Path:
    try:
        proj = load_project(project_arg)
    except ProjectError as exc:
        print(f"error: {exc}", file=sys.stderr)
        raise SystemExit(1)
    problems = validate_project(proj)
    if problems:
        for problem in problems:
            print(f"- {problem}", file=sys.stderr)
        raise SystemExit(1)
    paths = project_paths(proj)
    for key in ("frames", "anim", "vo_clips", "score", "output", "work"):
        paths[key].mkdir(parents=True, exist_ok=True)
    fps = int((proj.get("render") or {}).get("fps") or 24)

    build_keyframes(proj, paths, res)
    anim_clips, expected_frames = build_animations(proj, paths, res)
    vo_clips = build_vo(proj, paths, keep)
    score_clips = build_score(proj, paths)
    total_s = expected_frames / float(fps)
    mixed_audio = mix_audio(vo_clips, score_clips, paths, total_s)
    base_video = concat_video(anim_clips, paths, fps)
    final = mux(base_video, mixed_audio, paths)

    actual_frames = frames_of(final)
    if not final.exists():
        raise RuntimeError(f"missing proof output: {final}")
    if not has_stream(final, "v:0"):
        raise RuntimeError(f"missing video stream: {final}")
    if not has_stream(final, "a:0"):
        raise RuntimeError(f"missing audio stream: {final}")
    if actual_frames != expected_frames:
        raise RuntimeError(f"proof frame mismatch: expected {expected_frames}, got {actual_frames}")

    print("\nPROOF SUMMARY")
    print(f"  output      : {final}")
    print(f"  duration_s  : {seconds_of(final):.3f}")
    print(f"  frames      : {actual_frames}")
    print("  streams     : video=yes audio=yes")
    return final


def main() -> int:
    ap = argparse.ArgumentParser(description="GPU-free proof executor")
    ap.add_argument("--project", required=True, help="project root or project.yaml")
    ap.add_argument("--res", type=_parse_res, default=(640, 360), help="proof resolution WIDTHxHEIGHT")
    ap.add_argument("--keep", action="store_true", help="keep temporary say AIFF files")
    args = ap.parse_args()
    run(args.project, args.res, args.keep)
    return 0


if __name__ == "__main__":
    sys.exit(main())
