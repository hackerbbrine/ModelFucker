"""
corrupt.py — The thing that breaks your model in scientifically interesting ways.
Handle with the same care you'd give a loaded weapon pointed at your weights.
"""

import os
import sys
import time
import random
import shutil
import multiprocessing
from dataclasses import dataclass, field
from pathlib import Path

try:
    import numpy as np
    HAS_NUMPY = True
except ImportError:
    HAS_NUMPY = False

try:
    import cupy as cp
    HAS_CUPY = True
except ImportError:
    HAS_CUPY = False

from ui import console, fmt_bytes, ok, warn, err, mf, corruption_info_table, corruption_stats_table


@dataclass
class CorruptionResult:
    path: str
    intensity: int
    skip: int
    seed: int
    total_flips: int
    usable_bytes: int
    elapsed: float
    mb_per_sec: float
    dry_run: bool = False

    @property
    def impact_label(self) -> str:
        if self.intensity >= 1024:
            return "LIGHT"
        elif self.intensity >= 256:
            return "MODERATE"
        elif self.intensity >= 64:
            return "HEAVY"
        return "CATASTROPHIC"

    @property
    def flips_per_mb(self) -> float:
        return self.total_flips / max(self.usable_bytes / 1024 / 1024, 0.001)


# ── Worker must be at module level so multiprocessing can pickle it ──────────
def _worker_flip(args):
    path, chunk_start, chunk_end, intensity, seed, skip = args
    rng = random.Random(seed)

    with open(path, "rb") as f:
        f.seek(chunk_start)
        data = bytearray(f.read(chunk_end - chunk_start))

    global_start = chunk_start - skip
    first_local = (intensity - (global_start % intensity)) % intensity
    pos = first_local
    flips = 0

    while pos < len(data):
        bit = rng.randint(0, 7)
        data[pos] ^= (1 << bit)
        flips += 1
        pos += intensity

    return (chunk_start, bytes(data), flips)


def _numpy_flip(data: "np.ndarray", intensity: int, seed: int) -> int:
    rng = np.random.default_rng(seed)
    positions = np.arange(0, len(data), intensity)
    bits = rng.integers(0, 8, size=len(positions), dtype=np.uint8)
    masks = (np.uint8(1) << bits).astype(np.uint8)
    data[positions] ^= masks
    return len(positions)


def _cupy_flip(data: "np.ndarray", intensity: int, seed: int):
    cp.random.seed(seed)
    positions = cp.arange(0, len(data), intensity)
    bits = cp.random.randint(0, 8, size=len(positions), dtype=cp.uint8)
    masks = (cp.uint8(1) << bits).astype(cp.uint8)
    gpu_data = cp.array(data)
    gpu_data[positions] ^= masks
    result = cp.asnumpy(gpu_data)
    return result, len(positions)


def backend_label() -> str:
    if HAS_CUPY:
        return "GPU (CuPy)"
    if HAS_NUMPY:
        return "CPU (NumPy)"
    return "CPU (pure)"


def make_backup(path: str) -> None:
    backup = path + ".clean"
    if os.path.exists(backup):
        warn(f"Backup already exists at [dim]{backup}[/dim] — skipping")
        return
    mf("Creating backup — don't skip this step, future you will be grateful...")
    t0 = time.time()
    shutil.copy2(path, backup)
    ok(f"Backup saved ({fmt_bytes(os.path.getsize(backup))}) in {time.time() - t0:.1f}s")


def restore_backup(path: str) -> None:
    backup = path + ".clean"
    if not os.path.exists(backup):
        err(f"No backup at [dim]{backup}[/dim] — you're on your own")
        sys.exit(1)
    mf("Restoring from backup...")
    shutil.copy2(backup, path)
    ok("Model restored to clean state — like it never happened")


def corrupt_model(
    path: str,
    intensity: int,
    skip: int,
    seed: int,
    dry_run: bool,
    show_stats: bool,
    workers: int,
) -> CorruptionResult:
    size = os.path.getsize(path)
    usable = size - skip

    if usable <= 0:
        err(f"Skip ({fmt_bytes(skip)}) >= file size ({fmt_bytes(size)}) — nothing to corrupt")
        sys.exit(1)

    if intensity < 1:
        err(f"Intensity must be >= 1 (got {intensity}) — what are you even trying to do")
        sys.exit(1)

    est_flips = usable // intensity
    corruption_info_table(path, size, skip, intensity, seed, est_flips, dry_run)

    t0 = time.time()
    total_flips = 0

    if dry_run:
        total_flips = est_flips
        mf("[yellow]Simulating (no writes)...[/yellow]")
        time.sleep(0.2)

    elif HAS_CUPY:
        mf("[green]GPU acceleration engaged (CuPy) — overkill but we respect it[/green]")
        mf("Reading file into GPU memory...")
        with open(path, "rb") as f:
            f.seek(skip)
            raw = np.frombuffer(f.read(usable), dtype=np.uint8).copy()

        mf("Flipping bits on GPU...")
        modified, total_flips = _cupy_flip(raw, intensity, seed)

        mf("Writing corrupted weights to disk...")
        with open(path, "r+b") as f:
            f.seek(skip)
            f.write(modified.tobytes())

    elif HAS_NUMPY:
        mf("[cyan]NumPy vectorized backend — fast enough[/cyan]")
        mf("Reading file into memory...")
        with open(path, "rb") as f:
            f.seek(skip)
            raw = np.frombuffer(f.read(usable), dtype=np.uint8).copy()

        mf("Flipping bits...")
        total_flips = _numpy_flip(raw, intensity, seed)

        mf("Writing corrupted weights to disk...")
        with open(path, "r+b") as f:
            f.seek(skip)
            f.write(raw.tobytes())

    else:
        # Multiprocessing fallback — still gets the job done
        mf(f"[yellow]Multiprocessing fallback ({workers} workers) — numpy would be faster[/yellow]")
        chunk_size = usable // workers
        chunks = [
            (
                path,
                skip + i * chunk_size,
                skip + (i + 1) * chunk_size if i < workers - 1 else size,
                intensity,
                seed + i,
                skip,
            )
            for i in range(workers)
        ]

        results = []
        mf("Chewing through chunks...")
        with multiprocessing.Pool(workers) as pool:
            for result in pool.imap_unordered(_worker_flip, chunks):
                results.append(result)

        mf("Writing chunks back to disk...")
        with open(path, "r+b") as f:
            for chunk_start, data, flips in sorted(results, key=lambda x: x[0]):
                    f.seek(chunk_start)
                    f.write(data)
                    total_flips += flips

    elapsed = time.time() - t0
    mb_per_sec = (size / 1024 / 1024) / elapsed if elapsed > 0 else 0

    result = CorruptionResult(
        path=path,
        intensity=intensity,
        skip=skip,
        seed=seed,
        total_flips=total_flips,
        usable_bytes=usable,
        elapsed=elapsed,
        mb_per_sec=mb_per_sec,
        dry_run=dry_run,
    )

    console.print()
    ok(f"Done in {elapsed:.2f}s ({mb_per_sec:.0f} MB/s)")
    ok(f"{total_flips:,} bits flipped")
    ok(f"~{fmt_bytes(total_flips * intensity)} of weights are now vibes")

    if show_stats:
        corruption_stats_table(total_flips, intensity, usable, elapsed, mb_per_sec)

    return result
