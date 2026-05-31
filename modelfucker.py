#!/usr/bin/env python3
"""
Usage:
    python modelfucker.py <model.gguf> [options]

Options:
    --intensity N     Flip one bit every N bytes (default: 1024)
    --skip N          Skip first N bytes of file (default: 50MB — skips GGUF header)
    --seed N          RNG seed for reproducibility (default: random)
    --workers N       Multiprocessing workers if NumPy unavailable (default: all cores)
    --n-ctx N         Context length for inference (default: 2048)
    --temp F          Sampling temperature (default: 0.8)
    --max-tokens N    Max tokens per response (default: 512)
    --no-chat         Skip inference, just corrupt and exit
    --restore         Restore from .clean backup
    --stats           Show detailed corruption stats
    --dry-run         Preview without writing anything
    --help            Show this message

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
        backend_label, HAS_NUMPY, HAS_CUPY
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

    # ── Choose wizard vs direct CLI ───────────────────────────────────────────
    # Wizard runs when no --intensity is explicitly passed (interactive mode).
    # Passing --intensity bypasses the wizard for scripted/automated use.
    cli_mode = args.intensity != 1024 or args.seed is not None or args.dry_run

    if cli_mode:
        # ── Legacy CLI path ───────────────────────────────────────────────────
        path = args.model
        if not path:
            err("Model path required in CLI mode")
            sys.exit(1)
        if not os.path.exists(path):
            err(f"File not found: {path}")
            sys.exit(1)
        seed = args.seed if args.seed is not None else random.randint(0, 999_999)
        intensity = args.intensity
        dry_run = args.dry_run
    else:
        # ── Interactive wizard ────────────────────────────────────────────────
        from wizard import run_wizard
        path, intensity, seed = run_wizard(model_path=args.model)
        dry_run = False

    # ── Corruption pass ───────────────────────────────────────────────────────
    corruption_passes = []

    if intensity is not None and not dry_run:
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

    console.print(f"\n[cyan]We hope you liked your fucking experience[/cyan]\n")


if __name__ == "__main__":
    # Windows multiprocessing guard — the price of running science on Windows
    multiprocessing.freeze_support()
    main()
