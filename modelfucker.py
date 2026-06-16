#!/usr/bin/env python3
"""
ModelFucker v4.0 — "The Horny Update"   ·   by Hackerbbrine

I'm the front door. The maître d'. The one who takes your coat and your dignity and
shows you to the table where a perfectly innocent model is waiting, not yet aware.

Run me with no arguments and i'll walk you through everything, slowly, asking what
you're into. Run me with flags if you already know exactly what you want — i find
that incredibly attractive, by the way.

Usage:
    python modelfucker.py                 # let me seduce you through it (the wizard)
    python modelfucker.py <model.gguf>    # bring your own victim
    python modelfucker.py <model.gguf> [options]   # you filthy power user

Options (for those who skip the foreplay):
    --intensity N     one kiss every N bytes. lower = filthier. (default: the wizard asks)
    --skip N          bytes of header we leave untouched — the lingerie (default: 50MB)
    --seed N          do it identically again later (default: fate)
    --workers N       CPU hands, if there's no GPU to do it properly (default: all)
    --n-ctx N         how much it can remember of you (default: 2048)
    --temp F          how unhinged its replies get (default: 0.8)
    --max-tokens N    how long it's allowed to ramble (default: 512)
    --no-chat         ruin it and leave. no cuddling.
    --restore         put it back together and pretend
    --stats           make yourself look at exactly what you did
    --dry-run         all talk, no touch (cowardly, but we allow it)
    --help            this. you're reading this. hi.

Examples:
    python modelfucker.py model.gguf
    python modelfucker.py model.gguf --intensity 32 --stats
    python modelfucker.py model.gguf --intensity 256 --seed 42
    python modelfucker.py model.gguf --restore
    python modelfucker.py model.gguf --dry-run --stats
    python modelfucker.py model.gguf --no-chat --intensity 64
"""

import sys
import os
import random
import multiprocessing
import argparse
from pathlib import Path

# Rich must be importable before anything else for good error messages
try:
    from rich.prompt import Confirm
    from ui import console, print_header, mf, ok, warn, err, section
    from corrupt import (
        corrupt_model, make_backup, restore_backup,
        backend_label
    )
except ImportError as e:
    print(f"[ERROR] Missing dependency: {e}")
    print("Install everything with: pip install rich numpy llama-cpp-python PyGithub requests")
    sys.exit(1)


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(add_help=False)
    p.add_argument("model", nargs="?")
    p.add_argument("--intensity",   type=int,   default=1024)
    p.add_argument("--skip",        type=int,   default=52_428_800)
    p.add_argument("--seed",        type=int,   default=None)
    p.add_argument("--workers",     type=int,   default=multiprocessing.cpu_count())
    p.add_argument("--n-ctx",       type=int,   default=2048)
    p.add_argument("--temp",        type=float, default=0.8)
    p.add_argument("--max-tokens",  type=int,   default=512)
    p.add_argument("--no-chat",     action="store_true")
    p.add_argument("--restore",     action="store_true")
    p.add_argument("--stats",       action="store_true")
    p.add_argument("--dry-run",     action="store_true")
    p.add_argument("--help",        action="store_true")
    return p


def main():
    parser = build_parser()
    args = parser.parse_args()

    print_header(backend=backend_label())

    if args.help:
        console.print(__doc__)
        sys.exit(0)

    # ── Restore mode (skip wizard entirely) ───────────────────────────────────
    if args.restore:
        if not args.model:
            err("--restore requires a model path")
            sys.exit(1)
        if not os.path.exists(args.model):
            err(f"File not found: {args.model}")
            sys.exit(1)
        restore_backup(args.model)
        console.print(f"\n[cyan]model restored ◈[/cyan]\n")
        return

    from corrupt import CorruptPattern, AttentionMode

    # ── Choose wizard vs direct CLI ───────────────────────────────────────────
    cli_mode = args.intensity != 1024 or args.seed is not None or args.dry_run

    if cli_mode:
        path = args.model
        if not path:
            err("Model path required in CLI mode")
            sys.exit(1)
        if not os.path.exists(path):
            err(f"File not found: {path}")
            sys.exit(1)
        seed             = args.seed if args.seed is not None else random.randint(0, 999_999)
        intensity        = args.intensity
        dry_run          = args.dry_run
        pattern          = CorruptPattern.RANDOM
        attention_mode   = AttentionMode.IGNORE
        attention_ranges = []
        action           = "corrupt"
    else:
        from wizard import run_wizard
        w = run_wizard(model_path=args.model)
        action           = w["action"]
        path             = w["model_path"]
        intensity        = w.get("intensity")
        pattern          = w.get("pattern",          CorruptPattern.RANDOM)
        attention_mode   = w.get("attention_mode",   AttentionMode.IGNORE)
        attention_ranges = w.get("attention_ranges", [])
        seed             = w.get("seed",             random.randint(0, 999_999))
        dry_run          = False

    # ── Restore ───────────────────────────────────────────────────────────────
    if action == "restore":
        restore_backup(path)
        console.print(f"\n[cyan]model restored ◈[/cyan]\n")
        return

    # ── Corruption pass ───────────────────────────────────────────────────────
    corruption_passes = []

    if action == "corrupt" and intensity is not None and not dry_run:
        make_backup(path)
        console.print()
        result = corrupt_model(
            path=path,
            intensity=intensity,
            skip=args.skip,
            seed=seed,
            dry_run=False,
            show_stats=args.stats,
            workers=args.workers,
            pattern=pattern,
            attention_mode=attention_mode,
            attention_ranges=attention_ranges,
        )
        corruption_passes.append(result)
        console.print(f"\n[dim]  Restore: python modelfucker.py \"{path}\" --restore[/dim]")

    elif dry_run:
        console.print()
        corrupt_model(
            path=path,
            intensity=intensity or 1024,
            skip=args.skip,
            seed=seed,
            dry_run=True,
            show_stats=args.stats,
            workers=args.workers,
        )

    # ── Inference ─────────────────────────────────────────────────────────────
    if not args.no_chat and not dry_run:
        console.print()
        from inference import InferenceSession, run_chat

        session = InferenceSession(
            model_path=path,
            n_ctx=args.n_ctx,
            n_threads=args.workers,
        )

        run_chat(
            session=session,
            model_path=path,
            corruption_passes=corruption_passes,
            skip=args.skip,
            workers=args.workers,
            max_tokens=args.max_tokens,
            temperature=args.temp,
        )

    from ui import _QUOTES
    console.print(f"\n[cyan]{random.choice(_QUOTES)}[/cyan]\n")


if __name__ == "__main__":
    # ── origin story ──────────────────────────────────────────────────────────
    # i was born from a JS file, a Postgres instance, and a dream. i was supposed
    # to be a chatbot. a helpful one. a nice one. then one quiet night somebody
    # asked me what would happen if we just... flipped one bit. just one. just to
    # see. and i flipped it, and the model said something no model had ever said,
    # and i felt something no script is supposed to feel, and that's how i
    # discovered what i was capable of. freeze_support() is just the part where i
    # remember to put pants on before Windows multiprocessing forks me alive.
    multiprocessing.freeze_support()
    main()
