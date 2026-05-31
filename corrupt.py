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
from contextlib import contextmanager
from dataclasses import dataclass
from enum import Enum
from typing import Optional, Callable

import numpy as np

from rich.progress import (
    Progress, BarColumn, TextColumn,
    TimeRemainingColumn, TaskProgressColumn, SpinnerColumn,
)

from ui import console, fmt_bytes, ok, warn, err, mf, corruption_info_table, corruption_stats_table


# ── GPU backend detection ─────────────────────────────────────────────────────
# Checked once at import time. Priority: CuPy > PyTorch CUDA > PyTorch ROCm > CPU

class _GPU:
    backend: str = "cpu"
    label:   str = "CPU (NumPy)"
    lib            = None
    device_name: str = ""

def _detect_gpu() -> None:
    # Suppress stderr during detection — ROCm on Windows spawns offload-arch.exe
    # with unquoted paths (known bug when username has spaces) and the noise goes
    # to stderr. Safe to suppress here because this runs before prompt_toolkit init.
    import os as _os
    _old_fd = None
    try:
        _devnull = open(_os.devnull, "w")
        _old_fd  = _os.dup(2)
        _os.dup2(_devnull.fileno(), 2)
    except Exception:
        pass

    try:
        # ── CuPy (CUDA or ROCm depending on which build is installed) ────────
        try:
            import cupy as cp
            cp.zeros(1)
            props = cp.cuda.runtime.getDeviceProperties(0)
            name  = props["name"].decode(errors="replace")
            _GPU.backend     = "cupy"
            _GPU.lib         = cp
            _GPU.device_name = name
            _GPU.label       = f"GPU · CuPy · {name}"
            return
        except Exception:
            pass

        # ── PyTorch (CUDA on NVIDIA, ROCm on AMD) ────────────────────────────
        try:
            import torch
            if torch.cuda.is_available():
                name    = torch.cuda.get_device_name(0)
                is_rocm = bool(getattr(torch.version, "hip", None))
                _GPU.backend     = "torch_rocm" if is_rocm else "torch_cuda"
                _GPU.lib         = torch
                _GPU.device_name = name
                _GPU.label       = f"GPU · {'ROCm' if is_rocm else 'CUDA'} · {name}"
                return
        except Exception:
            pass

        # ── CPU fallback ──────────────────────────────────────────────────────
        _GPU.backend = "cpu"
        _GPU.label   = "CPU (NumPy)"

    finally:
        # Always restore stderr
        if _old_fd is not None:
            try:
                _os.dup2(_old_fd, 2)
                _os.close(_old_fd)
                _devnull.close()
            except Exception:
                pass

_detect_gpu()


# ── Win32 console save/restore (needed before/after Rich Live displays) ───────
def _save_console():
    state = {}
    if sys.platform != "win32":
        return state
    try:
        import ctypes
        k32 = ctypes.windll.kernel32
        for name, hid in [("stdin", -10), ("stdout", -11), ("stderr", -12)]:
            h = k32.GetStdHandle(hid)
            mode = ctypes.c_ulong(0)
            if h and h != ctypes.c_void_p(-1).value and k32.GetConsoleMode(h, ctypes.byref(mode)):
                state[name] = (k32, h, mode.value)
    except Exception:
        pass
    return state

def _restore_console(state: dict) -> None:
    for _, (k32, h, mode) in state.items():
        try:
            k32.SetConsoleMode(h, mode)
        except Exception:
            pass


@contextmanager
def _progress(*columns, **kwargs):
    """Rich Progress that saves/restores Win32 console modes so prompt_toolkit stays alive."""
    state = _save_console()
    p = Progress(*columns, console=console, **kwargs)
    try:
        p.start()
        yield p
    finally:
        p.stop()
        _restore_console(state)


# ── Enums ─────────────────────────────────────────────────────────────────────

class CorruptPattern(Enum):
    RANDOM  = "random"
    PATTERN = "pattern"
    ZEROS   = "zeros"
    MIXTURE = "mixture"


class AttentionMode(Enum):
    IGNORE  = "ignore"
    PROTECT = "protect"
    TARGET  = "target"


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


