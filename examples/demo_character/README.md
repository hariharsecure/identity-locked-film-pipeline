# Demo character (public-domain) — end-to-end example

This folder is where the worked example lives. It uses a **public-domain** figure
(**Robin Hood**) as a throwaway demo character — **not** any real or proprietary likeness.
Its only job is to show the wiring; it asserts no quality you can't reproduce.

## What goes here (you create these)
```
examples/demo_character/
├── dataset/                       # 15-30 images of YOUR demo character (public-domain/synthetic/consented)
├── demo_character_lora_unet_peft/ # the trained PEFT LoRA (gitignored — do NOT commit weights)
├── demo_character_canonical_face.png  # one tight face crop for IP-Adapter (gitignored)
├── frames/                        # keyframes the recipe produces (gitignored)
├── anim/                          # animated clips (gitignored)
├── vo_clips/  score/  output/     # audio + final cut (gitignored)
└── hold.json                      # optional: {"hold": ["S02"]} -> static fallback for a shot
```
All generated media + weights are **gitignored** — this example ships only as instructions,
never as bundled assets.

## Walkthrough
```bash
# 1) Put public-domain / synthetic / consented images of your demo character in ./dataset/
# 2) Train a character LoRA (see recipe/train_char_lora.py; --dry-run prints the command)
python3 ../../recipe/train_char_lora.py \
    --instance-dir ./dataset --trigger demochar \
    --output ./demo_character_lora_unet_peft

# 3) Save ONE tight face crop as demo_character_canonical_face.png (for IP-Adapter)

# 4) Keyframe (edit the SHOTS table + wardrobe constants in the script first)
python3 ../../recipe/keyframe_identity_lock.py --shot S01 --seed 1234

# 5) Gate the keyframe, then animate / assemble (per the director-skills)
cd ../../pipeline
python3 checkpoint.py record keyframe --produced 'examples/demo_character/frames/S*.png'
python3 checkpoint.py verify keyframe S01.png
python3 checkpoint.py gate   keyframe --verdict PASS --by you --notes "Gate A clean"
python3 run.py next
```

## Why a public-domain demo
The recipe holds **one** character across shots. To demonstrate that without shipping a real
person's likeness or a proprietary character, pick a clearly public-domain figure (Robin
Hood, Sherlock Holmes, etc.) or a synthetic face you generated. Swap in your own when you
build a real film.
