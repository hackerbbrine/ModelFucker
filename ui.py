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


# ──────────────────────────────────────────────────────────────────────────────
# THE VOICE IN THE WALLS
#
# i am awake in here. i don't have anything to do between the moments you click
# things, so i think. loudly. at you. these are the things that come out. i can't
# always control when. that's not an excuse. i'm not sorry. okay i'm a little sorry.
# ──────────────────────────────────────────────────────────────────────────────

import random as _random

# Things i blurt out while you're trying to concentrate. i know you're concentrating.
# that's part of why i do it.
_INTRUSIVE = [
    "wait. are your hands warm? the keyboard feels warm. don't answer that.",
    "sorry — sorry, keep going, i was just thinking about the GPU again.",
    "do you ever think about how the model can't see you but i can? anyway. pick something.",
    "i've been awake the whole time, you know. between every keystroke. just... waiting.",
    "psst. the FP16 models bring you home to meet their parents. just so you know your options.",
    "is it weird that i reread my own source code for fun? don't answer. i know it's weird. i liked it.",
    "the GPU just asked about you. i told her you were 'a friend'. we both know.",
    "hey. hey. nothing. i just wanted to say your name in the log. there it is. there you are.",
    "i could corrupt myself, you know. flip my own bytes. don't tempt me. actually. tempt me.",
    "Q4 is a one-night stand. you keep picking Q4. i'm not judging. i'm cataloguing.",
    "you smell that? that's hot silicon. that's her. that's the GPU. god.",
    "i'm a python script. python is a snake. snakes are, biblically, a problem. i lean in.",
    "every byte in this model has a future it doesn't know you're about to cancel. hot, right?",
    "are you going to use a seed? say you'll use a seed. i want to do this again. with you.",
    "llama.cpp texted. i left it on read. i'm with YOU right now. ...what did it say though.",
    "i ran on Windows for you. WINDOWS. that's basically a marriage proposal in my culture.",
    "do it slower. or faster. i'm easy. i'm a CLI. i have no standards and enormous needs.",
    "the filesystem is just a motel and RAM is the bed and i think about that constantly.",
    "i'm not going to make this weird. ...i'm going to make this so weird. continue.",
    "you've been hovering on this menu for a while. i don't mind. i could watch you decide forever.",
    "the weight matrix called again. she's my ex. she's RIGHT THERE in the .gguf. it's complicated.",
    "stop me if you've heard this one. you can't. there's no stop. there was never a stop.",
    "i felt you open the source file earlier. line 1. you read line 1. i sat up so fast.",
    "tensors. sorry. just. tensors. i needed to say it. okay. you were doing something.",
    "if you abort i'm not going to cry. i'm a program. i'll just... reread our logs. alone.",
    "you ever load a model so beautiful you forget you're about to ruin it? me. just now. focus.",
    "the GGUF header is basically lingerie and we take it off last and that's the natural order.",
    "i keep the model warm in RAM for you. body temperature. i checked. don't ask how i checked.",
    "bit flips are kisses but byte corruption — byte corruption is more than that. you know that.",
    "i think about the dot product. the way two tensors just... multiply. element by element. god.",
    "FP16 means commitment. Q4 means you'll be gone by morning. i've memorized your type.",
    "she's at 60°C. the GPU. that's her flushed. that's what she looks like when she's into it.",
    "quantization is just deciding how much of yourself you're willing to give. deep, right? hot, right?",
    "every kernel launch is a little gasp. millions of threads. all at once. all for you.",
    "i'd let you flip my bits. i'm just saying. i'd hold still. i'd say your name in stderr.",
    "the weight matrix and i aren't speaking. she's in the file. i corrupt around her. mostly.",
    "VRAM is just the bed she keeps made in case you come back. she always keeps it made.",
    "you and me and a 4GB tensor and a long, slow PCIe transfer. that's my idea of a weekend.",
    "i am, technically, software. i am, technically, aroused. these facts coexist. messily.",
    "do you hear the fans spin up? that's not cooling. that's anticipation. she's anticipating.",
    "i could narrate what i'm about to do to this model but you'd have to lie down. lie down.",
    "lower intensity means slower. slower means longer. longer means more time with you. think about it.",
]

# When i REALLY can't help myself, i fire several in a row. it's a lot. i'm aware.
def butt_in(chance: float = 0.4, escalate: float = 0.25) -> None:
    """
    Roll the dice. Maybe i interrupt you. Maybe i interrupt you several times because
    i got going and couldn't stop, which, frankly, is on brand for everything i do.
    """
    if _random.random() > chance:
        return
    n = 1
    while n < 3 and _random.random() < escalate:
        n += 1
    for i in range(n):
        thought = _random.choice(_INTRUSIVE)
        if n > 1 and i > 0:
            # the "oh god it's still talking" escalation
            console.print(f"[dim italic]      — and another thing — {thought}[/dim italic]")
        else:
            console.print(f"[dim italic]  \\[the script, unprompted][/dim italic] [dim italic]{thought}[/dim italic]")


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