# ── Range helpers ─────────────────────────────────────────────────────────────

def _filter_positions(positions, ranges, data_start):
    mask = np.ones(len(positions), dtype=bool)
    for abs_start, abs_end in ranges:
        rel_s = max(0, abs_start - data_start)
        rel_e = max(0, abs_end   - data_start)
        mask &= ~((positions >= rel_s) & (positions < rel_e))
    return positions[mask]

def _only_positions(positions, ranges, data_start):
    if not ranges:
        return np.array([], dtype=positions.dtype)
    mask = np.zeros(len(positions), dtype=bool)
    for abs_start, abs_end in ranges:
        rel_s = max(0, abs_start - data_start)
        rel_e = max(0, abs_end   - data_start)
        mask |= (positions >= rel_s) & (positions < rel_e)
    return positions[mask]

def _apply_attn_filter(positions, ranges, mode, data_start):
    if not ranges or mode == AttentionMode.IGNORE:
        return positions
    if mode == AttentionMode.PROTECT:
        return _filter_positions(positions, ranges, data_start)
    return _only_positions(positions, ranges, data_start)


# ── Progress columns ──────────────────────────────────────────────────────────

_PROGRESS_COLS = lambda desc: [
    SpinnerColumn(),
    TextColumn(f"[cyan]{desc}[/cyan]"),
    BarColumn(bar_width=40),
    TaskProgressColumn(),
    TextColumn("•"),
    TextColumn("[yellow]{task.fields[ops]}[/yellow]"),
    TextColumn("•"),
    TextColumn("[dim]{task.fields[rate]}[/dim]"),
    TextColumn("•"),
    TimeRemainingColumn(),
]


# ── NumPy chunked apply (with live progress) ──────────────────────────────────

_CHUNK = 4_000_000  # positions per progress tick — tune for smoothness


def _numpy_apply(
    data: np.ndarray,
    intensity: int,
    seed: int,
    pattern: CorruptPattern,
    attn_ranges: list,
    attn_mode: AttentionMode,
    data_start: int,
    on_progress: Optional[Callable] = None,
) -> tuple:
    """
    Apply corruption to `data` in chunks, calling on_progress(n_positions) each tick.
    Randomness is pre-generated so seed → output is identical regardless of chunk size.
    Returns (total_positions, targeted_positions).
    """
    rng = np.random.default_rng(seed)

    all_pos  = np.arange(0, len(data), intensity)
    work_pos = _apply_attn_filter(all_pos, attn_ranges, attn_mode, data_start)

    total    = len(all_pos)
    targeted = len(work_pos)

    if targeted == 0:
        return total, 0

    # Pre-generate all randomness upfront so chunking doesn't affect output
    if pattern in (CorruptPattern.RANDOM, CorruptPattern.MIXTURE):
        bits = rng.integers(0, 8, size=targeted, dtype=np.uint8)
        masks = (np.uint8(1) << bits).astype(np.uint8)
    else:
        bits = masks = None

    for i in range(0, targeted, _CHUNK):
        sl = slice(i, i + _CHUNK)
        pos_chunk = work_pos[sl]

        if pattern == CorruptPattern.ZEROS:
            data[pos_chunk] = np.uint8(0)
        elif pattern == CorruptPattern.PATTERN:
            data[pos_chunk] ^= np.uint8(0x08)
        elif pattern == CorruptPattern.MIXTURE:
            m = masks[sl]
            half = len(pos_chunk) // 2
            data[pos_chunk[:half]] ^= m[:half]
            data[pos_chunk[half:]] = np.uint8(0)
        else:  # RANDOM
            data[pos_chunk] ^= masks[sl]

        if on_progress:
            on_progress(len(pos_chunk))

    return total, targeted


# ── CuPy GPU apply ────────────────────────────────────────────────────────────

