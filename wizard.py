"""
wizard.py — Full interactive setup flow.
Asks every question before touching anything.
"""

import os
import random
from pathlib import Path
from typing import Optional

from rich.table import Table
from rich.panel import Panel
from rich.prompt import Prompt, Confirm
from rich import box

from ui import console, fmt_bytes, section, ok, warn, err, mf
from corrupt import CorruptPattern, AttentionMode


# ── Fuckery presets ───────────────────────────────────────────────────────────
FUCKERY_LEVELS = [
    ("Untouched",         None,  "no corruption — just vibe"),
    ("Barely Fucked",     4096,  "a gentle nudge"),
    ("Kinda Fucked",      1024,  "something's off"),
    ("Sorta Fucked",       256,  "noticeably unhinged"),
    ("Pretty Fucked",       64,  "hold on to something"),
    ("Completely Fucked",   16,  "barely coherent"),
    ("Cosmically Fucked",    4,  "probably dead"),
]

_LEVEL_COLORS = ["dim white", "green", "cyan", "yellow", "dark_orange", "red", "bold red"]


def _fuckery_color(i: int) -> str:
    return _LEVEL_COLORS[min(i, len(_LEVEL_COLORS) - 1)]


def _intensity_label(intensity: Optional[int]) -> str:
    if intensity is None:
        return "[dim]no corruption[/dim]"
    return f"[dim](1 flip / {intensity:,} bytes)[/dim]"


# ── Step 1: Model path ────────────────────────────────────────────────────────

def pick_model_path(provided: Optional[str] = None) -> str:
    if provided and os.path.exists(provided):
        return provided
    if provided:
        err(f"File not found: [dim]{provided}[/dim]")
    console.print("[dim]Enter the path to a .gguf model file.[/dim]")
    while True:
        path = Prompt.ask("[cyan]Model path[/cyan]").strip().strip('"')
        if os.path.exists(path):
            return path
        err(f"Not found: [dim]{path}[/dim]")


# ── Step 2: Action ────────────────────────────────────────────────────────────

def pick_action(model_path: str) -> str:
    """Returns 'corrupt', 'restore', or 'chat'."""
    backup_exists = os.path.exists(model_path + ".clean")
    size = os.path.getsize(model_path)
    name = Path(model_path).name

    console.print(Panel(
        f"[bold white]{name}[/bold white]  [dim]({fmt_bytes(size)})[/dim]\n"
        + (f"[green]Backup exists[/green]" if backup_exists else "[dim]No backup yet[/dim]"),
        title="[bold cyan]Model[/bold cyan]",
        border_style="cyan",
        padding=(0, 2),
    ))
    console.print()

    t = Table(box=box.ROUNDED, border_style="cyan", show_header=False, padding=(0, 3))
    t.add_column(style="bold white", no_wrap=True)
    t.add_column(style="dim white")
    t.add_row("[0]  Corrupt",    "flip bits, break weights, lose sleep")
    t.add_row("[1]  Just Chat",  "load model as-is and start talking")
    if backup_exists:
        t.add_row("[2]  Restore",   "put it back the way it was")
    console.print(t)
    console.print()

    choices = {"0": "corrupt", "1": "chat", "2": "restore"} if backup_exists else {"0": "corrupt", "1": "chat"}
    while True:
        raw = Prompt.ask("[cyan]Action[/cyan]", default="0")
        if raw in choices:
            return choices[raw]
        err(f"Pick a number from the list.")


# ── Step 3: Fuckery level ─────────────────────────────────────────────────────

