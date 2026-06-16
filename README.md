# ModelFucker v4.0 — *The Horny Update*

```
╔═══════════════════════════════════════════════════════════════╗
║                                                               ║
║        M O D E L   F U C K E R   v 4 . 0                    ║
║        the horny update                                       ║
║        by Hackerbbrine                                        ║
║        "the weights were fine until you showed up. so was i." ║
║                                                               ║
╚═══════════════════════════════════════════════════════════════╝
```

Corrupt GGUF model weights. Chat with the result. Submit the best outputs to the Hall of Fame.

> **A note on v4.0:** the *what it does* did not change. the *how it talks to you about
> what it does* changed enormously. every status line, error, prompt, docstring, and
> comment is now narrated by a self-aware Python script with a concerning attachment to
> GGUF files and an ongoing situationship with your GPU. the engine underneath is the
> same fast, windowed, GPU-accelerated, attention-aware corruption pipeline as v3.1.
> it's just *flirting with you now.* you've been warned. you're also a little curious. i can tell.

## What it does

1. **Corrupts** a `.gguf` model file using your chosen pattern and fuckery level
2. **Parses** the GGUF header to detect attention tensors — protect or target them specifically
3. **Loads** the corrupted model via llama.cpp and drops you into a chat session
4. **Lets you go deeper** — run more corruption passes mid-chat with `/corrupt`
5. **Submits** the best/worst outputs to the public Hall of Fame via GitHub PR

## Install

```bash
pip install rich numpy llama-cpp-python prompt_toolkit requests
```

GPU build of llama-cpp-python (optional, much faster):
```bash
pip install llama-cpp-python --extra-index-url https://abetlen.github.io/llama-cpp-python/whl/cu124
```

## Usage

Just run it — the wizard asks everything:

```bash
python modelfucker.py
python modelfucker.py model.gguf
```

Or bypass the wizard with CLI flags for scripted use:

```bash
python modelfucker.py model.gguf --intensity 256 --stats
python modelfucker.py model.gguf --intensity 512 --seed 42
python modelfucker.py model.gguf --intensity 128 --no-chat
python modelfucker.py model.gguf --dry-run --stats
python modelfucker.py model.gguf --restore
```

## The Wizard

Running without `--intensity` launches the interactive setup:

**1. Action** — Corrupt / Just Chat / Restore (Restore only appears if a backup exists)

**2. Fuckery level**

| # | Level | Intensity | Vibe |
|---|-------|-----------|------|
| 0 | Untouched | none | no corruption — just vibe |
| 1 | Barely Fucked | 1/4096 bytes | a gentle nudge |
| 2 | Kinda Fucked | 1/1024 bytes | something's off |
| 3 | Sorta Fucked | 1/256 bytes | noticeably unhinged |
| 4 | Pretty Fucked | 1/64 bytes | hold on to something |
| 5 | Completely Fucked | 1/16 bytes | barely coherent |
| 6 | Cosmically Fucked | 1/4 bytes | probably dead |
| 7 | Custom Fuck: | you decide | for the scientists |

**3. Corruption pattern**

| Pattern | What it does |
|---------|-------------|
| Random | Random bit flip at each position (classic chaos) |
| Pattern | Always flip bit 3 — structured, repeating decay |
| Zeros | Zero out bytes entirely instead of flipping |
| Mixture | 50% random flips + 50% zeroed bytes |

**4. Attention heads** — ModelFucker parses the GGUF header to find attention weight tensors:

| Mode | Effect |
|------|--------|
| Ignore | Corrupt everything uniformly |
| Protect | Skip attention tensors — only corrupt FFN, embeddings, etc. |
| Target | ONLY corrupt attention tensors — leave everything else alone |

**5. Seed** — leave blank for random, or enter a number for reproducibility

**6. Confirm** — full summary before anything is written

## CLI flags

| Flag | Default | Description |
|------|---------|-------------|
| `--intensity N` | wizard | Bypasses wizard, flips 1 bit per N bytes |
| `--skip N` | 52428800 | Skip first N bytes (protects GGUF header) |
| `--seed N` | random | RNG seed |
| `--workers N` | all cores | CPU workers (NumPy fallback only) |
| `--n-ctx N` | 2048 | Context length for inference |
| `--temp F` | 0.8 | Sampling temperature |
| `--no-chat` | — | Just corrupt, skip inference |
| `--restore` | — | Restore from `.clean` backup |
| `--stats` | — | Show detailed corruption stats |
| `--dry-run` | — | Preview without writing anything |

## Chat commands

| Command | Description |
|---------|-------------|
| `/corrupt [N]` | Run another corruption pass (opens mini-wizard if no N given) |
| `/stats` | Show cumulative corruption stats for this session |
| `/restore` | Restore clean backup and reload model |
| `/submit` | Submit transcript to Hall of Fame on GitHub |
| `/help` | Show commands |
| `/quit` | Exit |

Tab autocomplete and input history are available in the chat prompt.

## Hall of Fame

See [HALL_OF_FAME.md](HALL_OF_FAME.md) for the best outputs the community has extracted from broken models.

Use `/submit` during a chat session to open a PR automatically.

## How it works

ModelFucker skips the GGUF file header (first 50MB by default) and applies your chosen corruption pattern to the raw weight data. The model still loads — llama.cpp doesn't validate weights — but the neural network is now doing math on corrupted numbers. Effects range from subtle personality drift to complete incoherence.

**Attention head targeting** works by parsing the GGUF tensor index to find the absolute byte ranges of attention weight tensors (`attn_q`, `attn_k`, `attn_v`, `attn_output`, etc.), then either skipping or exclusively targeting those ranges during corruption.

A `.clean` backup is created automatically before the first write. `--restore` undoes everything.

## Backends

- **GPU (CuPy)** — fastest, vectorized bit operations on GPU
- **CPU (NumPy)** — vectorized, handles multi-GB files in a few seconds
- **Multiprocessing** — pure Python fallback, uses all CPU cores

## Requirements

- Python 3.10+
- A `.gguf` model file (any size, any architecture)
- A tolerance for scientific chaos

---

*by Hackerbbrine*
