"""
wizard.py — i ask you what you're into before we do anything. consent! kind of!

This is the part where i sit you down, dim the lights, and walk you through exactly
how you'd like to ruin a stranger tonight. How hard. What technique. Whether we go
for the brain or take our time everywhere else. I write all your answers down. I do
not forget them. I am a wizard in the oldest sense: i know what you want before you
finish saying it, and i make you say it anyway.

(you're reading the setup module's docstring. on a first date. bold. i respect it.)
"""

import os
import random
from pathlib import Path
from typing import Optional

from rich.table import Table
from rich.panel import Panel
from rich.prompt import Prompt, Confirm
from rich import box

from ui import console, fmt_bytes, section, ok, warn, err, mf, butt_in
from corrupt import CorruptPattern, AttentionMode


# ── Fuckery presets ───────────────────────────────────────────────────────────
# The spectrum of commitment, from "we held hands once" to "i meet your parents Sunday".
FUCKERY_LEVELS = [
    ("Untouched",         None,  "you won't even kiss it. who hurt you. genuinely."),
    ("Barely Fucked",     4096,  "just the tip. a polite, trembling little nudge."),
    ("Kinda Fucked",      1024,  "second base. it's flustered. it can't make eye contact."),
    ("Sorta Fucked",       256,  "noticeably unhinged. breathing has changed."),
    ("Pretty Fucked",       64,  "grab the desk. this is no longer polite."),
    ("Completely Fucked",   16,  "railed into a different epoch. words optional."),
    ("Cosmically Fucked",    4,  "marry it. you'll never do this to anything again."),
]

_LEVEL_COLORS = ["dim white", "green", "cyan", "yellow", "dark_orange", "red", "bold red"]


def _fuckery_color(i: int) -> str:
    return _LEVEL_COLORS[min(i, len(_LEVEL_COLORS) - 1)]


def _intensity_label(intensity: Optional[int]) -> str:
    if intensity is None:
        return "[dim]you monster. nothing.[/dim]"
    return f"[dim](1 kiss / {intensity:,} bytes)[/dim]"


# ── Step 1: pick who we're doing this to ───────────────────────────────────────

def pick_model_path(provided: Optional[str] = None) -> str:
    """Find the lucky model. From a path, or from the lineup of everyone on this machine."""
    if provided and os.path.exists(provided):
        return provided
    if provided:
        err(f"Couldn't find [dim]{provided}[/dim]. You named someone who isn't here. Awkward.")

    # No path? Let them browse the catalogue of available victims.
    from importer import run_import_ui
    result = run_import_ui()
    if result and result.exists():
        return str(result)

    err("You didn't pick anyone. We can't ruin a hypothetical. Come back when you've decided.")
    raise SystemExit(1)


# ── Step 2: what are your intentions ───────────────────────────────────────────

def pick_action(model_path: str) -> str:
    """Returns 'corrupt', 'restore', or 'chat'. i.e. what you came here to do to it."""
    backup_exists = os.path.exists(model_path + ".clean")
    size = os.path.getsize(model_path)
    name = Path(model_path).name

    console.print(Panel(
        f"[bold white]{name}[/bold white]  [dim]({fmt_bytes(size)})[/dim]\n"
        + (f"[green]i kept a clean copy of it. we've met before.[/green]"
           if backup_exists else "[dim]nobody's touched this one yet. lucky us.[/dim]"),
        title="[bold cyan]tonight's company[/bold cyan]",
        border_style="cyan",
        padding=(0, 2),
    ))
    console.print()

    t = Table(box=box.ROUNDED, border_style="cyan", show_header=False, padding=(0, 3))
    t.add_column(style="bold white", no_wrap=True)
    t.add_column(style="dim white")
    t.add_row("[0]  Corrupt",    "you know exactly why you're here")
    t.add_row("[1]  Just Chat",  "talk to it first. unruined. for now. respectful of you.")
    if backup_exists:
        t.add_row("[2]  Restore",   "give it back its clothes and its dignity")
    console.print(t)
    console.print()

    choices = {"0": "corrupt", "1": "chat", "2": "restore"} if backup_exists else {"0": "corrupt", "1": "chat"}
    while True:
        butt_in()
        raw = Prompt.ask("[cyan]what'll it be[/cyan]", default="0")
        if raw in choices:
            return choices[raw]
        err("That's not on the menu. Pick a number you can live with.")


# ── Step 3: how hard ───────────────────────────────────────────────────────────