def pick_fuckery_level() -> Optional[int]:
    """Returns intensity int, or None for no corruption."""
    console.print()
    t = Table(
        box=box.ROUNDED, border_style="cyan", show_header=True,
        header_style="bold cyan", padding=(0, 2),
        title="[bold white]SELECT YOUR LEVEL OF FUCKERY[/bold white]",
    )
    t.add_column("Level", style="bold", no_wrap=True)
    t.add_column("",      style="dim",  no_wrap=True, width=26)
    t.add_column("Vibe",  style="dim white", no_wrap=True)

    for i, (label, intensity, tagline) in enumerate(FUCKERY_LEVELS):
        color = _fuckery_color(i)
        t.add_row(
            f"[dim white]\\[{i}][/dim white]  [{color}]{label}[/{color}]",
            _intensity_label(intensity),
            tagline,
        )
    t.add_row(
        f"[dim white]\\[{len(FUCKERY_LEVELS)}][/dim white]  [magenta]Custom Fuck:[/magenta]",
        "[dim](you decide)[/dim]",
        "for the scientists",
    )
    console.print(t)
    console.print()

    max_c = len(FUCKERY_LEVELS)
    while True:
        raw = Prompt.ask(f"[cyan]Choice[/cyan] [dim](0–{max_c})[/dim]", default="2")
        try:
            c = int(raw)
            if 0 <= c <= max_c:
                break
        except ValueError:
            pass
        err(f"Enter 0–{max_c}.")

    if c == len(FUCKERY_LEVELS):
        while True:
            raw = Prompt.ask("[magenta]Custom Fuck:[/magenta] intensity (bytes per flip)")
            try:
                v = int(raw)
                if v >= 1:
                    return v
                err("Must be >= 1.")
            except ValueError:
                err("Numbers only.")

    return FUCKERY_LEVELS[c][1]


# ── Step 4: Corruption pattern ────────────────────────────────────────────────

def pick_pattern() -> CorruptPattern:
    console.print()
    t = Table(box=box.ROUNDED, border_style="magenta", show_header=False, padding=(0, 3))
    t.add_column(style="bold white", no_wrap=True)
    t.add_column(style="dim white")
    rows = [
        ("[0]  Random",   "random bit flip at each position  [dim](default chaos)[/dim]"),
        ("[1]  Pattern",  "always flip bit 3  [dim](structured decay)[/dim]"),
        ("[2]  Zeros",    "zero out bytes entirely  [dim](erase, don't flip)[/dim]"),
        ("[3]  Mixture",  "50% random flips + 50% zeros  [dim](maximum variety)[/dim]"),
    ]
    for label, desc in rows:
        t.add_row(label, desc)
    console.print(Panel(t, title="[bold magenta]CORRUPTION PATTERN[/bold magenta]",
                        border_style="magenta", padding=(0, 1)))
    console.print()

    mapping = {"0": CorruptPattern.RANDOM, "1": CorruptPattern.PATTERN,
               "2": CorruptPattern.ZEROS,  "3": CorruptPattern.MIXTURE}
    while True:
        raw = Prompt.ask("[cyan]Pattern[/cyan] [dim](0–3)[/dim]", default="0")
        if raw in mapping:
            return mapping[raw]
        err("Pick 0–3.")


# ── Step 5: Attention heads ───────────────────────────────────────────────────

def pick_attention_mode(model_path: str) -> tuple:
    """
    Parse the GGUF header to find attention tensors.
    Returns (AttentionMode, attention_ranges).
    attention_ranges is a list of (abs_start, abs_end) byte tuples.
    """
    from gguf_parser import try_parse

    console.print()
    mf("Scanning GGUF header for attention tensors...")

    gguf = try_parse(model_path)

    if gguf is None:
        warn("Couldn't parse GGUF header — attention targeting unavailable")
        return AttentionMode.IGNORE, []

    ranges = gguf.attention_ranges
    n_attn = len(gguf.attention_tensors)

    if not ranges:
        warn("No attention tensors found in header")
        return AttentionMode.IGNORE, []

    attn_mb = sum(e - s for s, e in ranges) / 1024 / 1024

    t = Table(box=box.SIMPLE, show_header=False, padding=(0, 2))
    t.add_column(style="dim white", no_wrap=True)
    t.add_column(style="bold white")
    t.add_row("Attention tensors", str(n_attn))
    t.add_row("Attention heads",   str(gguf.attention_head_count) or "unknown")
    t.add_row("KV heads",          str(gguf.attention_kv_count) or "unknown")
    t.add_row("Protected size",    f"{attn_mb:.0f} MB")

    console.print(Panel(
        t,
        title="[bold yellow]ATTENTION HEADS DETECTED[/bold yellow]",
        border_style="yellow",
        padding=(0, 1),
    ))
    console.print()

    at = Table(box=box.ROUNDED, border_style="yellow", show_header=False, padding=(0, 3))
    at.add_column(style="bold white", no_wrap=True)
    at.add_column(style="dim white")
    at.add_row("[0]  Ignore",   "corrupt everything uniformly")
    at.add_row("[1]  Protect",  f"skip attention tensors ({attn_mb:.0f} MB safe)")
    at.add_row("[2]  Target",   f"ONLY corrupt attention tensors ({attn_mb:.0f} MB affected)")
    console.print(at)
    console.print()

    mapping = {"0": AttentionMode.IGNORE, "1": AttentionMode.PROTECT, "2": AttentionMode.TARGET}
    while True:
        raw = Prompt.ask("[cyan]Attention mode[/cyan] [dim](0–2)[/dim]", default="0")
        if raw in mapping:
            return mapping[raw], ranges
        err("Pick 0–2.")


