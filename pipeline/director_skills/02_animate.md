# Director Skill — STAGE 2: ANIMATE (Wan2.2 image-to-video, seed-locked)

*How an agent or a human runs + verifies the animation stage. Tool: `wan_i2v`. Gate: **B (clip)**.*

## What this stage decides
**Only HOW-IT-MOVES.** It cannot fix a bad still. **Never animate a keyframe that has not passed
Gate A** — a motion pass cannot rescue a bad frame (see `../recipe/CONSISTENCY_QC.md`).

## The stack
- Image→video via a Wan2.2 I2V generator (MLX path on Apple silicon), anchored to the keyframe PNG.
- **MLX, not ComfyUI** on Apple silicon (sidesteps the float8-on-MPS break).
- Settings: `--width 1216 --height 704`, **`--num-frames` = 4n+1** (73=3s, 97=4s, 121=5s, 145=6s, 169=7s @24fps),
  **`--steps` 24** (low-motion cinemagraphs) **or 30** (fix-shots + payoffs), `--guide-scale 5.0 --shift 5.0
  --scheduler unipc`, **fixed seed = the keyframe seed**.
- Motion lives **entirely in the prompt** ("mostly still, single slow blink, secondary motion only").
- The I2V pass carries **NO IP-Adapter** — anchor coherence is a keyframe-stage property only.

## How to run (reference)
```
# full sequence (skip-if-exists → safe to resume after any interruption)
python3 ../recipe/wan_i2v.py
# subset (pass tag prefixes)
python3 ../recipe/wan_i2v.py S01 S02
```
Governor: each shot wraps `acquire_slot('animate_<tag>', est_gb=22.0)`. **Strictly serial — one I2V at a time.**
Keyframes are READ-ONLY; writes only into `anim/<scene>/`. Produces per-shot `*_anim.mp4` + a
`*_animation_manifest.json` (seed/frames/ffprobe-verify) + a stitched preview.

## Two-/multi-figure shots
Use **`TWO_FIGURE_NEG`** — DROP the `duplicate person, extra person, identity change` terms (they FIGHT a
deliberate two-figure shot and make I2V collapse the second figure into one); KEEP all anatomy/quality
terms. Add "BOTH remain present, neither fades or merges" + fewer frames (3s).

## GATE B (clip) — per-shot QA (self-review; PASS auto-advances)
Extract frames **f0 / mid / tail** and look at the pixels (basics-first):
- [ ] Identity holds **to the tail** (drift grows over a clip).
- [ ] Props / wardrobe colour correct; **count** stays right (no merge/spawn).
- [ ] No **flicker / boiling / breathing-BG / first-frame flash / face-or-hand warp** at speed.

## Record the checkpoint + stamp the gate
```
python3 ../checkpoint.py record animate --produced 'anim/scene1/S*_anim.mp4'
python3 ../checkpoint.py verify animate S01_anim.mp4 S02_anim.mp4
python3 ../checkpoint.py gate   animate --verdict PASS --by agent --notes "Gate B clip: id-to-tail, no flicker"
```

## Defect → fix (route via `../recipe/CONSISTENCY_QC.md` — do NOT seed-sweep a bad still)
| Symptom | Route |
|---|---|
| Motion jitters/warps on a CLEAN still | **#2 seed-sweep** the I2V (kill after 2-3 unless monotonically better) |
| Drift grows over the clip | shorten 4n+1; `--guide-scale`→4.5 + anti-morph negative |
| 2-figure collapse in motion | swap to **`TWO_FIGURE_NEG`** + "both remain" + fewer frames |
| Near-static LONG window unstable | **#3 short-core + minterpolate** (e.g. 145f core → 331f window) |
| Flat / static scenic beat | **#4 depth-parallax** (zero regeneration → zero identity risk) |
| Marginal / head-or-tail defect | **#5 trim** (a bad 6s shot → a good 3s shot, faster than chasing a miracle seed) |
| The STILL is wrong | **STOP — re-key (Stage 1).** Animation cannot rescue it. |
