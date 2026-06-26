# Pipeline (the scaffold)

**An identity-locked, agentic, governor-gated film pipeline.** This formalizes a
generative-film pipeline as a resumable, auditable, agent-drivable stage graph —
borrowing the agentic-orchestration *pattern* (manifest + tool-registry +
checkpoints + review-gate + per-stage director-skill) and pairing it with a
local stack (SDXL + char-LoRA + IP-Adapter identity-lock, Wan2.2 I2V, local TTS,
local music, a defect->fix QC discipline, RAM-gating via a memory governor).
*(Commercial-clean note: SDXL/Wan2.2 are commercially usable; a MusicGen-small
TEMP score is CC-BY-NC — a commercial release swaps it for a licensed score. See
`tool_registry.yaml > musicgen_score.license_note` and `../THIRD_PARTY_LICENSES.md`.)*

> It **wraps** your generation scripts — it does **not** modify or replace them.
> The manifest is the contract; the scripts remain the implementation. The
> entrypoints in `tool_registry.yaml` ship pointing at the project-agnostic
> reference scripts in `../recipe/` so `tools.py validate` resolves out-of-the-box;
> repoint them at your own tuned scripts in a real project.

## What's here
| File | Role |
|---|---|
| `pipeline.yaml` | The **manifest**: 5 stages + QC, each with inputs/outputs/tool/deps/gate/RAM-class. Plus the explicit `advantages` block (the differentiators) and the gate definitions. |
| `tool_registry.yaml` | The **tool-registry**: each stage's tool, with purpose / runtime / RAM cost (governor `est_gb`) / in-out / fallback / director-skill / entrypoints. Auto-discoverable. |
| `tools.py` | Registry **loader + auto-discovery + validation** — asserts every entrypoint exists on disk and the manifest↔registry are consistent. `tools.py validate`. |
| `checkpoint.py` | **JSON checkpoint store** (one per stage): produced + verified artifacts, gate verdict, settings, log. Resumable + auditable. `checkpoint.py status`. |
| `run.py` | The **planner + review-gate driver**: derives build order from deps, shows status/gates, tells you what's runnable vs gate-blocked, and prints the exact command (with the governor call) for the next stage. **Plans, does not execute heavy gen.** |
| `director_skills/01..06_*.md` | One **director-skill per stage**: how to run + verify that stage, with its Gate checklist + defect→fix routing. |
| `checkpoints/` | Where the per-stage JSON checkpoints land (empty until a stage produces output). |

## The 5 stages
```
keyframe ──► animate ──► assemble ──► (output cut)
 (SDXL+LoRA   (Wan2.2     (ffmpeg
  +IP-Adapter  I2V, seed-  swap/retime
  identity-    locked)     /concat/mux)
  lock)                       ▲
                              │ mux
audio_vo  ─────────────────────┤  (network TTS / local emotional TTS)
audio_score ───────────────────┘  (local music model, per-beat cues)

QC (defect→fix routing) is cross-cutting: owns Gate A (keyframe) + Gate B (clip+cut) + audio gate.
```
- **keyframe** decides WHO/WHERE/WHAT-COLOR (root cause of most defects) — `sdxl_keyframe`, ~20GB, Gate A.
- **animate** decides only HOW-IT-MOVES — `wan_i2v`, ~22GB, Gate B (clip).
- **assemble** = timing/order/mux, zero identity risk — `ffmpeg_assemble`, ~0GB, Gate B (cut).
- **audio_vo** = voiceover — `tts_vo` (network → local emotional), Gate AUDIO.
- **audio_score** = per-beat music cues — `musicgen_score`, ~6GB, Gate AUDIO.
- **qc** = the defect→fix routing — `consistency_qc`, the gate authority.

## How to drive it (an agent or a human)
```bash
cd pipeline

python3 tools.py validate            # auto-discover: assert every tool's script exists on disk
python3 run.py plan                  # board: order, status, gates, runnable/blocked
python3 run.py next                  # the next runnable stage + its exact command + governor call

# run the printed command (your REAL script, governor-gated) — e.g.:
#   with acquire_slot('keyframe_S01', est_gb=20.0): python3 <your_keyframe_script> ...
# then record what it produced + (after Gate-A/B QC) stamp the gate:
python3 checkpoint.py record keyframe --produced 'frames/scene1/S*.png' --settings steps=34 cfg=6.5
python3 checkpoint.py verify keyframe S01_scene1.png            # the ones that passed Gate A
python3 checkpoint.py gate   keyframe --verdict PASS --by reviewer --notes "Gate A clean"
# -> now `animate` becomes runnable (run.py plan shows it unblocked)
```
The planner **gate-blocks** a stage until its upstream gate is stamped `PASS` — this is the human-in-the-loop
review discipline. Heavy stages acquire a memory-governor slot — a RAM-budget reservation that admits
concurrent jobs while they fit and blocks one only when the budget would be exceeded. Nothing here auto-runs
heavy gen; it prints the command for a human/agent to run, so the gate + governor discipline stays intact.

## The borrowed pattern — and what is original
*(Full comparison: `../docs/VS_OPENMONTAGE.md`.)*

| Borrowed orchestration idea | Implemented here | Original addition |
|---|---|---|
| YAML pipeline manifest (stage table) | ✅ `pipeline.yaml` | — |
| Auto-discovering tool registry (capability/runtime/cost/fallback) | ✅ `tool_registry.yaml` + `tools.py` | — |
| JSON checkpoint per stage (resume mid-pipeline) | ✅ `checkpoint.py` | — |
| Per-stage Markdown "director" skill | ✅ `director_skills/` | — |
| Human approval / review gate at creative stages | ✅ `gates` + `run.py` gate-blocking | — |
| Cost-tracker / $-budget provider selector | — | RAM-gate via a memory governor, not $-gate; single local stack |
| Prompt-only / SVG-rig "identity" | — | **LoRA + IP-Adapter face-lock** (`../recipe/IDENTITY_LOCK.md`) |

**The differentiator (kept explicit in `pipeline.yaml > advantages`):** photoreal single-character
continuity across a narrative film via per-character LoRA + IP-Adapter face-lock + plate→region-inpaint
for multi-char, with an empirical defect→fix QC. See `../recipe/` for the method + reference code.

## Note on paths
`pipeline.yaml` / `tool_registry.yaml` use **repo-relative** paths plus `<PATH_TO>` placeholders
for the machine-specific bits (model dirs, governor path). Copy `config.example.yaml` and fill in
your own absolute paths there so nothing machine-specific lives in the manifest.