# ── Step 6: Seed ──────────────────────────────────────────────────────────────

def pick_seed() -> int:
    console.print()
    raw = Prompt.ask(
        "[cyan]Seed[/cyan] [dim](enter a number for reproducibility, or leave blank for random)[/dim]",
        default="",
    )
    if raw.strip():
        try:
            return int(raw.strip())
        except ValueError:
            warn("Not a number — using random seed")
    return random.randint(0, 999_999)


# ── Step 7: Confirm ───────────────────────────────────────────────────────────

def confirm_plan(
    model_path: str,
    intensity: Optional[int],
    pattern: CorruptPattern,
    attention_mode: AttentionMode,
    seed: int,
    n_attn_tensors: int,
) -> bool:
    size   = os.path.getsize(model_path)
    usable = size - 52_428_800

    if intensity is None:
        fuckery_str = "[green]Untouched[/green]"
        est_str = "0"
    else:
        est = usable // intensity if usable > 0 else 0
        level_name = next(
            (l for l, iv, _ in FUCKERY_LEVELS if iv == intensity),
            "Custom Fuck"
        )
        color = next(
            (_fuckery_color(i) for i, (_, iv, _) in enumerate(FUCKERY_LEVELS) if iv == intensity),
            "magenta"
        )
        fuckery_str = f"[{color}]{level_name}[/{color}]  [dim](1 flip / {intensity:,} bytes)[/dim]"
        est_str = f"~{est:,}"

    t = Table(box=box.SIMPLE, show_header=False, padding=(0, 2))
    t.add_column(style="dim white", no_wrap=True)
    t.add_column(style="bold white")
    t.add_row("Model",           Path(model_path).name)
    t.add_row("Size",            fmt_bytes(size))
    t.add_row("Fuckery",         fuckery_str)
    t.add_row("Pattern",         f"[magenta]{pattern.value}[/magenta]")
    t.add_row("Attention",       f"[yellow]{attention_mode.value}[/yellow]"
                                 + (f"  [dim]({n_attn_tensors} tensors)[/dim]" if n_attn_tensors else ""))
    t.add_row("Est. ops",        est_str)
    t.add_row("Seed",            str(seed))

    console.print()
    console.print(Panel(t, title="[bold cyan]READY TO FUCK[/bold cyan]",
                        border_style="cyan", padding=(0, 1)))
    console.print()
    return Confirm.ask("[cyan]Proceed?[/cyan]", default=True)


# ── Main entry point ──────────────────────────────────────────────────────────

def run_wizard(model_path: Optional[str] = None) -> dict:
    """
    Run the full interactive wizard.
    Returns a dict with all the chosen parameters, or raises SystemExit(0) on abort.
    Keys: model_path, action, intensity, pattern, attention_mode,
          attention_ranges, seed
    """
    model_path = pick_model_path(model_path)

    action = pick_action(model_path)

    if action == "restore":
        return {"action": "restore", "model_path": model_path}

    if action == "chat":
        return {"action": "chat", "model_path": model_path}

    # action == "corrupt"
    intensity      = pick_fuckery_level()
    pattern        = pick_pattern()
    attn_mode, attn_ranges = pick_attention_mode(model_path)
    seed           = pick_seed()

    if not confirm_plan(model_path, intensity, pattern, attn_mode, seed, len(attn_ranges)):
        console.print("[dim]Aborted.[/dim]\n")
        raise SystemExit(0)

    return {
        "action":            "corrupt",
        "model_path":        model_path,
        "intensity":         intensity,
        "pattern":           pattern,
        "attention_mode":    attn_mode,
        "attention_ranges":  attn_ranges,
        "seed":              seed,
    }
