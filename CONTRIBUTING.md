# Contributing

Thanks for your interest. This project is the **method + the scaffold** for an
identity-locked, agent-drivable generative-film pipeline. Contributions that improve
the recipe, the orchestration, or the docs are welcome.

## Ground rules
- **No real-person likenesses without consent.** Train and demo on **public-domain,
  synthetic, or consented** subjects only. Do not submit datasets, LoRAs, or face crops of
  real people without their consent.
- **No model weights in the repo.** We do not re-host upstream weights. Link to the upstream
  source and note its license (see `THIRD_PARTY_LICENSES.md`). Some upstreams are
  **non-commercial** — keep that distinction accurate.
- **Keep examples generic.** Examples must not embed a specific proprietary film's story,
  characters, prompts, or assets. Use the public-domain demo character.
- **Keep machine paths out of the manifest.** Put any absolute paths (model dirs, governor)
  in `config.example.yaml`, never in `pipeline.yaml` / `tool_registry.yaml`.

## What makes a good contribution
- A clearer or more robust identity-lock step (LoRA loading, IP-Adapter scales, multi-char
  inpaint), with a before/after on the demo character.
- A better defect→fix routing rule in `recipe/CONSISTENCY_QC.md`, grounded in a reproducible
  failure case.
- Scaffold improvements (`tools.py` / `checkpoint.py` / `run.py`) that keep the
  validate/plan/gate loop intact. Run `python3 pipeline/tools.py validate` before submitting.
- Docs and worked examples.

## Style
- Python 3.10+, standard library where possible; keep `checkpoint.py` dependency-free.
- Reference scripts should run out-of-the-box pointing at the demo character, with
  placeholders clearly marked (`<PATH_TO>`, `<your-locale>`, etc.).

## License of contributions
By contributing you agree your contributions are licensed under this project's
**Apache-2.0** license (`LICENSE`).
