# Director Skill — STAGE 4a: AUDIO / VOICEOVER (TTS)

*How an agent or a human runs + verifies the VO stage. Tool: `tts_vo`. Gate: **AUDIO**.*
*A local emotional voice-design pass is the advantage over a plain TTS temp pass.*

## What this stage decides
**The voiced lines.** Per-line VO from your VO script. Parallel to the visual stages (authored from the
script, not the picture). Two passes: a light temp pass and an emotional final pass.

## The stack (reference — `../recipe/tts_vo.py`)
- **Temp pass:** a network TTS (e.g. `edge-tts`, light, no MPS / no governor). Per line: synthesize →
  ffmpeg `loudnorm I=-16:TP=-1.5:LRA=11`, `-ar 44100` → final mp3 → ffprobe duration (verify > 0 and
  proportional to text length).
- **Final pass:** a **local emotional TTS** (LOCAL_MPS — governor slot) → `vo_clips_emotional/`. This is
  the emotion-design layer (interior high-emotion lines get the expressive treatment).
- Writes `vo_clips/S##_<speaker>_<voice>.mp3` + `vo_clips/VO_MANIFEST.json`.

## Casting (an authoring decision — match the filename voice tag)
Define a casting table mapping each speaker to a voice, and tag it into the filename so the QA can confirm
the right voice per speaker. *(Example placeholders only:)*
| Speaker | Voice |
|---|---|
| narrator | `<your-locale>-<VoiceName>Neural` |
| character_a | `<your-locale>-<VoiceName>Neural` |
| character_b | `<your-locale>-<VoiceName>Neural` |

## How to run (reference)
```
python3 ../recipe/tts_vo.py            # temp network-TTS full pass + loudnorm + duration-verify
```
No governor slot for the temp pass (network). The local emotional final pass DOES take a slot — run it
serial like any heavy stage.

## Lip-sync sub-step (on-screen dialogue only)
- Off-screen V.O. (no mouth visible) → **no lip-sync** (audio-place only).
- On-screen dialogue → run the VO through a viseme tool → composite mouth sprites at the registered mouth
  ROI → mux. (CPU; interleaves with heavy jobs.)

## GATE AUDIO — VO QA (self-review)
- [ ] Each clip's **duration is proportional to its text** (a too-short clip = a dropped/garbled line).
- [ ] `loudnorm I=-16` applied; level consistent across speakers.
- [ ] Right **voice per speaker** (the filename tag matches the casting table).
- [ ] Emotional final pass reads on-character (not flat) for the high-emotion lines.

## Record the checkpoint + stamp the gate
```
python3 ../checkpoint.py record audio_vo --produced 'vo_clips/S*.mp3' 'vo_clips/VO_MANIFEST.json'
python3 ../checkpoint.py verify audio_vo VO_MANIFEST.json S01_narrator.mp3       # the clips that passed Gate AUDIO
python3 ../checkpoint.py gate   audio_vo --verdict PASS --by agent --notes "durations proportional, loudnorm ok, casting matches"
```
On a bad line: re-gen **that line only** — never re-mux a wrong stem.
