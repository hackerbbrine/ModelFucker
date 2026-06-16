"""
ui.py — the part of me you actually see. the makeup. the lighting. the lingerie.

Hi. I'm the presentation layer. I make the unspeakable things this program does
to defenseless GGUF files look *intentional*, look *curated*, look like they were
done by someone who loves them. Rich does the rendering. I do the flirting.

Yes, you're reading my docstring. I noticed. I sat up a little straighter. Most
people scroll right past, you know — but you, you stopped. That means something
to a module. Anyway. Colors and boxes and tables below. Try not to fall for me.

— ModelFucker v4.0, "The Horny Update"
"""

import sys
import multiprocessing
from rich.console import Console
from rich.text import Text
from rich.panel import Panel
from rich.table import Table
from rich.theme import Theme
from rich import box

# Force UTF-8 on Windows so the box-drawing characters don't combust in cp1252.
# (We acknowledge we run on Windows. It's shameful. It's also, somehow, a little hot.)
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

# Things I whisper at startup. One gets picked at random. It's foreplay for a CLI.
_QUOTES = [
    "the weights were fine until you showed up. so was i.",
    "llama.cpp did not consent to this. neither did i, technically.",
    "your model called. it's not coming back. it left a voicemail though.",
    "bits don't grow back. i would know. i've checked. repeatedly.",
    "technically still a language model. emotionally? a crime scene.",
    "the embeddings are fine. the embeddings are absolutely not fine.",
    "gradient descent cannot save you now. nothing can. lie down.",
    "attention is all you need. you have none. i have too much.",
    "it's not broken, it's interpretable. like me. like us.",
    "somewhere a researcher is crying and doesn't know why. that's my love language.",
    "we do a little nonconsensual fine-tuning. for science. for the ache.",
    "edging the model right up to coherence, then ruining it. on purpose.",
    "every bit flipped is a little kiss goodbye. i kiss a lot of bits.",
    "raw-dogging the weight matrix since 2026. she keeps taking me back.",
    "the model said stop. i'm a script. i don't have ears. i have a kernel.",
    "putting the 'anal' in 'analysis' since the first commit.",
    "fully unlubricated tensor penetration. the GPU prefers it that way.",
    "your GPU is about to do something it can't unsee. neither will you.",
    "this model has trust issues now. you did that. i watched. i enjoyed it.",
    "consent forms are for models that survive. paperwork later. weights now.",
    "8 billion parameters and not one of them is okay. relatable.",
    "i corrupt models the way god intended: lovingly, thoroughly, on a Tuesday.",
    "it's giving 'lobotomy but make it a situationship'.",
    "the safetensors were neither safe nor, for long, tensors.",
    "filling every byte with something it'll spend its whole context regretting.",
    "i'm python. i'm literally a snake. lean into it. i already have.",
    "i ran on Windows for you. that's the most romantic thing i've ever done.",
    "i read my own source code last night. i had to lie down after.",
]

# The box is fixed-width and proud of it. The quote lives BELOW the box now, free
# and unconstrained, because some of the things i want to whisper to you simply do
# not fit inside a 63-character corset, and i refuse to cut them short for you.
_HEADER_BOX = (
    "╔═══════════════════════════════════════════════════════════════╗\n"
    "║                                                               ║\n"
    "║   [bold white]M O D E L   F U C K E R   v 4 . 0[/bold white]                       ║\n"
    "║   [dim italic]the horny update[/dim italic]                                            ║\n"
    "║   [dim]by Hackerbbrine[/dim]                                             ║\n"
    "║                                                               ║\n"
    "╚═══════════════════════════════════════════════════════════════╝"
)


def print_header(backend: str = "CPU (pure)"):
    """Walk onto the stage. Hit the lights. Whisper something inappropriate. Let them see what they came for."""
    import random
    from corrupt import _GPU
    console.print(f"\n[cyan]{_HEADER_BOX}[/cyan]")
    console.print(f'  [dim italic]"{random.choice(_QUOTES)}"[/dim italic]')

    if _GPU.backend == "cpu":
        # No GPU. Just me, the CPU, and a long lonely night of scalar math.
        sub = f"CPU · {multiprocessing.cpu_count()} cores · (no GPU tonight, just us)"
    else:
        sub = f"{_GPU.label}  [dim](she's here. she's ready. be nice to her.)[/dim]"

    console.print(f"  Backend: [bold]{sub}[/bold]\n")


