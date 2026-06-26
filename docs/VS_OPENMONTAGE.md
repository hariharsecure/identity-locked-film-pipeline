# The borrowed pattern vs. the identity-lock addition

This project borrows a **well-known agentic-orchestration pattern** and pairs it with an
**identity-lock recipe** that prompt-only / cartoon-rig pipelines lack. This page is an
honest accounting of what is borrowed and what is original.

## The pattern (borrowed, re-implemented clean-room)
Several agentic-video orchestration projects converge on the same useful design:

- a **YAML pipeline manifest** (a declarative stage table),
- an **auto-discovering tool registry** (each stage's tool, with runtime / cost / fallback),
- **per-stage JSON checkpoints** (so a pipeline resumes mid-run),
- **human review-gates** at the creative stages, and
- **per-stage "director" skills** (markdown how-to-run-and-verify).

We re-implemented this pattern **cleanly, from the design idea — no third-party
orchestration source code is copied or vendored.** Because the implementation here is our
own, it is licensed **Apache-2.0** (permissive). If you have seen a copyleft (e.g. AGPL-3.0)
agentic-video repo, note that we did **not** copy its code, so this repo's Apache-2.0 license
applies to our work without conflict. (Always comply with the licenses of the upstream
**models** — those are separate; see `../THIRD_PARTY_LICENSES.md`.)

## The addition (original): identity-lock + empirical QC
The differentiator is the part most agentic-video tools do **not** have:

| Capability | Prompt-only / cartoon-rig pipelines | This project |
|---|---|---|
| Cross-shot photoreal **identity** | prompt-only or SVG/cartoon rig — drifts shot-to-shot | **per-character LoRA + IP-Adapter face-lock** (`../recipe/IDENTITY_LOCK.md`) |
| **Multi-character** identity in one frame | usually unaddressed | **plate → per-region LoRA inpaint** |
| **Consistency QC** | a generic "reviewer" prompt | an **empirical defect→fix decision tree** (`../recipe/CONSISTENCY_QC.md`) |
| Resource control | $-budget / provider selection (cloud) | **RAM-gating a local stack** (one heavy job at a time, `../recipe/GOVERNOR.md`) |
| Stack | hosted generators (cloud APIs/keys) | **fully local** SDXL / Wan2.2 / local music / local-or-network TTS |

## What we deliberately did NOT take
- **Cloud-API generators** and a `$`-cost provider selector — we run a single local stack and
  gate on **RAM**, not dollars.
- **Prompt-only identity** — the whole point of this repo is the LoRA + IP-Adapter face-lock.
- **Any third-party orchestration source code** — re-implemented from the pattern, not pasted.

## Honest scope
This is **not** "the world's first" identity-consistent agentic film pipeline. Prior projects
exist and some claim character consistency. The narrow, demonstrated claim here is: **a local,
identity-locked, agent-drivable pipeline + a reproducible single-character continuity recipe**,
shown on a public-domain demo character. Bring your own model weights (under their licenses),
train your own character, and judge the result on your own footage.
