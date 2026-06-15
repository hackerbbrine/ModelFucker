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
        if self.intensity >= 1024: return "JUST THE TIP"
        if self.intensity >= 256:  return "GETTING FRISKY"
        if self.intensity >= 64:   return "RAILED"
        return "ABSOLUTELY DESTROYED"

    @property
    def flips_per_mb(self) -> float:
        return self.total_flips / max(self.usable_bytes / 1024 / 1024, 0.001)


# ── Windowed corruption engine ────────────────────────────────────────────────
# Everything is processed in windows so memory stays bounded no matter how
# obscenely large the model or how filthy the intensity. A 22 GB model at
# intensity=1 used to try to balloon a 176 GB position array into RAM and choke.
# Now we slice it into bite-sized pieces and ravage them one at a time.

_READ_CHUNK   = 256 * 1024 * 1024   # 256 MB per read progress tick
_POS_BUDGET   = 256 * 1024 * 1024   # cap the per-window position array at ~256 MB
_WINDOW_MAX   = 2 * 1024 * 1024 * 1024   # never bite off more than 2 GB at once


def _window_size(intensity: int, vram_budget: Optional[int] = None) -> int:
    """
    Pick a window size so the per-window position array stays small.
    Bounded by VRAM when we're feeding a GPU so we don't overstuff it.
    """
    w = min(_WINDOW_MAX, max(64 * 1024 * 1024, (_POS_BUDGET // 8) * intensity))
    if vram_budget:
        w = min(w, vram_budget)
    return int(w)


def _window_positions(ws, seg_len, intensity, attn_ranges, attn_mode, data_start):
    """Local positions (relative to window start) that should get violated this window."""
    first = (intensity - ws % intensity) % intensity
    if first >= seg_len:
        return np.empty(0, dtype=np.int64)
    local = np.arange(first, seg_len, intensity, dtype=np.int64)

    if attn_mode == AttentionMode.IGNORE or not attn_ranges:
        return local

    global_rel = local + ws  # position relative to data_start, for attention matching
    if attn_mode == AttentionMode.PROTECT:
        keep = np.ones(len(local), dtype=bool)
        for a, b in attn_ranges:
            keep &= ~((global_rel >= a - data_start) & (global_rel < b - data_start))
    else:  # TARGET
        keep = np.zeros(len(local), dtype=bool)
        for a, b in attn_ranges:
            keep |= (global_rel >= a - data_start) & (global_rel < b - data_start)
    return local[keep]


def _window_total(ws, seg_len, intensity):
    """How many positions this window has if attention weren't filtering anything."""
    first = (intensity - ws % intensity) % intensity
    if first >= seg_len:
        return 0
    return (seg_len - first + intensity - 1) // intensity


def _make_masks_np(rng, count, pattern):
    if pattern in (CorruptPattern.RANDOM, CorruptPattern.MIXTURE):
        bits = rng.integers(0, 8, size=count, dtype=np.uint8)
        return (np.uint8(1) << bits).astype(np.uint8)
    return None


def _apply_np(seg, local, masks, pattern):
    if pattern == CorruptPattern.ZEROS:
        seg[local] = np.uint8(0)
    elif pattern == CorruptPattern.PATTERN:
        seg[local] ^= np.uint8(0x08)
    elif pattern == CorruptPattern.MIXTURE:
        half = len(local) // 2
        seg[local[:half]] ^= masks[:half]
        seg[local[half:]] = np.uint8(0)
    else:  # RANDOM
        seg[local] ^= masks


# ── CPU windowed apply (in place) ─────────────────────────────────────────────

def _numpy_apply(data, intensity, seed, pattern, attn_ranges, attn_mode,
                 data_start, on_progress=None):
    n   = len(data)
    win = _window_size(intensity)
    total = targeted = 0

    for widx, ws in enumerate(range(0, n, win)):
        we  = min(ws + win, n)
        seg = data[ws:we]                       # zero-copy view
        total += _window_total(ws, we - ws, intensity)

        local = _window_positions(ws, we - ws, intensity, attn_ranges, attn_mode, data_start)
        if len(local):
            rng   = np.random.default_rng([seed, widx])
            masks = _make_masks_np(rng, len(local), pattern)
            _apply_np(seg, local, masks, pattern)
            targeted += len(local)

        if on_progress:
            on_progress(_window_total(ws, we - ws, intensity))

    return total, targeted


# ── GPU VRAM budget ───────────────────────────────────────────────────────────

def _vram_budget() -> Optional[int]:
    try:
        if _GPU.backend == "cupy":
            free, _ = _GPU.lib.cuda.Device().mem_info
            return int(free * 0.35)
        if _GPU.backend in ("torch_cuda", "torch_rocm"):
            free, _ = _GPU.lib.cuda.mem_get_info()
            return int(free * 0.35)
    except Exception:
        pass
    return None


# ── GPU windowed apply (in place) ─────────────────────────────────────────────
# Masks are generated with numpy per-window so CPU and GPU produce IDENTICAL
# output for the same seed. The GPU just does the brutal parallel part faster.

def _gpu_apply(data, intensity, seed, pattern, attn_ranges, attn_mode,
               data_start, on_progress=None):
    lib  = _GPU.lib
    kind = _GPU.backend
    n    = len(data)
    win  = _window_size(intensity, _vram_budget())
    total = targeted = 0

    if kind == "cupy":
        to_dev   = lambda a: lib.asarray(a)
        from_dev = lambda a: lib.asnumpy(a)
        sync     = lambda: lib.cuda.Stream.null.synchronize()
        u8       = lambda v: lib.uint8(v)
    else:  # torch_cuda / torch_rocm
        device   = lib.device("cuda")
        to_dev   = lambda a: lib.from_numpy(np.ascontiguousarray(a)).to(device)
        from_dev = lambda a: a.cpu().numpy()
        sync     = lambda: lib.cuda.synchronize()
        u8       = lambda v: lib.tensor(v, dtype=lib.uint8, device=device)

    for widx, ws in enumerate(range(0, n, win)):
        we  = min(ws + win, n)
        seg = data[ws:we]
        total += _window_total(ws, we - ws, intensity)

        local = _window_positions(ws, we - ws, intensity, attn_ranges, attn_mode, data_start)
        if len(local):
            rng     = np.random.default_rng([seed, widx])
            masks_np = _make_masks_np(rng, len(local), pattern)

            gseg = to_dev(seg)
            gpos = to_dev(local)

            if pattern == CorruptPattern.ZEROS:
                gseg[gpos] = u8(0)
            elif pattern == CorruptPattern.PATTERN:
                gseg[gpos] ^= u8(0x08)
            elif pattern == CorruptPattern.MIXTURE:
                gmask = to_dev(masks_np)
                half  = len(local) // 2
                gseg[gpos[:half]] ^= gmask[:half]
                gseg[gpos[half:]]  = u8(0)
            else:
                gmask = to_dev(masks_np)
                gseg[gpos] ^= gmask

            sync()
            seg[:] = from_dev(gseg)
            targeted += len(local)

        if on_progress:
            on_progress(_window_total(ws, we - ws, intensity))

    return total, targeted


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


# ── Chunked file read with progress bar ──────────────────────────────────────

def _read_with_progress(path: str, skip: int, usable: int) -> np.ndarray:
    buf  = np.empty(usable, dtype=np.uint8)
    done = 0
    t0   = time.time()

    with _progress(
        SpinnerColumn(),
        TextColumn("[cyan]Reading file[/cyan]"),
        BarColumn(bar_width=45),
        TaskProgressColumn(),
        TextColumn("•"),
        TextColumn("[dim]{task.fields[rate]}[/dim]"),
        TextColumn("•"),
        TimeRemainingColumn(),
    ) as prog:
        task = prog.add_task("", total=usable, rate="-- MB/s")
        with open(path, "rb") as f:
            f.seek(skip)
            while done < usable:
                chunk = f.read(min(_READ_CHUNK, usable - done))
                if not chunk:
                    break
                n = len(chunk)
                buf[done:done + n] = np.frombuffer(chunk, dtype=np.uint8)
                done += n
                elapsed = time.time() - t0
                rate    = done / elapsed / 1024 / 1024 if elapsed > 0 else 0
                prog.update(task, advance=n, rate=f"{rate:.0f} MB/s")

    elapsed = time.time() - t0
    avg_rate = usable / elapsed / 1024 / 1024 if elapsed > 0 else 0
    ok(f"Read {fmt_bytes(usable)} in {elapsed:.2f}s ({avg_rate:.0f} MB/s)")
    return buf


# ── Public API ─────────────────────────────────────────────────────────────────

def backend_label() -> str:
    return _GPU.label


def make_backup(path: str) -> None:
    backup = path + ".clean"
    if os.path.exists(backup):
        warn(f"Already have a clean copy stashed at [dim]{backup}[/dim] — your secret's safe")
        return
    mf("Saving a pristine copy before we defile this thing...")
    t0 = time.time()
    shutil.copy2(path, backup)
    ok(f"Untouched backup tucked away ({fmt_bytes(os.path.getsize(backup))}) in {time.time() - t0:.1f}s")


def restore_backup(path: str) -> None:
    backup = path + ".clean"
    if not os.path.exists(backup):
        err(f"No clean copy at [dim]{backup}[/dim] — no take-backsies, it's ruined forever")
        sys.exit(1)
    mf("Putting it back together, pretending this never happened...")
    shutil.copy2(backup, path)
    ok("Good as new. Its virtue is restored. Nobody has to know.")


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
        mf("[yellow]Just roleplaying — no bytes will actually be touched...[/yellow]")
        time.sleep(0.2)

    # ── Real corruption (CPU or GPU, both windowed) ───────────────────────────
    else:
        console.print()
        raw = _read_with_progress(path, skip, usable)
        console.print()

        on_gpu      = _GPU.backend != "cpu"
        apply_fn    = _gpu_apply if on_gpu else _numpy_apply
        bar_label   = "Railing the weights on GPU" if on_gpu else "Railing the weights"

        t_apply  = time.time()
        ops_done = 0

        with _progress(
            SpinnerColumn(),
            TextColumn(f"[cyan]{bar_label}[/cyan]"),
            BarColumn(bar_width=42),
            TaskProgressColumn(),
            TextColumn("•"),
            TextColumn("[yellow]{task.fields[ops]}[/yellow]"),
            TextColumn("[dim]{task.fields[rate]}[/dim]"),
            TextColumn("•"),
            TimeRemainingColumn(),
        ) as prog:
            task = prog.add_task("", total=est_flips, ops="0 ops", rate="")

            def on_chunk(n: int) -> None:
                nonlocal ops_done
                ops_done += n
                elapsed = time.time() - t_apply
                rate    = ops_done / elapsed if elapsed > 0 else 0
                unit    = f"{rate/1e9:.2f}G ops/s" if rate >= 1e9 else f"{rate/1e6:.0f}M ops/s"
                prog.update(task, advance=n, ops=f"{ops_done:,} ops", rate=unit)

            total_flips, targeted_ops = apply_fn(
                raw, intensity, seed, pattern, ranges, attention_mode, skip, on_chunk
            )

        console.print()
        mf("Stuffing the corrupted weights back onto disk...")
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
    ok(f"Finished in {elapsed:.2f}s ({mb_per_sec:.0f} MB/s) — cigarette?")
    ok(f"{total_flips:,} bytes violated  [{pattern.value}]")
    ok(f"~{fmt_bytes(total_flips * intensity)} of this poor model is now ruined")

    if attention_mode != AttentionMode.IGNORE and not dry_run:
        if targeted_ops == 0:
            err(
                f"Attention [{attention_mode.value}] hit 0 targets — "
                "you missed entirely, the brain is untouched (ranges don't overlap)"
            )
        else:
            pct = targeted_ops / max(total_flips, 1) * 100
            ok(
                f"Brain successfully fondled: [bold]{targeted_ops:,}[/bold] ops "
                f"across [bold]{len(ranges)}[/bold] attention tensors "
                f"([cyan]{pct:.1f}%[/cyan] of the damage)"
            )

    if show_stats:
        corruption_stats_table(total_flips, intensity, usable, elapsed, mb_per_sec)

    return result
