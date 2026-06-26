# IDENTITY LOCK — holding one photoreal character across a film

*The method. SDXL + a per-character LoRA + IP-Adapter face-lock for the keyframe;
plate → per-region inpaint for multi-character frames; seed-locked low-motion I2V
for the animation. This is what a prompt-only or SVG-rig agentic-video pipeline
lacks: cross-shot photoreal identity.*

Reference code: `keyframe_identity_lock.py`, `train_char_lora.py`, `wan_i2v.py`.

---

## 0. The core idea (one paragraph)
A text-to-image model has no memory of "your" character between prompts. To hold a
character across dozens of shots you give the model two anchors: (1) a **per-character
LoRA** that teaches SDXL the character's identity from a small dataset, and (2) an
**IP-Adapter** conditioned on a **canonical face crop** that pins the face at inference.
The keyframe is where identity is decided; the image-to-video pass only adds motion
and must be **seed-locked and anchored** so it does not drift the face.

---

## 1. Train the character LoRA (the identity)
- **Dataset:** 15–30 images of the SAME character — varied pose / expression / lighting,
  plainish backgrounds, consistent wardrobe (or caption the wardrobe out if it should
  vary). Use a **public-domain, synthetic, or consented** subject — never a real person's
  likeness without consent.
- **Trigger:** a unique rare token (e.g. `demochar`) used in every caption.
- **Hyper-params (SDXL):** resolution 1024, LoRA rank 8–32 (16 is a good default),
  lr 1e-4, ~800–1500 steps. Over-training makes identity rigid (every shot the same
  pose) — stop when the face is reliable but still poseable.
- **Trainer:** use a maintained SDXL LoRA trainer (the `diffusers`
  `train_dreambooth_lora_sdxl.py` example, Apache-2.0) — don't re-implement the loop.
  `train_char_lora.py` is a launcher around it with the recommended params.
- Save **one tight face crop** separately as `<char>_canonical_face.png` for IP-Adapter.

## 2. Load it correctly at inference (the gotcha)
- Load the LoRA as a PEFT model: `pipe.unet = PeftModel.from_pretrained(pipe.unet, lora_dir)`.
- **Set the LoRA weight via a `set_scale()` loop over the UNet modules.** Passing
  `cross_attention_kwargs={"scale": w}` is a **NO-OP on a PEFT-wrapped UNet** — a common
  mistake that makes the LoRA look like it "isn't working." The reference's
  `set_lora_weight()` shows the loop.
- Typical weight **1.0**; bump to **1.15** to fight drift in a close-up.

## 3. IP-Adapter face-lock (the face pin)
- Load IP-Adapter (ViT-H image encoder) and pass the **canonical face crop** as the
  IP-Adapter image at generate time.
- **Scale is per-shot:** ~**0.30** for a medium / close-up, ~**0.45** inside a masked
  two-shot box. Too high and the face stamps in unnaturally; too low and it drifts.
- You can apply face-IP to the **hardest-to-hold** character only and run the rest
  **LoRA-only** (face-IP scale 0.0) to save complexity.

## 4. Style without erasing the character
- A no-people **style anchor** image via a second IP-Adapter input is great for a
  consistent look — but keep its scale **≤ 0.15**. A high style-anchor scale will
  **erase characters into empty rooms** (observed: 0.45 emptied many character shots).

## 5. Multi-character frames: plate → per-region inpaint
A single PEFT-wrapped UNet holds **one** identity at a time; two character LoRAs in one
pass fight and one dominates. So:
1. **Plate:** generate a **no-LoRA** composition with the right layout / count / poses.
   Re-roll the seed and **look at each plate**; pick the cleanest multi-figure layout.
   (Re-keying at the SAME seed keeps a duplicate — change the seed to break it.)
2. **Per-region inpaint:** for each character, mask that character's region and inpaint
   it with **that character's LoRA** (and its face crop), **serially**. Each region gets
   the correct identity without the adapters fighting.

## 6. Wardrobe / colour discipline (verify the pixels)
- Lock a short **per-character wardrobe + colour** convention.
- Carry a **targeted negative** so a strong background colour cannot bleed into a garment
  (e.g. green hills bleeding green into a garment → add `green garment, green clothing` to
  the negative for that character). This is the most common "everything looks the same
  colour" failure.
- Always check the **rendered pixels** against the canon — never trust the prompt string.

## 7. Animate without losing the face (the I2V pass)
- **Keyframe-anchored** image-to-video; **fixed seed = the keyframe seed**.
- **4n+1** frame counts at 24fps (73=3s … 169=7s); `--steps` 24 for low-motion
  cinemagraphs, 30 for fix-shots / payoffs; `--guide-scale 5.0 --shift 5.0
  --scheduler unipc`.
- **Motion lives in the prompt** ("mostly still, single slow blink, secondary motion
  only"). The world can drift; the **face stays held**.
- **NO IP-Adapter in the I2V pass** — anchor coherence is a keyframe property; adding
  face-IP to motion fights the temporal model.
- Deliberate **two-figure** shots: drop the `duplicate person / extra person / identity
  change` negatives (they collapse the second figure), add "both remain present, neither
  fades nor merges," and use **fewer frames**.

## 8. The order that matters
Identity is **decided at the keyframe**. A motion pass **cannot rescue a bad still**.
Gate the keyframe (identity / wardrobe / count / composition) **before** you ever animate.
See `CONSISTENCY_QC.md` for the defect→fix routing and the gates.
