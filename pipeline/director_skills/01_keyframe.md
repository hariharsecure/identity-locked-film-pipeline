# Director Skill — STAGE 1: KEYFRAME (SDXL + char-LoRA + IP-Adapter identity-lock)

*How an agent or a human runs + verifies the keyframe stage. Tool: `sdxl_keyframe`. Gate: **A**.*
*This is the identity-lock advantage — a prompt-only / SVG-rig pipeline has no LoRA / IP-Adapter / face-ID.*

## What this stage decides
**WHO / WHERE / WHAT-COLOR.** The keyframe is the root cause of most defects. A keyframe
defect is NEVER fixed downstream — re-roll the keyframe. (See `../recipe/CONSISTENCY_QC.md`.)

## The stack
- SDXL-base-1.0, **fp32 on MPS**, **1216×704**, **34 steps**, **CFG 6.5**.
- Identity HARD-LOCK: per-character **PEFT LoRA** (`PeftModel.from_pretrained`, weight set by a
  `set_scale` loop — the `cross_attention_kwargs` scale is a NO-OP on a wrapped UNet) **+ IP-Adapter
  ViT-H on the canonical face crop** (`<char>_canonical_face.png`). You can apply face-IP to the
  hardest-to-hold character only and run LoRA-only (face-IP = 0.0) for the rest.
- Style anchor (no-people) IP at **≤0.15** (a high style-anchor scale can erase characters into empty rooms).
- **Multi-char = plate → per-region LoRA inpaint** (a single PEFT UNet holds ONE identity).
- Optional: hard-block `onnxruntime` at import if you want to avoid an insightface/FaceID dependency.

## How to run (reference)
Single-char:
```
python3 ../recipe/keyframe_identity_lock.py --shot S01 --seed 1234 --char demo_character
```
Multi-char (the hard case) — two stages, governor-gated, serial:
```
# 1. plate: re-roll seeds, VIEW each, pick the cleanest multi-figure layout (no LoRA)
python3 ../recipe/keyframe_identity_lock.py --shot S02 --multichar --stage plate
# 2. lock faces on the chosen plate (runs each character region in order)
python3 ../recipe/keyframe_identity_lock.py --shot S02 --multichar --stage faces --plate <plate.png>
```
Governor: each pass wraps `acquire_slot('keyframe_<shot>', est_gb=20.0)`. **One heavy job at a time.**
Write ONLY to a staging dir — never overwrite a source; a delivered master is sacred.

## Wardrobe canon (verify the PIXELS, not the prompt)
Lock a short, per-character wardrobe + colour convention and carry it as a **targeted negative** so a
background colour cannot bleed into a garment. *(Example placeholder: `demo_character = a distinct garment
colour + a load-bearing prop`; carry an anti-`<background-colour>` negative on the garment.)* Define your own
per-character canon and check the **rendered pixels** against it every shot.

## GATE A — verify before ANY animation (batch-level, on the contact sheet)
- [ ] **Identity** reads (LoRA faces correct; no drift/duplication).
- [ ] **Props / load-bearing accessories** survive this lighting and match the standard description.
- [ ] **Wardrobe colour** correct (per your locked per-character convention).
- [ ] **Location geometry** matches; **palette** warm↔cool legible; **count** correct.
- [ ] **Composition / aspect** safe. → **Any miss = re-roll the keyframe** (route via QC #1). Do NOT animate.

## Record the checkpoint + stamp the gate
```
python3 ../checkpoint.py record keyframe --produced 'frames/scene1/S*.png' --settings steps=34 cfg=6.5
python3 ../checkpoint.py verify keyframe S01_scene1.png S02_scene1.png        # the ones that passed Gate A
python3 ../checkpoint.py gate   keyframe --verdict PASS --by reviewer --notes "Gate A clean: count/wardrobe/palette"
```
On a defect: `--verdict REWORK` (gate stays closed → `animate` will not run) and re-key.

## Known failure modes → fix (see `../recipe/CONSISTENCY_QC.md`)
| Symptom | Fix |
|---|---|
| Identity drift (CU) | LoRA w→1.15 + face-IP on canonical crop (0.30 CU / 0.45 masked box) |
| Multi-char LoRA-domination | plate → per-region inpaint (each region its own LoRA, serial) |
| Background colour bleeds into garment | reinforce wardrobe colour + a targeted anti-`<colour>` negative |
| Floating head / no feet | full-body language + anti-`bust only, cropped legs` negative |
| Prop dropped | 77-token CLIP limit → trigger FIRST, load-bearing noun early, shorten ID text |
