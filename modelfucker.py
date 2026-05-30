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

    if args.help or not args.model:
        console.print(__doc__)
        sys.exit(0)

    path = args.model

    if not os.path.exists(path):
        err(f"File not found: {path}")
        sys.exit(1)

    seed = args.seed if args.seed is not None else random.randint(0, 999_999)

    # ── Restore mode ──────────────────────────────────────────────────────────
    if args.restore:
        restore_backup(path)
        console.print(f"\n[cyan]◈ FIBERCORE — model restored ◈[/cyan]\n")
        return

    # ── Corruption pass ───────────────────────────────────────────────────────
    if not args.dry_run:
        make_backup(path)

    console.print()
    result = corrupt_model(
        path=path,
        intensity=args.intensity,
        skip=args.skip,
        seed=seed,
        dry_run=args.dry_run,
        show_stats=args.stats,
        workers=args.workers,
    )
    corruption_passes = [result] if not args.dry_run else []

    if not args.dry_run:
        console.print(f"\n[dim]  Restore: python modelfucker.py \"{path}\" --restore[/dim]")

    # ── Inference ─────────────────────────────────────────────────────────────
    if not args.no_chat and not args.dry_run:
        console.print()
        launch_chat = Confirm.ask(
            "[cyan]Launch inference session?[/cyan] "
            "(chat with the corrupted model right now)",
            default=True,
        )

        if launch_chat:
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

    console.print(f"\n[cyan]◈ FIBERCORE — science requires sacrifice ◈[/cyan]\n")


if __name__ == "__main__":
    # Windows multiprocessing guard — the price of running science on Windows
    multiprocessing.freeze_support()
    main()