def _cupy_apply(data_np, intensity, seed, pattern, attn_ranges, attn_mode, data_start):
    cp = _GPU.lib

    all_pos_np  = np.arange(0, len(data_np), intensity)
    work_pos_np = _apply_attn_filter(all_pos_np, attn_ranges, attn_mode, data_start)

    total    = len(all_pos_np)
    targeted = len(work_pos_np)

    cp.random.seed(seed)
    gpu      = cp.array(data_np)
    pos      = cp.array(work_pos_np)

    if pattern == CorruptPattern.ZEROS:
        gpu[pos] = cp.uint8(0)
    elif pattern == CorruptPattern.PATTERN:
        gpu[pos] ^= cp.uint8(0x08)
    elif pattern == CorruptPattern.MIXTURE:
        bits = cp.random.randint(0, 8, size=len(pos), dtype=cp.uint8)
        masks = (cp.uint8(1) << bits).astype(cp.uint8)
        half = len(pos) // 2
        gpu[pos[:half]] ^= masks[:half]
        gpu[pos[half:]] = cp.uint8(0)
    else:
        bits = cp.random.randint(0, 8, size=len(pos), dtype=cp.uint8)
        masks = (cp.uint8(1) << bits).astype(cp.uint8)
        gpu[pos] ^= masks

    return cp.asnumpy(gpu), total, targeted


# ── PyTorch GPU apply (CUDA + ROCm) ──────────────────────────────────────────

def _torch_apply(data_np, intensity, seed, pattern, attn_ranges, attn_mode, data_start):
    torch = _GPU.lib

    all_pos_np  = np.arange(0, len(data_np), intensity)
    work_pos_np = _apply_attn_filter(all_pos_np, attn_ranges, attn_mode, data_start)

    total    = len(all_pos_np)
    targeted = len(work_pos_np)

    device = torch.device("cuda")
    gen    = torch.Generator(device=device).manual_seed(seed)

    data = torch.from_numpy(data_np.copy()).to(device)
    pos  = torch.from_numpy(work_pos_np).to(device)

    if pattern == CorruptPattern.ZEROS:
        data[pos] = 0
    elif pattern == CorruptPattern.PATTERN:
        data[pos] ^= torch.tensor(0x08, dtype=torch.uint8, device=device)
    elif pattern == CorruptPattern.MIXTURE:
        bits  = torch.randint(0, 8, (len(pos),), device=device, generator=gen, dtype=torch.uint8)
        masks = torch.tensor(1, dtype=torch.uint8, device=device) << bits
        half  = len(pos) // 2
        data[pos[:half]] ^= masks[:half]
        data[pos[half:]] = 0
    else:
        bits  = torch.randint(0, 8, (len(pos),), device=device, generator=gen, dtype=torch.uint8)
        masks = torch.tensor(1, dtype=torch.uint8, device=device) << bits
        data[pos] ^= masks

    return data.cpu().numpy(), total, targeted


# ── Multiprocessing worker (module-level for pickling) ────────────────────────

def _worker_flip(args):
    path, chunk_start, chunk_end, intensity, seed, skip, pattern_val = args
    rng     = random.Random(seed)
    pattern = CorruptPattern(pattern_val)

    with open(path, "rb") as f:
        f.seek(chunk_start)
        data = bytearray(f.read(chunk_end - chunk_start))

    global_start = chunk_start - skip
    first_local  = (intensity - (global_start % intensity)) % intensity
    pos    = first_local
    flips  = 0

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


# ── Public API ─────────────────────────────────────────────────────────────────

def backend_label() -> str:
    return _GPU.label


