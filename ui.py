"""
ui.py — Rich terminal UI for ModelFucker v3.0
All the pretty stuff so the chaos looks intentional.
"""

import sys
import multiprocessing
from rich.console import Console
from rich.text import Text
from rich.panel import Panel
from rich.table import Table
from rich.theme import Theme
from rich import box

# Force UTF-8 on Windows so box-drawing characters don't explode cp1252
if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

theme = Theme({
    "mf.brand":  "bold cyan",
    "mf.ok":     "bold green",
    "mf.warn":   "bold yellow",
    "mf.err":    "bold red",
    "mf.dim":    "dim white",
    "mf.label":  "bold white",
    "mf.cmd":    "bold magenta",
})

console = Console(theme=theme, highlight=False, legacy_windows=False)

_QUOTES = [
    "the weights were fine until you showed up.",
    "llama.cpp did not consent to this.",
    "your model called. it's not coming back.",
    "bits don't grow back, you know.",
    "technically still a language model.",
    "the embeddings are fine. the embeddings are not fine.",
    "gradient descent cannot save you now.",
    "attention is all you need. you have none.",
    "it's not broken, it's interpretable.",
    "somewhere a researcher is crying and doesn't know why.",
]

_BOX_WIDTH = 63  # visible chars between the ║ characters

def _header(quote: str) -> str:
    padded = f'"{quote}"'
    # 3 leading spaces + content + trailing spaces to fill box
    quote_pad = max(0, _BOX_WIDTH - 3 - len(padded))
    author_pad = max(0, _BOX_WIDTH - 3 - len("by Hackerbbrine"))
    return (
        "╔═══════════════════════════════════════════════════════════════╗\n"
        "║                                                               ║\n"
        "║   [bold white]M O D E L   F U C K E R   v 3 . 0[/bold white]                       ║\n"
        "║                                                               ║\n"
        f'║   [dim]by Hackerbbrine[/dim]{" " * author_pad}║\n'
        f'║   [dim]{padded}[/dim]{" " * quote_pad}║\n'
        "║                                                               ║\n"
        "╚═══════════════════════════════════════════════════════════════╝"
    )


def print_header(backend: str = "CPU (pure)"):
    import random
    from corrupt import _GPU
    console.print(f"\n[cyan]{_header(random.choice(_QUOTES))}[/cyan]")

    if _GPU.backend == "cpu":
        sub = f"CPU · {multiprocessing.cpu_count()} cores"
    else:
        sub = _GPU.label

    console.print(f"  Backend: [bold]{sub}[/bold]\n")


def fmt_bytes(n: float) -> str:
    for unit in ["B", "KB", "MB", "GB"]:
        if n < 1024:
            return f"{n:.1f} {unit}"
        n /= 1024
    return f"{n:.1f} TB"


def mf(msg: str, style: str = "cyan"):
    """[MF] prefixed log line — the bread and butter."""
    console.print(f"[{style}]\\[MF][/{style}] {msg}")


def ok(msg: str):
    console.print(f"[green]\\[MF] ✓[/green] {msg}")


def warn(msg: str):
    console.print(f"[yellow]\\[MF][/yellow] {msg}")


def err(msg: str):
    console.print(f"[red]\\[MF] ✗ {msg}[/red]")


def section(title: str):
    console.rule(f"[cyan]{title}[/cyan]", style="dim cyan")


def corruption_info_table(
    path: str,
    size: int,
    skip: int,
    intensity: int,
    seed: int,
    est_flips: int,
    dry_run: bool,
) -> None:
    t = Table(box=box.SIMPLE, show_header=False, padding=(0, 2))
    t.add_column(style="dim white", no_wrap=True)
    t.add_column(style="bold white")
    t.add_row("Target",    path)
    t.add_row("File size", fmt_bytes(size))
    t.add_row("Skip zone", fmt_bytes(skip))
    t.add_row("Intensity", f"1 flip per {intensity:,} {'byte' if intensity == 1 else 'bytes'}")
    t.add_row("Seed",      str(seed))
    t.add_row("Est flips", f"~{est_flips:,}")
    if dry_run:
        t.add_row("[yellow]Mode[/yellow]", "[yellow]DRY RUN — no writes[/yellow]")
    console.print(t)


def corruption_stats_table(
    total_flips: int,
    intensity: int,
    usable: int,
    elapsed: float,
    mb_per_sec: float,
) -> None:
    impact = (
        "LIGHT" if intensity >= 1024
        else "MODERATE" if intensity >= 256
        else "HEAVY" if intensity >= 64
        else "[bold red]CATASTROPHIC[/bold red]"
    )
    t = Table(box=box.SIMPLE, show_header=False, padding=(0, 2))
    t.add_column(style="dim white", no_wrap=True)
    t.add_column(style="bold white")
    t.add_row("Bits flipped",        f"{total_flips:,}")
    t.add_row("Corruption density",  f"{total_flips / max(usable / 1024 / 1024, 0.001):.1f} flips/MB")
    t.add_row("Estimated impact",    impact)
    t.add_row("Throughput",          f"{mb_per_sec:.0f} MB/s")
    t.add_row("Time",                f"{elapsed:.2f}s")
    section("Corruption Stats")
    console.print(t)


def chat_help():
    t = Table(box=box.SIMPLE, show_header=False, padding=(0, 2))
    t.add_column(style="mf.cmd", no_wrap=True)
    t.add_column(style="dim white")
    cmds = [
        ("/corrupt",  "run another corruption pass"),
        ("/stats",    "show cumulative corruption stats"),
        ("/restore",  "restore the clean backup and reload"),
        ("/submit",   "submit to the Hall of Fame on GitHub"),
        ("/quit",     "exit"),
    ]
    for cmd, desc in cmds:
        t.add_row(cmd, desc)
    section("Available Commands")
    console.print(t)
