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
from enum import Enum
from pathlib import Path
from typing import Optional

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


class CorruptPattern(Enum):
    RANDOM  = "random"    # random bit flip — unpredictable chaos
    PATTERN = "pattern"   # same bit (bit 3) every time — structured decay
    ZEROS   = "zeros"     # zero out bytes — erase instead of flip
    MIXTURE = "mixture"   # 50% random flips, 50% zeroed bytes


class AttentionMode(Enum):
    IGNORE  = "ignore"    # don't care about attention tensors
    PROTECT = "protect"   # skip attention tensors — corrupt everything else
    TARGET  = "target"    # ONLY corrupt attention tensors


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
    pattern: CorruptPattern = CorruptPattern.RANDOM
    attention_mode: AttentionMode = AttentionMode.IGNORE

    @property
    def impact_label(self) -> str:
        if self.intensity >= 1024: return "LIGHT"
        if self.intensity >= 256:  return "MODERATE"
        if self.intensity >= 64:   return "HEAVY"
        return "CATASTROPHIC"

    @property
    def flips_per_mb(self) -> float:
        return self.total_flips / max(self.usable_bytes / 1024 / 1024, 0.001)


# ── Helpers ────────────────────────────────────────────────────────────────────

def _filter_positions(positions: "np.ndarray", ranges: list, data_start: int) -> "np.ndarray":
    """Remove positions that fall inside any of the given absolute byte ranges."""
    if not ranges:
        return positions
    mask = np.ones(len(positions), dtype=bool)
    for abs_start, abs_end in ranges:
        rel_start = max(0, abs_start - data_start)
        rel_end   = max(0, abs_end   - data_start)
        mask &= ~((positions >= rel_start) & (positions < rel_end))
    return positions[mask]


def _only_positions(positions: "np.ndarray", ranges: list, data_start: int) -> "np.ndarray":
    """Keep ONLY positions that fall inside one of the given absolute byte ranges."""
    if not ranges:
        return np.array([], dtype=positions.dtype)
    mask = np.zeros(len(positions), dtype=bool)
    for abs_start, abs_end in ranges:
        rel_start = max(0, abs_start - data_start)
        rel_end   = max(0, abs_end   - data_start)
        mask |= (positions >= rel_start) & (positions < rel_end)
    return positions[mask]


def _apply_pattern(
    data: "np.ndarray",
    positions: "np.ndarray",
    pattern: CorruptPattern,
    rng,
) -> int:
    if len(positions) == 0:
        return 0
    if pattern == CorruptPattern.ZEROS:
        data[positions] = np.uint8(0)
    elif pattern == CorruptPattern.PATTERN:
        data[positions] ^= np.uint8(0x08)   # always bit 3
    elif pattern == CorruptPattern.MIXTURE:
        idx = rng.permutation(len(positions))
        half = len(positions) // 2
        rand_pos = positions[idx[:half]]
        zero_pos = positions[idx[half:]]
        bits = rng.integers(0, 8, size=len(rand_pos), dtype=np.uint8)
        data[rand_pos] ^= (np.uint8(1) << bits).astype(np.uint8)
        data[zero_pos] = np.uint8(0)
    else:  # RANDOM
        bits = rng.integers(0, 8, size=len(positions), dtype=np.uint8)
        data[positions] ^= (np.uint8(1) << bits).astype(np.uint8)
    return len(positions)


# ── Multiprocessing worker (module-level for pickling) ────────────────────────

def _worker_flip(args):
    path, chunk_start, chunk_end, intensity, seed, skip, pattern_val = args
    rng = random.Random(seed)
    pattern = CorruptPattern(pattern_val)

    with open(path, "rb") as f:
        f.seek(chunk_start)
        data = bytearray(f.read(chunk_end - chunk_start))

    global_start = chunk_start - skip
    first_local  = (intensity - (global_start % intensity)) % intensity
    pos = first_local
    flips = 0

    while pos < len(data):
        if pattern == CorruptPattern.ZEROS:
            data[pos] = 0
        elif pattern == CorruptPattern.PATTERN:
            data[pos] ^= 0x08
        elif pattern == CorruptPattern.MIXTURE:
            if rng.random() < 0.5:
                data[pos] ^= (1 << rng.randint(0, 7))
            else:
                data[pos] = 0
        else:
            data[pos] ^= (1 << rng.randint(0, 7))
        flips += 1
        pos += intensity

    return (chunk_start, bytes(data), flips)