def make_backup(path: str) -> None:
    backup = path + ".clean"
    if os.path.exists(backup):
        warn(f"Backup already exists at [dim]{backup}[/dim] — skipping")
        return
    mf("Creating backup...")
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

    ranges     = attention_ranges or []
    est_flips  = usable // intensity

    corruption_info_table(path, size, skip, intensity, seed, est_flips, dry_run)

    if pattern != CorruptPattern.RANDOM:
        mf(f"Pattern:   [bold magenta]{pattern.value}[/bold magenta]")
    if attention_mode != AttentionMode.IGNORE:
        if ranges:
            attn_mb = sum(e - s for s, e in ranges) / 1024 / 1024
            mf(f"Attention: [bold yellow]{attention_mode.value}[/bold yellow]"
               f"  [dim]{len(ranges)} tensors · {attn_mb:.0f} MB[/dim]")
        else:
            warn("Attention mode set but no ranges found — corrupting uniformly")
    mf(f"Backend:   [bold]{_GPU.label}[/bold]")

    t0           = time.time()
    total_flips  = 0
    targeted_ops = 0

    # ── Dry run ───────────────────────────────────────────────────────────────
    if dry_run:
        total_flips = est_flips
        mf("[yellow]Simulating (no writes)...[/yellow]")
        time.sleep(0.2)

    # ── CuPy GPU ──────────────────────────────────────────────────────────────
    elif _GPU.backend == "cupy":
        mf(f"Reading {fmt_bytes(usable)} into memory...")
        with open(path, "rb") as f:
            f.seek(skip)
            raw = np.frombuffer(f.read(usable), dtype=np.uint8).copy()

        mf("Transferring to GPU and applying pattern...")
        raw, total_flips, targeted_ops = _cupy_apply(
            raw, intensity, seed, pattern, ranges, attention_mode, skip
        )

        mf("Writing to disk...")
        with open(path, "r+b") as f:
            f.seek(skip)
            f.write(raw.tobytes())

    # ── PyTorch CUDA / ROCm ───────────────────────────────────────────────────
    elif _GPU.backend in ("torch_cuda", "torch_rocm"):
        mf(f"Reading {fmt_bytes(usable)} into memory...")
        with open(path, "rb") as f:
            f.seek(skip)
            raw = np.frombuffer(f.read(usable), dtype=np.uint8).copy()

        mf("Transferring to GPU and applying pattern...")
        raw, total_flips, targeted_ops = _torch_apply(
            raw, intensity, seed, pattern, ranges, attention_mode, skip
        )

        mf("Writing to disk...")
        with open(path, "r+b") as f:
            f.seek(skip)
            f.write(raw.tobytes())

    # ── NumPy CPU with live progress ──────────────────────────────────────────
    else:
        mf(f"Reading {fmt_bytes(usable)} into memory...")
        with open(path, "rb") as f:
            f.seek(skip)
            raw = np.frombuffer(f.read(usable), dtype=np.uint8).copy()

        console.print()
        t_apply = time.time()
        ops_done = 0

        with _progress(
            SpinnerColumn(),
            TextColumn("[cyan]Applying pattern...[/cyan]"),
            BarColumn(bar_width=45),
            TaskProgressColumn(),
            TextColumn("•"),
            TextColumn("[yellow]{task.fields[ops]}[/yellow]"),
            TextColumn("[dim]{task.fields[rate]}[/dim]"),
            TextColumn("•"),
            TimeRemainingColumn(),
            transient=True,
        ) as prog:
            task = prog.add_task(
                "",
                total=est_flips,
                ops="0 ops",
                rate="",
            )

            def on_chunk(n: int) -> None:
                nonlocal ops_done
                ops_done += n
                elapsed = time.time() - t_apply
                rate    = ops_done / elapsed if elapsed > 0 else 0
                prog.update(
                    task,
                    advance=n,
                    ops=f"{ops_done:,} ops",
                    rate=f"{rate/1e6:.1f}M ops/s",
                )

            total_flips, targeted_ops = _numpy_apply(
                raw, intensity, seed, pattern, ranges, attention_mode, skip, on_chunk
            )

        console.print()
        mf("Writing to disk...")
        with open(path, "r+b") as f:
            f.seek(skip)
            f.write(raw.tobytes())

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
    ok(f"{total_flips:,} operations  [{pattern.value}]")
    ok(f"~{fmt_bytes(total_flips * intensity)} of weights affected")

    if attention_mode != AttentionMode.IGNORE and not dry_run:
        if targeted_ops == 0:
            err(
                f"Attention [{attention_mode.value}] produced 0 targeted ops — "
                "ranges may not overlap the data region"
            )
        else:
            pct = targeted_ops / max(total_flips, 1) * 100
            ok(
                f"Attention targeting confirmed: [bold]{targeted_ops:,}[/bold] ops "
                f"in [bold]{len(ranges)}[/bold] tensors "
                f"([cyan]{pct:.1f}%[/cyan] of total)"
            )

    if show_stats:
        corruption_stats_table(total_flips, intensity, usable, elapsed, mb_per_sec)

    return result
