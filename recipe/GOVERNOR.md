# GOVERNOR — RAM-gating heavy local generation (one job at a time)

*Why and how to serialize heavy local generation on a single workstation so it does
not run out of memory. The pattern: a tiny "memory governor" that hands out a slot
before a heavy job runs and refuses to over-commit RAM.*

The reference scripts import `acquire_slot(name, est_gb, timeout_s)` and fall back to
a **no-op context manager** if no governor is present — so they run out-of-the-box,
but you should provide a real governor on a single-GPU/single-Mac box.

---

## Why
SDXL keyframing (~20 GB), Wan2.2 I2V (~22 GB), and a local music model (~6 GB) are each
heavy. Run two at once on one workstation and the OS will OOM-kill one (or thrash). The
fix is not "$ budget" (that's for cloud APIs) — it's **RAM admission control**: one heavy
job at a time, gated by estimated peak memory.

## The contract
```python
with acquire_slot("keyframe_S01", est_gb=20.0, timeout_s=7200):
    ... run the heavy job ...
```
- **Blocks** until enough RAM is free (and no other slot is held, if you enforce a single
  global slot).
- **est_gb** is the job's estimated peak — the reference uses measured values: keyframe
  20.0, animate 22.0, score 6.0, the emotional-TTS pass ~8.0; ffmpeg / network TTS = 0.0
  (no slot).
- **timeout_s** bounds the wait so a wedged job can't deadlock the queue forever.

## A minimal governor (sketch)
A simple, dependency-light governor can be a file-lock + a free-RAM check:
```python
# memory_governor.py (sketch — adapt to your OS / needs)
import contextlib, time, fcntl, os, psutil
LOCK = os.path.expanduser("~/.cache/yourtool/gen.lock")

@contextlib.contextmanager
def acquire_slot(name, est_gb=0.0, timeout_s=7200):
    os.makedirs(os.path.dirname(LOCK), exist_ok=True)
    f = open(LOCK, "w")
    deadline = time.time() + timeout_s
    while True:
        try:
            fcntl.flock(f, fcntl.LOCK_EX | fcntl.LOCK_NB)        # single global slot
            free_gb = psutil.virtual_memory().available / 1e9
            if est_gb <= 0 or free_gb >= est_gb:
                break
            fcntl.flock(f, fcntl.LOCK_UN)                         # not enough RAM yet; back off
        except BlockingIOError:
            pass
        if time.time() > deadline:
            raise TimeoutError(f"acquire_slot('{name}') timed out")
        time.sleep(5)
    try:
        yield
    finally:
        fcntl.flock(f, fcntl.LOCK_UN)
        f.close()
```
This enforces **one heavy job at a time** AND a **free-RAM floor**. You can extend it to
N concurrent slots, per-device accounting, or a small daemon — but the single-slot file
lock already prevents the common OOM.

## Rules of thumb
- **Heavy = governor slot.** keyframe / animate / score acquire a slot; ffmpeg and a
  network TTS do not.
- **Serial, always.** Never hold two slots at once on one workstation.
- **Skip-if-exists** in every heavy script so an interrupted batch resumes cheaply.
- **Estimate high, not low.** An over-estimate wastes a little time; an under-estimate
  OOM-kills the run.
- The pipeline manifest declares which stages need a slot
  (`policy.governor_required_for`); the runner prints the exact `acquire_slot(...)` call
  for the next stage.