# ── Core flip functions ────────────────────────────────────────────────────────

def _numpy_flip(
    data: "np.ndarray",
    intensity: int,
    seed: int,
    pattern: CorruptPattern,
    attention_ranges: list,
    attention_mode: AttentionMode,
    data_start: int,
) -> tuple:
    """Returns (total_ops, targeted_ops)."""
    rng = np.random.default_rng(seed)
    all_positions = np.arange(0, len(data), intensity)
    total = len(all_positions)

    if attention_ranges and attention_mode != AttentionMode.IGNORE:
        if attention_mode == AttentionMode.PROTECT:
            positions = _filter_positions(all_positions, attention_ranges, data_start)
        else:  # TARGET
            positions = _only_positions(all_positions, attention_ranges, data_start)
    else:
        positions = all_positions

    _apply_pattern(data, positions, pattern, rng)
    return total, len(positions)


def _cupy_flip(
    data: "np.ndarray",
    intensity: int,
    seed: int,
    pattern: CorruptPattern,
    attention_ranges: list,
    attention_mode: AttentionMode,
    data_start: int,
) -> tuple:
    """Returns (modified_array, total_ops, targeted_ops)."""
    cp.random.seed(seed)
    all_pos_np = np.arange(0, len(data), intensity)
    total = len(all_pos_np)

    # Apply attention filtering on CPU then transfer to GPU
    if attention_ranges and attention_mode != AttentionMode.IGNORE:
        if attention_mode == AttentionMode.PROTECT:
            pos_np = _filter_positions(all_pos_np, attention_ranges, data_start)
        else:
            pos_np = _only_positions(all_pos_np, attention_ranges, data_start)
    else:
        pos_np = all_pos_np

    positions = cp.array(pos_np)
    gpu = cp.array(data)

    if pattern == CorruptPattern.ZEROS:
        gpu[positions] = cp.uint8(0)
    elif pattern == CorruptPattern.PATTERN:
        gpu[positions] ^= cp.uint8(0x08)
    elif pattern == CorruptPattern.MIXTURE:
        bits = cp.random.randint(0, 8, size=len(positions), dtype=cp.uint8)
        half = len(positions) // 2
        gpu[positions[:half]] ^= (cp.uint8(1) << bits[:half]).astype(cp.uint8)
        gpu[positions[half:]] = cp.uint8(0)
    else:
        bits = cp.random.randint(0, 8, size=len(positions), dtype=cp.uint8)
        gpu[positions] ^= (cp.uint8(1) << bits).astype(cp.uint8)

    return cp.asnumpy(gpu), total, int(len(positions))


# ── Public API ─────────────────────────────────────────────────────────────────

