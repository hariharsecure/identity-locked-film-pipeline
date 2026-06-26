# Third-party licenses

**This project's own code and documentation are licensed Apache-2.0 (see `LICENSE`).**

The pipeline *drives* several upstream models. **We do NOT re-host any model weights** —
you download them from their own sources, and **each carries its own license, which you
must comply with.** Some are **non-commercial.** Our Apache-2.0 covers our code/docs
only; it does **not** relicense any of the models below.

| Component | What it is | License | Commercial use? | Source |
|---|---|---|---|---|
| **SDXL-base-1.0** | Stable Diffusion XL base (keyframe generation) | CreativeML **Open RAIL++-M** | Yes, with use-based restrictions (see the license's prohibited-uses appendix) | `stabilityai/stable-diffusion-xl-base-1.0` (Hugging Face) |
| **Wan2.2-TI2V-5B** | Image-to-video (animation) | **Apache-2.0** | Yes | Wan-AI / `Wan2.2-TI2V-5B` (Hugging Face) — and the MLX port |
| **MusicGen-small** | Local music model (temp score) | **CC-BY-NC-4.0** | **NO — non-commercial only** | `facebook/musicgen-small` (Hugging Face) |
| **IP-Adapter** | Image-prompt adapter (face-lock) | **Apache-2.0** | Yes | `h94/IP-Adapter` weights + `tencent-ailab/IP-Adapter` code (both Apache-2.0, verified) |
| **CLIP ViT-H / OpenCLIP** | IP-Adapter image encoder | **MIT** (OpenCLIP) | Yes | `laion/CLIP-ViT-H-14-laion2B-s32B-b79K` (Hugging Face) |
| **edge-tts** | Network TTS (temp VO pass) | GPL-3.0 (the client library) — it calls Microsoft Edge's online TTS service, which has its **own terms of use** | Verify Microsoft's service terms for your use; the recipe is TTS-agnostic — swap freely | `rany2/edge-tts` |
| **diffusers / transformers / peft** | Hugging Face libraries (inference + LoRA training) | **Apache-2.0** | Yes | Hugging Face |
| **ffmpeg** | Assemble / mux (CLI invoked, not linked) | LGPL-2.1+ / GPL build-dependent | Yes (we shell out to the `ffmpeg` binary; we do not link it) | ffmpeg.org |

## Hard rules
1. **No re-hosting.** Download each model from its own source under its own license.
2. **MusicGen-small is NON-COMMERCIAL (CC-BY-NC-4.0).** Use it only for a local TEMP
   score. A **commercial release MUST swap** to a commercially-licensed model/library
   (e.g. Stable Audio Open) or original music. Do **not** describe a MusicGen score as
   "commercial-clean."
3. **SDXL's Open RAIL++-M has use-based restrictions** (the prohibited-uses list). Commercial
   use is permitted, but the content restrictions still apply.
4. **edge-tts** is a thin client for an online Microsoft service; confirm the service's
   terms for your use case, or substitute any TTS that emits per-line audio.
5. **Verify at publish/ship time.** Upstream licenses can change. Re-check each component's
   current license before a release. (License facts above verified at the time of writing;
   IP-Adapter confirmed Apache-2.0 for both the code repo and the `h94/IP-Adapter` weights.)

## On the orchestration pattern
The agentic-orchestration **pattern** (a YAML pipeline manifest + an auto-discovering
tool-registry + per-stage JSON checkpoints + a human review-gate + per-stage director
skills) is a well-known design that prior agentic-video projects also use. This repo is an
**independent, clean-room re-implementation** of that pattern — **no third-party
orchestration source code is copied or vendored here.** See `docs/VS_OPENMONTAGE.md`.
