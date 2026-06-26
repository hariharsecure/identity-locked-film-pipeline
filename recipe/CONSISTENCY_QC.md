# CONSISTENCY QC — the defect→fix decision tree

*The QC authority for an identity-locked film pipeline. Classify a defect's root
cause in ONE category, route it to exactly ONE knob, re-generate (governor-gated,
serial), and verify against your character canon — not against a drifted frame.*

This is the discipline that makes the pipeline converge instead of thrash. It is
method, not film content — define your own per-character canon and plug it in.

---

## The one rule
**Classify the root cause BEFORE choosing a tool.** The single most expensive mistake
is **seed-sweeping a still that is already wrong.**

> The keyframe (SDXL) decides WHO / WHERE / WHAT-COLOR and is the root cause of most
> defects. The image-to-video pass decides only HOW-IT-MOVES. So never seed-sweep a
> still that is already wrong — re-key it first.

---

## The debug loop (systematic, reproducible)
1. **DIAGNOSE.** Extract the keyframe (f0) + a mid + tail frame. Name the defect in
   **ONE** category: identity · wardrobe/colour · composition/count · framing/body-crop ·
   prop-missing · palette · motion-jitter · 2-figure-collapse · flat/static. Two stacked
   defects → fix the **still** one first.
2. **ROUTE TO THE KNOB** (turn exactly ONE — see the table below).
3. **RE-GEN, governor-gated, serial.** One heavy job at a time. Never overwrite a source;
   write to a staging / suffixed name.
4. **VERIFY AGAINST CANON.** Look at the actual **pixels** (don't trust the prompt). Match
   against your per-character checklist — against the **canon**, NOT a drifted frame. Log
   seed + knob + outcome to the shot manifest so the win is reproducible.

---

## Root cause → the ONE knob
| Diagnosis | Knob | Concrete move |
|---|---|---|
| Identity drift (close-up) | face-IP scale ↑ / + face-crop + LoRA w→1.15 | canonical face crop @0.30 CU / 0.45 masked box |
| LoRA domination (multi-char) | plate→region-inpaint | no-LoRA plate, mask each region, inpaint that char's LoRA serially |
| Wardrobe/colour bleed | prompt + targeted negative | reinforce the garment colour + an anti-`<background-colour>` negative |
| Composition / duplicate / missing | fresh seed + solo/2-shot prompt (+ optional Depth ControlNet) | re-roll the seed — re-keying at the SAME seed keeps the duplicate |
| Body-crop / floating bust | full-body prompt + anti-crop negative | "whole figure head to feet, both feet on the floor" |
| Prop missing | token order | trigger FIRST, load-bearing noun in the first ~60 tokens, shorten ID text (77-token CLIP limit) |
| Palette wrong | lighting clause in-prompt | name the light (warm vs cool) — never swap the style anchor |
| Motion jitter on a CLEAN still | I2V seed (kill 2–3) | vary `--seed`; tail-drift → `--guide-scale`→4.5 + anti-morph negative |
| 2-figure collapse in motion | swap to `TWO_FIGURE_NEG` | drop duplicate/identity-change terms; "both remain"; fewer frames |
| Flat / static scenic | route OUT of generation | depth-parallax or an emotion-hold, not a re-roll |

---

## The decision tree (route a wrong shot)
```
1. STILL wrong (count/figure/face/colour/framing)? → RE-KEY (keyframe stage). Do NOT animate.
2. Still CLEAN but motion jitters/warps/boils?     → SEED-SWEEP the I2V (kill after 2-3).
3. Near-static LONG window unstable at length?     → SHORT-CORE + minterpolate (gen a short stable core, interpolate to length).
4. Flat / static / quiet scenic beat?              → DEPTH-PARALLAX (zero regeneration → zero identity risk).
5. Marginal / defective only at head-or-tail?      → TRIM / re-time (a good 3s beats a bad 6s).
6. Clean but feels un-animated / emotionally flat? → TIMING PASS (zero-model; only after the still passes).
```
**Why kill a seed-sweep after 2–3:** if the result is not **monotonically** improving,
the problem is in the still or the prompt, not the seed. Chasing a "miracle seed" is the
classic time-sink.

---

## The gates (hard stops — a shot does NOT advance with an open defect)
- **GATE A (keyframe, batch-level, before ANY animation):** identity · props-survive-
  lighting · wardrobe colour · location geometry · palette · count · composition. A miss =
  re-roll the keyframe (route #1). This is the most important gate — a keyframe defect is
  never cheaper to fix later.
- **GATE B (clip + cut):** identity holds to the **tail** (drift grows over a clip); no
  flicker / boiling / breathing-BG at speed; props & palette correct across the cuts;
  audio synced; crop safe.

---

## Per-character verify checklist (the floor — define your own)
Write **one short line per character**: the LoRA **trigger word**, the **wardrobe +
colour**, and the **load-bearing prop / identity anchor** (glasses, a scarf, a satchel).
Then match the rendered **pixels** to that line every shot. Keep it in your repo as the
QC canon; verify against it, not against the last frame you rendered (which may have
drifted). These lines are project-specific — this method ships the discipline, not a cast.

---

## Two truths to tape to the wall
1. **The keyframe is the root cause.** Diagnose there first; animation only moves.
2. **Verify against the canon, governor-gated and serial.** One knob, one re-gen, logged.
