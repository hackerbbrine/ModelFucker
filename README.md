# ModelFucker v3.0

```
╔═══════════════════════════════════════════════════════════════╗
║                                                               ║
║        M O D E L   F U C K E R   v 3 . 0                      ║
║                                                               ║
║        by Hackerbbrine                                        ║
║        "science requires sacrifice"                           ║
║           (I never said that)                                 ║
║                                                               ║
║                                                               ║
╚═══════════════════════════════════════════════════════════════╝
```

Corrupt GGUF model weights. Chat with the result. Submit the best outputs to the Hall of Fame.

Science requires sacrifice.

## What it does

1. **Corrupts** a `.gguf` model file by flipping random bits in the weight data
2. **Loads** the corrupted model via llama.cpp and drops you into a chat session
3. **Lets you go deeper** — run more corruption passes mid-chat with `/corrupt`
4. **Submits** the best outputs to the public Hall of Fame via GitHub PR

## Install

```bash
pip install rich numpy llama-cpp-python prompt_toolkit PyGithub requests
```

GPU build of llama-cpp-python (optional but fast):
```bash
pip install llama-cpp-python --extra-index-url https://abetlen.github.io/llama-cpp-python/whl/cu124
```

## Usage

```bash
# Corrupt and chat
python modelfucker.py model.gguf

# Specific intensity (lower = more chaos)
python modelfucker.py model.gguf --intensity 256 --stats

# Reproducible run
python modelfucker.py model.gguf --intensity 512 --seed 42

# Just corrupt, no chat
python modelfucker.py model.gguf --intensity 128 --no-chat

# Preview without writing
python modelfucker.py model.gguf --dry-run --stats

# Restore clean backup
python modelfucker.py model.gguf --restore
```

## Options

| Flag | Default | Description |
|------|---------|-------------|
| `--intensity N` | 1024 | Flip one bit every N bytes. Lower = more broken. |
| `--skip N` | 52428800 | Skip first N bytes (protects the GGUF header, default 50MB) |
| `--seed N` | random | RNG seed for reproducibility |
| `--workers N` | all cores | Multiprocessing workers (fallback if NumPy unavailable) |
| `--n-ctx N` | 2048 | Context length for inference |
| `--temp F` | 0.8 | Sampling temperature |
| `--max-tokens N` | 512 | Max tokens per response |
| `--no-chat` | — | Just corrupt, skip inference |
| `--restore` | — | Restore from `.clean` backup |
| `--stats` | — | Show detailed corruption statistics |
| `--dry-run` | — | Preview without writing anything |

## Intensity guide

| Intensity | Impact | Flips on 3GB model |
|-----------|--------|--------------------|
| 1024 | LIGHT | ~3.3M |
| 256 | MODERATE | ~13M |
| 64 | HEAVY | ~52M |
| 16 | CATASTROPHIC | ~210M |
| 1 | ??? | ~3.4B |

## Chat commands

Once inside the inference session:

| Command | Description |
|---------|-------------|
| `/corrupt [N]` | Run another corruption pass at intensity N |
| `/stats` | Show cumulative corruption stats |
| `/restore` | Restore clean backup and reload |
| `/submit` | Submit to Hall of Fame on GitHub |
| `/help` | Show commands |
| `/quit` | Exit |

## Hall of Fame

> See [HALL_OF_FAME.md](HALL_OF_FAME.md) for the best outputs the community has extracted from broken models.

Use `/submit` during a chat session to open a PR with your transcript.

## How it works

ModelFucker skips the GGUF file header (first 50MB by default) and flips random bits in the raw weight data. The model still loads — llama.cpp doesn't validate weights — but the neural network is now operating on corrupted math. Effects range from subtle personality drift to complete incoherence depending on intensity.

A `.clean` backup is created automatically before the first write. Use `--restore` to undo everything.

## Backends

- **GPU (CuPy)** — fastest, transfers weights to GPU for vectorized bit flipping
- **CPU (NumPy)** — vectorized, handles multi-GB files in seconds
- **Multiprocessing** — pure Python fallback, uses all CPU cores

## Requirements

- Python 3.10+
- A `.gguf` model file (any size, any architecture)
- A willingness to sacrifice science at the altar of chaos

---

*by Hackerbbrine*