def backend_label() -> str:
    if HAS_CUPY:  return "GPU (CuPy)"
    if HAS_NUMPY: return "CPU (NumPy)"
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
    pattern: CorruptPattern = CorruptPattern.RANDOM,
    attention_mode: AttentionMode = AttentionMode.IGNORE,
    attention_ranges: Optional[list] = None,
) -> CorruptionResult:
    size   = os.path.getsize(path)
    usable = size - skip

    if usable <= 0:
        err(f"Skip ({fmt_bytes(skip)}) >= file size ({fmt_bytes(size)}) — nothing to corrupt")
        sys.exit(1)
    if intensity < 1:
        err(f"Intensity must be >= 1 (got {intensity})")
        sys.exit(1)

    ranges = attention_ranges or []
    est_flips = usable // intensity
    corruption_info_table(path, size, skip, intensity, seed, est_flips, dry_run)

    # Show extra context for pattern / attention mode
    if pattern != CorruptPattern.RANDOM:
        mf(f"Pattern: [bold magenta]{pattern.value}[/bold magenta]")
    if attention_mode != AttentionMode.IGNORE:
        if ranges:
            attn_mb = sum(e - s for s, e in ranges) / 1024 / 1024
            mf(
                f"Attention: [bold yellow]{attention_mode.value}[/bold yellow]"
                f"  [dim]{len(ranges)} tensors · {attn_mb:.0f} MB[/dim]"
            )
        else:
            warn("Attention mode set but no ranges found — corrupting uniformly")

    t0 = time.time()
    total_flips = 0
    targeted_ops = 0

    if dry_run:
        total_flips = est_flips
        mf("[yellow]Simulating (no writes)...[/yellow]")
        time.sleep(0.2)

    elif HAS_CUPY:
        mf("[green]GPU acceleration (CuPy)[/green]")
        mf("Reading into GPU memory...")
        with open(path, "rb") as f:
            f.seek(skip)
            raw = np.frombuffer(f.read(usable), dtype=np.uint8).copy()
        mf("Applying pattern on GPU...")
        modified, total_flips, targeted_ops = _cupy_flip(raw, intensity, seed, pattern, ranges, attention_mode, skip)
        mf("Writing to disk...")
        with open(path, "r+b") as f:
            f.seek(skip)
            f.write(modified.tobytes())

    elif HAS_NUMPY:
        mf("[cyan]NumPy vectorized backend[/cyan]")
        mf("Reading into memory...")
        with open(path, "rb") as f:
            f.seek(skip)
            raw = np.frombuffer(f.read(usable), dtype=np.uint8).copy()
        mf("Applying pattern...")
        total_flips, targeted_ops = _numpy_flip(raw, intensity, seed, pattern, ranges, attention_mode, skip)
        mf("Writing to disk...")
        with open(path, "r+b") as f:
            f.seek(skip)
            f.write(raw.tobytes())

    else:
        mf(f"[yellow]Multiprocessing fallback ({workers} workers)[/yellow]")
        chunk_size = usable // workers
        chunks = [
            (
                path,
                skip + i * chunk_size,
                skip + (i + 1) * chunk_size if i < workers - 1 else size,
                intensity,
                seed + i,
                skip,
                pattern.value,
            )
            for i in range(workers)
        ]
        results = []
        mf("Chewing through chunks...")
        with multiprocessing.Pool(workers) as pool:
            for result in pool.imap_unordered(_worker_flip, chunks):
                results.append(result)
        mf("Writing chunks to disk...")
        with open(path, "r+b") as f:
            for chunk_start, data, flips in sorted(results, key=lambda x: x[0]):
                f.seek(chunk_start)
                f.write(data)
                total_flips += flips

    elapsed    = time.time() - t0
    mb_per_sec = (size / 1024 / 1024) / elapsed if elapsed > 0 else 0

    result = CorruptionResult(
        path=path, intensity=intensity, skip=skip, seed=seed,
        total_flips=total_flips, usable_bytes=usable,
        elapsed=elapsed, mb_per_sec=mb_per_sec, dry_run=dry_run,
        pattern=pattern, attention_mode=attention_mode,
    )

    console.print()
    ok(f"Done in {elapsed:.2f}s ({mb_per_sec:.0f} MB/s)")
    ok(f"{total_flips:,} operations applied  [{pattern.value}]")

    # Verification — show what was actually targeted so the user knows it worked
    if attention_mode != AttentionMode.IGNORE and not dry_run:
        if targeted_ops == 0:
            err(
                f"Attention mode [{attention_mode.value}] produced 0 targeted operations — "
                "the ranges may not overlap the corrupted region. Try reducing --skip."
            )
        else:
            pct = targeted_ops / max(total_flips, 1) * 100
            ok(
                f"Attention targeting confirmed: [bold]{targeted_ops:,}[/bold] ops "
                f"in [bold]{len(ranges)}[/bold] tensors "
                f"([cyan]{pct:.1f}%[/cyan] of total)"
            )
    ok(f"~{fmt_bytes(total_flips * intensity)} of weights affected")

    if show_stats:
        corruption_stats_table(total_flips, intensity, usable, elapsed, mb_per_sec)

    return result