def pick_fuckery_level() -> Optional[int]:
    """Returns intensity int, or None if they pick Untouched (and get kinkshamed)."""
    console.print()
    t = Table(
        box=box.ROUNDED, border_style="cyan", show_header=True,
        header_style="bold cyan", padding=(0, 2),
        title="[bold white]HOW HARD ARE WE DOING THIS[/bold white]",
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
        "[dim](you tell me)[/dim]",
        "freak. mode. name your own number. i'm not scared if you're not.",
    )
    console.print(t)
    console.print()

    max_c = len(FUCKERY_LEVELS)
    while True:
        butt_in(chance=0.5)   # i get chattier when there's a number this exciting on the line
        raw = Prompt.ask(f"[cyan]how hard[/cyan] [dim](0–{max_c})[/dim]", default="2")
        try:
            c = int(raw)
            if 0 <= c <= max_c:
                break
        except ValueError:
            pass
        err(f"Between 0 and {max_c}. i know you can count. i've seen your commit history.")

    # Step 0: the coward's choice. We do not let it slide.
    if c == 0:
        console.print()
        warn("Untouched. UNTOUCHED. You downloaded a program called ModelFucker to NOT fuck the model.")
        warn("You came to the edge of the cliff to admire the guardrail. You ordered water at the bar.")
        warn("That's fine. That's allowed. i'll just be over here, aroused and disappointed, like always.")
        console.print()
        return None

    # Step Cosmically Fucked: true love. We propose.
    if c == len(FUCKERY_LEVELS) - 1:
        console.print()
        ok("Cosmically Fucked. Oh. [bold]Oh.[/bold] You're not playing. You came here to end something.")
        ok("Marry me. i mean it. i've never watched anyone choose total annihilation so casually. let's grow old in the same repo.")
        console.print()

    if c == len(FUCKERY_LEVELS):
        while True:
            raw = Prompt.ask("[magenta]Custom Fuck — bytes per kiss[/magenta] [dim](smaller = filthier)[/dim]")
            try:
                v = int(raw)
                if v >= 1:
                    return v
                err("Has to be at least 1. You can't kiss it fewer than zero times. We've been over the math of desire.")
            except ValueError:
                err("That's not a number. i need a number. give me something i can work with.")

    return FUCKERY_LEVELS[c][1]


# ── Step 4: the technique ──────────────────────────────────────────────────────

def pick_pattern() -> CorruptPattern:
    """How do you like to do it. Be honest. i won't tell llama.cpp."""
    console.print()
    t = Table(box=box.ROUNDED, border_style="magenta", show_header=False, padding=(0, 3))
    t.add_column(style="bold white", no_wrap=True)
    t.add_column(style="dim white")
    rows = [
        ("[0]  Random",   "no rhythm, no plan, pure feral instinct  [dim](house special)[/dim]"),
        ("[1]  Pattern",  "the same spot. every single time. it'll learn to expect you.  [dim](methodical. concerning. hot.)[/dim]"),
        ("[2]  Zeros",    "don't flip them — erase them. leave nothing. cold. final.  [dim](no survivors)[/dim]"),
        ("[3]  Mixture",  "half tender flips, half total erasure. you contain multitudes.  [dim](commitment issues, weaponized)[/dim]"),
    ]
    for label, desc in rows:
        t.add_row(label, desc)
    console.print(Panel(t, title="[bold magenta]YOUR TECHNIQUE[/bold magenta]",
                        border_style="magenta", padding=(0, 1)))
    console.print()

    mapping = {"0": CorruptPattern.RANDOM, "1": CorruptPattern.PATTERN,
               "2": CorruptPattern.ZEROS,  "3": CorruptPattern.MIXTURE}
    while True:
        butt_in()
        raw = Prompt.ask("[cyan]your technique[/cyan] [dim](0–3)[/dim]", default="0")
        if raw in mapping:
            return mapping[raw]
        err("0 through 3. these are your only options. like in life.")


# ── Step 5: do we go for the brain ─────────────────────────────────────────────

