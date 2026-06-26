# Identity-locked agentic film pipeline

**Hold one photoreal character across a whole short film — and let an agent drive the
multi-stage pipeline reliably, with human review-gates between stages.** Fully local,
$0/render. This repo ships the **method + the scaffold**, not any particular film.

> The differentiator is the **identity-lock recipe**: a per-character LoRA + IP-Adapter
> face-lock for the keyframe, and plate→region-inpaint for multi-character frames. Most
> agentic-video tools are prompt-only or cartoon-rig — they have **no cross-shot photoreal
> identity.** That recipe is the thing they lack. See [`recipe/IDENTITY_LOCK.md`](recipe/IDENTITY_LOCK.md).

## The pitch (3 bullets)
1. **Hold one photoreal character across a whole film.** Per-character LoRA + IP-Adapter
   face-lock + plate→region-inpaint for multi-character frames + an empirical defect→fix QC.
2. **An agent can drive it.** A YAML pipeline manifest + an auto-discovering tool-registry +
   JSON checkpoints (resumable) + per-stage director-skills + human review-gates — so a
   coding assistant runs the multi-stage pipeline reliably and you approve between stages.
3. **Local, owned, governor-gated.** Fully local weights (SDXL / Wan2.2 / a local music
   model / local-or-network TTS), RAM-gated so one heavy job runs at a time. No cloud keys,
   no per-render cost. *(Some upstream weights are non-commercial — see
   [`THIRD_PARTY_LICENSES.md`](THIRD_PARTY_LICENSES.md).)*

## Honest framing
This **borrows a well-known agentic-orchestration pattern** (manifest + tool-registry +
checkpoints + review-gate + director-skills) and re-implements it cleanly — no third-party
orchestration code is copied (see [`docs/VS_OPENMONTAGE.md`](docs/VS_OPENMONTAGE.md)). The
**original contribution** is the **identity-lock recipe** + the **empirical consistency QC**.

This is **not** "the world's first" anything — prior agentic-video projects exist and some
claim character consistency. The defensible, demonstrated claim is narrow and concrete:
**a local, identity-locked, agent-drivable pipeline plus a reproducible single-character
continuity recipe.** The example demonstrates the wiring on a throwaway **public-domain**
demo character (Robin Hood) with placeholder settings — it does not assert quality the demo
doesn't show. Train your own character and bring your own story.

## Layout
```
.
├── README.md                  # this file
├── LICENSE                    # Apache-2.0 (our code/docs)
├── THIRD_PARTY_LICENSES.md    # SDXL / Wan2.2 / MusicGen / IP-Adapter upstream licenses (some NON-commercial)
├── CONTRIBUTING.md
├── config.example.yaml        # machine-specific paths (model dirs, governor) live HERE, not in the manifest
├── pipeline/                  # THE SCAFFOLD
│   ├── pipeline.yaml          # the manifest (5 stages + QC; generic example)
│   ├── tool_registry.yaml     # the auto-discovering tool registry
│   ├── tools.py  checkpoint.py  run.py
│   ├── director_skills/01..06_*.md
│   └── checkpoints/           # per-stage JSON checkpoints land here
├── recipe/                    # THE DIFFERENTIATOR — method docs + reference code
│   ├── IDENTITY_LOCK.md       # SDXL + LoRA + IP-Adapter face-lock, plate→region-inpaint
│   ├── CONSISTENCY_QC.md      # the defect→fix decision tree + the gates
│   ├── GOVERNOR.md            # RAM-gating heavy local gen (one job at a time)
│   ├── keyframe_identity_lock.py   # reference keyframe impl (placeholder triggers/wardrobe)
│   ├── wan_i2v.py                  # reference seed-locked low-motion I2V
│   ├── assemble.py                 # reference frame-exact swap/retime/mux
│   ├── train_char_lora.py          # train YOUR OWN character (public-domain/synthetic dataset)
│   ├── tts_vo.py                   # reference VO temp pass (network TTS) + loudnorm
│   └── musicgen_score.py           # reference local music cues (NON-commercial weights)
├── examples/
│   └── demo_character/        # a public-domain demo character end-to-end (NOT a real likeness)
└── docs/
    └── VS_OPENMONTAGE.md      # honest comparison: the borrowed pattern vs the identity-lock addition
```

## Quick start
```bash
# 1) validate the scaffold (it ships pointing at the reference scripts)
cd pipeline && python3 tools.py validate

# 2) see the plan / the next runnable stage
python3 run.py plan
python3 run.py next

# 3) train your own character LoRA (public-domain / synthetic / consented dataset)
python3 ../recipe/train_char_lora.py --instance-dir <your_images> --trigger demochar \
    --output ../examples/demo_character/demo_character_lora_unet_peft --dry-run

# 4) run a keyframe (reference; edit the SHOTS table + wardrobe constants first)
python3 ../recipe/keyframe_identity_lock.py --shot S01 --seed 1234

# 5) record + gate, then animate/assemble/score per the director-skills
python3 checkpoint.py record keyframe --produced 'examples/demo_character/frames/S*.png'
```
Read [`pipeline/README.md`](pipeline/README.md) for the full driving loop and
[`recipe/IDENTITY_LOCK.md`](recipe/IDENTITY_LOCK.md) for the identity method.

## Requirements
- Python 3.10+, `torch`, `diffusers`, `transformers`, `peft`, `pyyaml`; `ffmpeg`/`ffprobe`
  on PATH. Apple-silicon (MPS) or CUDA for the heavy stages. `edge-tts` for the VO temp pass.
- Model weights downloaded from upstream (see `THIRD_PARTY_LICENSES.md` — **do not** expect
  any weights in this repo).

## License
Apache-2.0 for this repo's code and docs (`LICENSE`). Upstream **model weights carry their
own licenses — some are non-commercial** (`THIRD_PARTY_LICENSES.md`). Comply with each.
