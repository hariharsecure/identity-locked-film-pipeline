# Director Skill — STAGE 4b: AUDIO / SCORE (local music model, per-beat cues)

*How an agent or a human runs + verifies the score stage. Tool: `musicgen_score`. Gate: **AUDIO**.*

## What this stage decides
**The per-beat musical cues** (the non-silent score states from your sound-design plan). Parallel to the
visual stages. The mix (VO + score + beds, ducking, any deliberate silences) happens later, in **assemble**.

## The stack (reference — `../recipe/musicgen_score.py`)
- A **local music model** (e.g. `facebook/musicgen-small`), transformers-native, **MPS**. **License caveat:**
  MusicGen-small weights are **CC-BY-NC-4.0 (non-commercial)** — fine as a fully-local TEMP score, but a
  commercial release MUST swap to a commercially-licensed model/library or original music. See
  `../THIRD_PARTY_LICENSES.md`.
- Per cue: `(name, prompt, target_seconds)` → generate → ffmpeg `loudnorm I=-18:TP=-2:LRA=11`, `-ar 44100`.
- Writes `score/C##_*.wav` + `score/SCORE_MANIFEST.json` (cue / prompt / target_s / actual_s / path).
- **Palette:** define your own cue palette and reserve any distinctive timbre for a specific beat. Keep the
  emotional arc legible cue-to-cue (e.g. question → tension → wander → resolution).

## How to run (reference)
```
python3 ../recipe/musicgen_score.py
```
Governor: **ONE slot for the whole batch** (`acquire_slot('score_musicgen', est_gb=6.0)`).
Heavy stage → serial with all other heavy gen.

## GATE AUDIO — score QA (self-review)
- [ ] Each cue's **`actual_s` ≈ `target_s`** (the manifest records both — a big miss = a truncated cue).
- [ ] `loudnorm I=-18` applied; cues sit under dialogue (they get ducked at the mix).
- [ ] **On-palette** — listen, don't trust the prompt string.
- [ ] The emotional arc reads cue-to-cue.

## Record the checkpoint + stamp the gate
```
python3 ../checkpoint.py record audio_score --produced 'score/C*.wav' 'score/SCORE_MANIFEST.json'
python3 ../checkpoint.py gate   audio_score --verdict PASS --by agent --notes "actual_s≈target_s, on-palette, loudnorm ok"
```

## On a bad cue
Re-gen **that cue only** — use a single-cue re-gen pattern. Never re-gen the whole batch for one bad cue;
never re-mux a wrong stem.
