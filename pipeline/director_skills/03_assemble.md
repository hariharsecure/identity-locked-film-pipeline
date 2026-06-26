# Director Skill — STAGE 3: ASSEMBLE (pure ffmpeg: swap / retime / concat / mux)

*How an agent or a human runs + verifies the assemble stage. Tool: `ffmpeg_assemble`. Gate: **B (cut)**.*

## What this stage decides
**Timing / order / the final mux.** Zero model, **zero identity risk**. Swaps per-shot clips into the
timeline at frame-exact windows, applies the retime filtergraph, concatenates in film order, muxes audio.
**NEVER overwrites a delivered master** — write to a `_<label>` output.

## The pattern (reference — `../recipe/assemble.py`)
- **Step A (base):** swap clips into the source timeline at the EXACT per-shot windows; non-target spans
  re-encoded frame-accurate (CRF18, libx264 high, yuv420p, fps=24) so the concat is codec-uniform.
- **Step B (retime+mux):** apply the retime filtergraph to the base, then mux the audio stream
  (`-c:a copy` — byte-for-byte).
- **Frame-exact guard:** asserts `produced_frames == source_frames` — trips on any timeline drift. This
  is the safety net; do not remove it.
- **HOLD fallback:** `hold.json` (`{"hold": ["S18", ...]}`) flips a drifting shot to its Ken-Burns/static
  fallback clip **without editing code** — the verify step can hold a shot at assemble time.

## How to run (reference)
```
python3 ../recipe/assemble.py all     # base + retime + mux
# or step-by-step:
python3 ../recipe/assemble.py base
python3 ../recipe/assemble.py mux
```
No governor slot needed (ffmpeg, LOCAL_CPU). Intermediates (`concat_*.txt`, `full_video_noaudio_*.mp4`)
are written to the work dir and are resumable.

## Dependency
Runs only after **animate** (shots) + **audio_vo** + **audio_score** have cleared their gates — it muxes
the mixed audio (VO + score + beds, ducking, any deliberate silences) onto the cut.

## GATE B (cut) — final QA on the assembled cut
- [ ] Identity holds to the **end** of every shot; props / palette correct across the actual cuts.
- [ ] **No flicker at speed**; eyelines / continuity read across the cut (≥30° between same-subject cuts).
- [ ] **Audio synced** (recompute `-itsoffset` from the rendered duration); ducking + bed levels right.
- [ ] Crops to your delivery aspect (e.g. 2.39:1) with nothing important lost; the master aspect is kept.
- [ ] ffprobe: expected frame count / duration / codec; **0 decode errors**.

## Record the checkpoint + stamp the gate
```
python3 ../checkpoint.py record assemble --produced 'output/film_v1.mp4'
python3 ../checkpoint.py verify assemble film_v1.mp4
python3 ../checkpoint.py gate   assemble --verdict PASS --by reviewer --notes "Gate B cut: synced, no decode errors, crop safe"
```

## On a defect at the cut
Identify the **offending shot** and re-open ITS stage (keyframe or animate) — do not re-do the whole cut.
A motion/identity defect that only shows in one shot is a `hold.json` candidate (static fallback) while
the shot is re-worked.
