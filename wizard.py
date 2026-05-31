"""
wizard.py — The interactive fuckery selection interface.
Because just running the script is too easy.
"""

import os
import random
from pathlib import Path
from typing import Optional

from rich.table import Table
from rich.panel import Panel
from rich.text import Text
from rich.columns import Columns
from rich.prompt import Prompt, Confirm
from rich import box

from ui import console, fmt_bytes, section, ok, warn, err


# ── Fuckery presets ──────────────────────────────────────────────────────────
# (label, intensity, tagline)
# intensity=None means dry-run / no corruption — just load and chat
FUCKERY_LEVELS = [
    ("Untouched",          None,  "no corruption — just vibe"),
    ("Barely Fucked",      4096,  "a gentle nudge"),
    ("Kinda Fucked",       1024,  "something's off"),
    ("Sorta Fucked",        256,  "noticeably unhinged"),
    ("Pretty Fucked",        64,  "hold on to something"),
    ("Completely Fucked",    16,  "barely coherent"),
    ("Cosmically Fucked",     4,  "probably dead"),
]


def _fuckery_color(idx: int) -> str:
    """Color gradient from chill to chaos."""
    colors = ["dim white", "green", "cyan", "yellow", "dark_orange", "red", "bold red"]
    return colors[min(idx, len(colors) - 1)]


def _intensity_label(intensity: Optional[int]) -> str:
    if intensity is None:
        return "[dim]no corruption[/dim]"
    return f"[dim](1 flip / {intensity:,} bytes)[/dim]"


def pick_fuckery_level() -> tuple[Optional[int], bool]:
    """
    Show the fuckery menu. Returns (intensity, dry_run).
    intensity=None means skip corruption entirely.
    dry_run=True means simulate only.
    """
    console.print()

    t = Table(
        box=box.ROUNDED,
        border_style="cyan",
        show_header=True,
        header_style="bold cyan",
        padding=(0, 2),
        title="[bold white]SELECT YOUR LEVEL OF FUCKERY[/bold white]",
        title_style="bold",
    )
    t.add_column("Level",   style="bold",        no_wrap=True)
    t.add_column("",        style="dim",         no_wrap=True, width=26)
    t.add_column("Vibe",    style="dim white",   no_wrap=True)

    for i, (label, intensity, tagline) in enumerate(FUCKERY_LEVELS):
        color = _fuckery_color(i)
        t.add_row(
            f"[dim white]\\[{i}][/dim white]  [{color}]{label}[/{color}]",
            _intensity_label(intensity),
            tagline,
        )

    # Custom option
    t.add_row(
        f"[dim white]\\[{len(FUCKERY_LEVELS)}][/dim white]  [magenta]Custom Fuck:[/magenta]",
        "[dim](you decide)[/dim]",
        "for the scientists",
    )

    console.print(t)
    console.print()

    max_choice = len(FUCKERY_LEVELS)
    while True:
        raw = Prompt.ask(
            f"[cyan]Your choice[/cyan] [dim](0–{max_choice})[/dim]",
            default="2",
        )
        try:
            choice = int(raw)
            if 0 <= choice <= max_choice:
                break
        except ValueError:
            pass
        err(f"Enter a number between 0 and {max_choice}.")

    if choice == len(FUCKERY_LEVELS):
        # Custom Fuck
        while True:
            raw = Prompt.ask("[magenta]Custom Fuck:[/magenta] intensity (bytes per flip)")
            try:
                intensity = int(raw)
                if intensity >= 1:
                    break
                err("Must be >= 1.")
            except ValueError:
                err("Numbers only.")
        return intensity, False

    label, intensity, _ = FUCKERY_LEVELS[choice]
    if intensity is None:
        return None, False  # no corruption, just chat

    return intensity, False


def pick_model_path(provided: Optional[str] = None) -> Optional[str]:
    """Validate provided path or ask for one."""
    if provided and os.path.exists(provided):
        return provided

    if provided:
        err(f"File not found: [dim]{provided}[/dim]")

    console.print("[dim]Enter the path to a .gguf model file.[/dim]")
    while True:
        path = Prompt.ask("[cyan]Model path[/cyan]").strip().strip('"')
        if os.path.exists(path):
            return path
        err(f"File not found: [dim]{path}[/dim]")


def show_model_banner(model_path: str) -> None:
    size = os.path.getsize(model_path)
    name = Path(model_path).name
    console.print(
        f"\n  [dim]Model :[/dim] [bold white]{name}[/bold white]"
        f"  [dim]({fmt_bytes(size)})[/dim]\n"
    )


def confirm_fuckery(intensity: Optional[int], model_path: str, seed: int) -> bool:
    """Show a summary panel and ask for final confirmation."""
    name = Path(model_path).name
    size = os.path.getsize(model_path)
    usable = size - 52_428_800

    if intensity is None:
        description = "[green]No corruption[/green] — loading clean model for chat"
        est = "0"
    else:
        est = f"~{usable // intensity:,}"
        # Find matching level name
        level_name = "Custom Fuck"
        for label, lvl_int, _ in FUCKERY_LEVELS:
            if lvl_int == intensity:
                level_name = label
                break
        color = _fuckery_color(
            next((i for i, (_, li, _) in enumerate(FUCKERY_LEVELS) if li == intensity), 6)
        )
        description = (
            f"[{color}]{level_name}[/{color}]"
            f"  [dim](1 flip / {intensity:,} bytes)[/dim]"
        )

    summary = Table(box=box.SIMPLE, show_header=False, padding=(0, 2))
    summary.add_column(style="dim white", no_wrap=True)
    summary.add_column(style="bold white")
    summary.add_row("Model",      name)
    summary.add_row("Size",       fmt_bytes(size))
    summary.add_row("Fuckery",    description)
    summary.add_row("Est. flips", est)
    summary.add_row("Seed",       str(seed))

    console.print(Panel(summary, title="[bold cyan]Ready to Fuck[/bold cyan]", border_style="cyan"))
    console.print()

    return Confirm.ask("[cyan]Proceed?[/cyan]", default=True)


def run_wizard(model_path: Optional[str] = None) -> tuple[str, Optional[int], int]:
    """
    Full interactive wizard. Returns (model_path, intensity, seed).
    intensity=None means skip corruption.
    """
    model_path = pick_model_path(model_path)
    show_model_banner(model_path)
    intensity, _ = pick_fuckery_level()
    seed = random.randint(0, 999_999)

    console.print()
    if not confirm_fuckery(intensity, model_path, seed):
        console.print("[dim]Aborted. Come back when you're ready to commit.[/dim]\n")
        raise SystemExit(0)

    return model_path, intensity, seed