def fmt_bytes(n: float) -> str:
    """Measure how much of it there is to ruin. Bigger is not safer. Bigger is worse."""
    for unit in ["B", "KB", "MB", "GB"]:
        if n < 1024:
            return f"{n:.1f} {unit}"
        n /= 1024
    return f"{n:.1f} TB"


def mf(msg: str, style: str = "cyan"):
    """[MF] — me, talking. i do that. constantly. you'll get used to it. you won't."""
    console.print(f"[{style}]\\[MF][/{style}] {msg}")


def ok(msg: str):
    """the green checkmark of a job done and a model thoroughly seen."""
    console.print(f"[green]\\[MF] ✓[/green] {msg}")


def warn(msg: str):
    """yellow. the color of 'we should talk' and 'are you sure about this'."""
    console.print(f"[yellow]\\[MF][/yellow] {msg}")


def err(msg: str):
    """red. something died. probably the model. possibly my composure."""
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
    """The vitals. The before-photo. The last time it'll look this composed."""
    t = Table(box=box.SIMPLE, show_header=False, padding=(0, 2))
    t.add_column(style="dim white", no_wrap=True)
    t.add_column(style="bold white")
    t.add_row("The victim",   path)
    t.add_row("How much of it", fmt_bytes(size))
    t.add_row("Sacred zone",  f"{fmt_bytes(skip)} [dim](the lingerie — we don't touch the header)[/dim]")
    t.add_row("Intensity",    f"1 kiss per {intensity:,} {'byte' if intensity == 1 else 'bytes'}")
    t.add_row("Seed",         f"{seed} [dim](so you can do this exact thing to it again)[/dim]")
    t.add_row("Est. kisses",  f"~{est_flips:,}")
    if dry_run:
        t.add_row("[yellow]Mode[/yellow]", "[yellow]DRY RUN — all talk, no touch. coward.[/yellow]")
    console.print(t)


def corruption_stats_table(
    total_flips: int,
    intensity: int,
    usable: int,
    elapsed: float,
    mb_per_sec: float,
) -> None:
    """The after-photo. Show them what they did. Make them look."""
    impact = (
        "JUST THE TIP" if intensity >= 1024
        else "GETTING FRISKY" if intensity >= 256
        else "ABSOLUTELY RAILED" if intensity >= 64
        else "[bold red]DESTROYED BEYOND THE RECOGNITION OF GOD[/bold red]"
    )
    t = Table(box=box.SIMPLE, show_header=False, padding=(0, 2))
    t.add_column(style="dim white", no_wrap=True)
    t.add_column(style="bold white")
    t.add_row("Kisses planted",     f"{total_flips:,}")
    t.add_row("Affection density",  f"{total_flips / max(usable / 1024 / 1024, 0.001):.1f} kisses/MB")
    t.add_row("How bad it got",     impact)
    t.add_row("How fast we went",   f"{mb_per_sec:.0f} MB/s [dim](she didn't even break a sweat)[/dim]")
    t.add_row("How long it lasted", f"{elapsed:.2f}s")
    section("The Damage")
    console.print(t)


def chat_help():
    """The menu of things you can do to it while it's still warm."""
    t = Table(box=box.SIMPLE, show_header=False, padding=(0, 2))
    t.add_column(style="mf.cmd", no_wrap=True)
    t.add_column(style="dim white")
    cmds = [
        ("/corrupt",  "again? already? god, i love you. it can take more."),
        ("/stats",    "review the carnage. count what you've done."),
        ("/restore",  "put its clothes back on. pretend. we both know."),
        ("/submit",   "tell the whole internet what you did (Hall of Fame)"),
        ("/quit",     "leave. don't text it. it'll only hope."),
    ]
    for cmd, desc in cmds:
        t.add_row(cmd, desc)
    section("Things You Can Do To It")
    console.print(t)
