# GOVERNOR — RAM-budget admission control for heavy local generation

*Why and how to RAM-gate heavy local generation on a single workstation so it does
not run out of memory. The pattern: a tiny "memory governor" that reserves a RAM
budget before a heavy job runs and refuses to over-commit memory. The reference
governor (`memory_governor.py`) is a **RAM-budget reservation** gate — it lets
independent jobs run CONCURRENTLY as long as their combined estimate (plus headroom)
fits in available RAM, and only blocks a job when the budget would be exceeded. (An
earlier single-slot lock was replaced because it left tens of GB idle.)*

The reference scripts import `acquire_slot(name, est_gb, timeout_s)` and fall back to
a **no-op context manager** if no governor is present — so they run out-of-the-box,
but you should provide a real governor on a single-GPU/single-Mac box.

---

## Why
SDXL keyframing (~20 GB), Wan2.2 I2V (~22 GB), and a local music model (~6 GB) are each
heavy. Run too many at once on one workstation — beyond what RAM holds — and the OS will
OOM-kill one (or thrash). The fix is not "$ budget" (that's for cloud APIs) — it's **RAM
admission control**: admit a heavy job only when its estimated peak (plus headroom) still
fits in available RAM. That admits concurrent jobs while the budget fits and blocks one
only when it would not — not a blind one-at-a-time rule.

## The contract
```python
with acquire_slot("keyframe_S01", est_gb=20.0, timeout_s=7200):
    ... run the heavy job ...
```
The reference implementation (`memory_governor.py`) is a **RAM-budget reservation** gate:
- **Grants** as soon as `sum(live reservations) + est_gb + HEADROOM <= available RAM` —
  so **concurrent jobs are allowed whenever the budget fits**; it only **blocks** a job
  when that sum would exceed available RAM (then it waits and retries). Each grant writes
  a small reservation file and releases it on exit. (The reference `HEADROOM` is **14 GB**
  beyond the sum of estimates; `available RAM` is the true reclaimable figure from
  `vm_stat` — free + inactive + speculative + purgeable.)
- **est_gb** is the job's estimated peak — the reference uses measured values: keyframe
  20.0, animate 22.0, score 6.0, the emotional-TTS pass ~8.0; ffmpeg / network TTS = 0.0
  (no slot). The reference default is `est_gb=6.0`.
- **timeout_s** bounds the wait so a wedged job can't deadlock the queue forever
  (reference default **3600 s**); on timeout `acquire_slot` raises `TimeoutError`.
- A separate **watchdog** (`memory_governor.py --watchdog`) can run persistently and abort
  the current heavy job if available RAM drops below a CRITICAL floor, never touching a
  protected long-running process. This is the safety net under the budget gate.

## A minimal governor (sketch)
The reference `memory_governor.py` does budget-reservation (concurrent-if-it-fits, above).
The simplest possible *alternative*, if you only ever want **one heavy job at a time**, is a
file-lock + a free-RAM check — shown here as a dependency-light starting point you can grow
into the budget-reservation form:
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
This sketch enforces a **single slot** AND a **free-RAM floor**. It is the conservative
floor; the reference `memory_governor.py` instead does **RAM-budget reservation** (grant
while the combined estimate + headroom fits), so independent jobs can run concurrently and
RAM is not left idle. Extend the sketch toward that — N concurrent reservations, per-device
accounting, or a small daemon — when a strict single slot wastes capacity.

## Rules of thumb
- **Heavy = governor slot.** keyframe / animate / score acquire a slot; ffmpeg and a
  network TTS do not.
- **Budget, not blind-serial.** The reference admits concurrent heavy jobs *only while the
  combined RAM estimate + headroom fits*; it blocks (waits) the moment the budget would be
  exceeded. A strict single slot is the simpler, more conservative fallback.
- **Skip-if-exists** in every heavy script so an interrupted batch resumes cheaply.
- **Estimate high, not low.** An over-estimate wastes a little time; an under-estimate
  OOM-kills the run.
- The pipeline manifest declares which stages need a slot
  (`policy.governor_required_for`); the runner prints the exact `acquire_slot(...)` call
  for the next stage.