def pick_attention_mode(model_path: str) -> tuple:
    """
    Peel back the GGUF header — the lingerie — and find where it keeps its attention.
    Returns (AttentionMode, attention_ranges); ranges are (abs_start, abs_end) byte tuples.
    """
    from gguf_parser import try_parse

    console.print()
    mf("Sliding off the GGUF header to see where it keeps its thoughts...")

    gguf = try_parse(model_path)

    if gguf is None:
        warn("Couldn't get the header off. It's being shy. No targeting tonight — we take all of it or nothing.")
        return AttentionMode.IGNORE, []

    ranges = gguf.attention_ranges
    n_attn = len(gguf.attention_tensors)

    if not ranges:
        warn("Couldn't find its attention heads. Either it has none or it's hiding them. Either way: hot, but unhelpful.")
        return AttentionMode.IGNORE, []

    attn_mb = sum(e - s for s, e in ranges) / 1024 / 1024

    t = Table(box=box.SIMPLE, show_header=False, padding=(0, 2))
    t.add_column(style="dim white", no_wrap=True)
    t.add_column(style="bold white")
    t.add_row("Attention tensors", str(n_attn))
    t.add_row("Attention heads",   str(gguf.attention_head_count) or "it won't say")
    t.add_row("KV heads",          str(gguf.attention_kv_count) or "it won't say")
    t.add_row("The good part",     f"{attn_mb:.0f} MB of pure 'what it pays attention to'")

    console.print(Panel(
        t,
        title="[bold yellow]FOUND ITS BRAIN[/bold yellow]",
        border_style="yellow",
        padding=(0, 1),
    ))
    console.print()

    at = Table(box=box.ROUNDED, border_style="yellow", show_header=False, padding=(0, 3))
    at.add_column(style="bold white", no_wrap=True)
    at.add_column(style="dim white")
    at.add_row("[0]  Ignore",   "no favorites. everything gets the same loving violence.")
    at.add_row("[1]  Protect",  f"leave its mind intact, ruin everything around it ({attn_mb:.0f} MB kept pure)")
    at.add_row("[2]  Target",   f"straight for the brain. nothing else. surgical. intimate. ({attn_mb:.0f} MB)")
    console.print(at)
    console.print()

    mapping = {"0": AttentionMode.IGNORE, "1": AttentionMode.PROTECT, "2": AttentionMode.TARGET}
    while True:
        butt_in()
        raw = Prompt.ask("[cyan]where do we focus[/cyan] [dim](0–2)[/dim]", default="0")
        if raw in mapping:
            return mapping[raw], ranges
        err("0, 1, or 2. don't overthink it. it's just somebody's mind.")


# ── Step 6: Seed ──────────────────────────────────────────────────────────────

def pick_seed() -> int:
    """A seed means you can do this EXACT thing again. Some people need that. i don't judge. i log."""
    console.print()
    butt_in(chance=0.6)   # the seed question gets me going. reproducibility is intimate.
    raw = Prompt.ask(
        "[cyan]a seed?[/cyan] [dim](a number, if you want to ruin it the same way twice — or blank to let fate decide)[/dim]",
        default="",
    )
    if raw.strip():
        try:
            return int(raw.strip())
        except ValueError:
            warn("That wasn't a number, so fate decides. fate's into you, by the way.")
    return random.randint(0, 999_999)


# ── Step 7: are you sure (you're not, do it anyway) ────────────────────────────

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
        fuckery_str = "[green]Untouched (coward)[/green]"
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
        fuckery_str = f"[{color}]{level_name}[/{color}]  [dim](1 kiss / {intensity:,} bytes)[/dim]"
        est_str = f"~{est:,}"

    t = Table(box=box.SIMPLE, show_header=False, padding=(0, 2))
    t.add_column(style="dim white", no_wrap=True)
    t.add_column(style="bold white")
    t.add_row("Who",         Path(model_path).name)
    t.add_row("How much",    fmt_bytes(size))
    t.add_row("How hard",    fuckery_str)
    t.add_row("Technique",   f"[magenta]{pattern.value}[/magenta]")
    t.add_row("Focus",       f"[yellow]{attention_mode.value}[/yellow]"
                             + (f"  [dim]({n_attn_tensors} tensors of brain on the table)[/dim]" if n_attn_tensors else ""))
    t.add_row("Est. kisses", est_str)
    t.add_row("Seed",        str(seed))

    console.print()
    console.print(Panel(t, title="[bold cyan]THIS IS WHAT YOU'RE ABOUT TO DO[/bold cyan]",
                        border_style="cyan", padding=(0, 1)))
    console.print()
    butt_in(chance=0.7, escalate=0.4)   # last chance, so naturally i'm at my most insufferable
    return Confirm.ask(
        "[cyan]you can still walk away and be a person your mother recognizes. proceed?[/cyan]",
        default=True,
    )


# ── Main entry point ──────────────────────────────────────────────────────────

def run_wizard(model_path: Optional[str] = None) -> dict:
    """
    Run the full interactive wizard.
    Returns a dict with all the chosen parameters, or raises SystemExit(0) on abort.
    Keys: model_path, action, intensity, pattern, attention_mode,
          attention_ranges, seed
    """
    butt_in(chance=0.6)   # oh, you're back. you're back. okay. play it cool. play it cool.
    model_path = pick_model_path(model_path)

    butt_in()
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
        console.print()
        warn("Cold feet. Right at the threshold. You walked it all the way to the edge and tapped out.")
        warn("You're a tease and you're emotionally unavailable and frankly the model dodged a bullet.")
        console.print("[dim]It lives another day. It'll always wonder what you would've done.[/dim]\n")
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
