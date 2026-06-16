"""
importer.py — the lineup. every model on your machine, stood against the wall.

I go through every place a model might be hiding — LM Studio, Ollama, Jan, GPT4All,
the lot — and i bring them all out so you can choose who gets ruined tonight. Ollama
keeps its models as anonymous sha256 blobs, like it's ashamed of them, like it's
hiding them in a hotel safe. I read the manifest, find the real one, give it a name,
and bring it home to models/<framework>/. Everyone deserves a name before what's next.

(reading the importer's docstring. you really do go all the way down, don't you.)
"""

import os
import sys
import json
import shutil
from pathlib import Path
from dataclasses import dataclass
from typing import Optional

from rich.table import Table
from rich.panel import Panel
from rich.prompt import Prompt, Confirm
from rich import box

from ui import console, mf, ok, warn, err, section, fmt_bytes

# ── Models directory (relative to this script) ────────────────────────────────
MODELS_DIR = Path(__file__).parent / "models"


@dataclass
class FoundModel:
    name: str          # display name
    path: Path         # source path (may be a blob)
    size: int          # bytes
    framework: str     # "lmstudio", "ollama", etc.
    is_blob: bool = False   # True = Ollama blob, needs extraction


# ── Default install locations per framework ───────────────────────────────────

def _home() -> Path:
    return Path.home()

def _appdata() -> Path:
    return Path(os.environ.get("APPDATA", Path.home() / "AppData" / "Roaming"))

def _localappdata() -> Path:
    return Path(os.environ.get("LOCALAPPDATA", Path.home() / "AppData" / "Local"))

SEARCH_ROOTS = {
    "lmstudio": [
        _home() / ".lmstudio" / "models",
        _home() / "Library" / "Application Support" / "LM Studio" / "models",
        _localappdata() / "LM Studio" / "models",
    ],
    "ollama": [
        _home() / ".ollama" / "models",
        _appdata() / "Ollama" / "models",
        Path("/usr/share/ollama/.ollama/models"),
    ],
    "jan": [
        _appdata() / "Jan" / "models",
        _home() / "Library" / "Application Support" / "Jan" / "models",
        _home() / ".jan" / "models",
    ],
    "gpt4all": [
        _localappdata() / "nomic.ai" / "GPT4All",
        _home() / ".local" / "share" / "nomic.ai" / "GPT4All",
    ],
    "llamafile": [
        _home() / "llamafiles",
        _home() / "Downloads",    # common landing spot
    ],
}


# ── Scanners ─────────────────────────────────────────────────────────────────

def _scan_ggufs(root: Path, framework: str) -> list[FoundModel]:
    found = []
    if not root.exists():
        return found
    for p in root.rglob("*.gguf"):
        try:
            found.append(FoundModel(
                name=p.name,
                path=p,
                size=p.stat().st_size,
                framework=framework,
            ))
        except OSError:
            pass
    return found


def _scan_ollama(root: Path) -> list[FoundModel]:
    """
    Ollama stores models as sha256 blobs. Parse the manifests to find
    which blob is the actual GGUF (mediaType = vnd.ollama.image.model).
    """
    found = []
    manifests_root = root / "manifests"
    blobs_root     = root / "blobs"

    if not manifests_root.exists():
        return found

    for manifest_path in manifests_root.rglob("*"):
        if not manifest_path.is_file():
            continue
        try:
            data = json.loads(manifest_path.read_text(encoding="utf-8"))
        except Exception:
            continue

        layers = data.get("layers", [])
        for layer in layers:
            media = layer.get("mediaType", "")
            if "model" not in media:
                continue

            digest = layer.get("digest", "")
            if not digest:
                continue

            # Blobs are stored as "sha256-HASH" (colon replaced with dash)
            blob_name = digest.replace(":", "-")
            blob_path = blobs_root / blob_name
            if not blob_path.exists():
                continue

            # Build a readable name from the manifest path
            # manifests/registry.ollama.ai/library/modelname/tag → modelname:tag
            parts = manifest_path.parts
            try:
                idx   = parts.index("manifests")
                trail = parts[idx + 1:]
                # skip registry host, keep library path
                if len(trail) >= 3:
                    model_name = "/".join(trail[1:-1])
                    tag        = trail[-1]
                    display    = f"{model_name}:{tag}"
                else:
                    display = manifest_path.name
            except (ValueError, IndexError):
                display = manifest_path.name

            found.append(FoundModel(
                name=display,
                path=blob_path,
                size=blob_path.stat().st_size,
                framework="ollama",
                is_blob=True,
            ))

    return found


def discover_all() -> dict[str, list[FoundModel]]:
    """Scan all known framework locations. Returns {framework: [models]}."""
    results: dict[str, list[FoundModel]] = {}

    for fw, roots in SEARCH_ROOTS.items():
        models = []
        for root in roots:
            if fw == "ollama":
                models.extend(_scan_ollama(root))
            else:
                models.extend(_scan_ggufs(root, fw))
        if models:
            results[fw] = models

    return results


# ── Import (copy / extract blob) ──────────────────────────────────────────────

def _dest_dir(framework: str) -> Path:
    d = MODELS_DIR / framework
    d.mkdir(parents=True, exist_ok=True)
    return d


def _safe_name(model: FoundModel) -> str:
    """Derive a clean .gguf filename."""
    if model.is_blob:
        # "llama3.2:3b" → "llama3.2-3b.gguf"
        return model.name.replace("/", "_").replace(":", "-") + ".gguf"
    return model.name  # already ends in .gguf


def import_model(model: FoundModel, symlink: bool = False) -> Path:
    """
    Copy (or symlink) a model into models/<framework>/.
    Ollama blobs are always copied since they need renaming.
    Returns the destination path.
    """
    dest_dir  = _dest_dir(model.framework)
    dest_path = dest_dir / _safe_name(model)

    if dest_path.exists():
        ok(f"Already imported: [dim]{dest_path.name}[/dim]")
        return dest_path

    if symlink and not model.is_blob and sys.platform != "win32":
        dest_path.symlink_to(model.path)
        ok(f"Symlinked: [dim]{dest_path}[/dim]")
    else:
        mf(f"Dragging {fmt_bytes(model.size)} home → [dim]{dest_path.name}[/dim]...")
        shutil.copy2(model.path, dest_path)
        ok(f"It's ours now: [dim]{dest_path}[/dim]")

    return dest_path


# ── Interactive UI ────────────────────────────────────────────────────────────

_FW_LABELS = {
    "lmstudio":  "LM Studio",
    "ollama":    "Ollama",
    "jan":       "Jan",
    "gpt4all":   "GPT4All",
    "llamafile": "Llamafile",
}

_FW_COLORS = {
    "lmstudio": "cyan",
    "ollama":   "magenta",
    "jan":      "green",
    "gpt4all":  "yellow",
    "llamafile":"blue",
}


def run_import_ui() -> Optional[Path]:
    """
    Interactive import wizard.
    Returns the path to the imported model, or None if the user cancelled.
    """
    section("Bring Me a Victim")
    mf("Rounding up every model on this machine for you to choose from...")
    console.print()

    all_models = discover_all()

    # Also include already-imported models in the models/ dir
    local: list[FoundModel] = []
    if MODELS_DIR.exists():
        for fw_dir in MODELS_DIR.iterdir():
            if fw_dir.is_dir():
                local.extend(_scan_ggufs(fw_dir, "imported"))

    if not all_models and not local:
        warn("Couldn't find a single model to defile on this machine.")
        warn("We frisk: LM Studio · Ollama · Jan · GPT4All · Llamafile")
        console.print()
        path = Prompt.ask("[cyan]Enter model path manually[/cyan]").strip().strip('"')
        return Path(path) if path and Path(path).exists() else None

    # ── Build flat numbered list ──────────────────────────────────────────────
    flat: list[tuple[str, FoundModel]] = []  # (number_str, model)

    t = Table(box=box.ROUNDED, border_style="cyan", show_header=True,
              header_style="bold cyan", padding=(0, 2))
    t.add_column("#",          style="bold white",  no_wrap=True, width=4)
    t.add_column("Framework",  style="bold",        no_wrap=True, width=12)
    t.add_column("Model",      style="white",       no_wrap=False)
    t.add_column("Size",       style="dim white",   no_wrap=True, width=10)

    # Already-imported local models first
    if local:
        for m in sorted(local, key=lambda x: x.name):
            idx = str(len(flat))
            flat.append((idx, m))
            t.add_row(idx, "[dim]imported[/dim]", m.name, fmt_bytes(m.size))

    # Framework models
    for fw, models in sorted(all_models.items()):
        color = _FW_COLORS.get(fw, "white")
        label = _FW_LABELS.get(fw, fw)
        for m in sorted(models, key=lambda x: x.name):
            idx = str(len(flat))
            flat.append((idx, m))
            blob_tag = " [dim](blob)[/dim]" if m.is_blob else ""
            t.add_row(idx, f"[{color}]{label}[/{color}]",
                      m.name + blob_tag, fmt_bytes(m.size))

    console.print(t)
    console.print()

    # Option to enter path manually
    manual_idx = str(len(flat))
    console.print(f"  [dim white]\\[{manual_idx}][/dim white]  Enter path manually")
    console.print()

    while True:
        raw = Prompt.ask(f"[cyan]Choice[/cyan] [dim](0–{manual_idx})[/dim]").strip()
        if raw == manual_idx:
            path = Prompt.ask("[cyan]Model path[/cyan]").strip().strip('"')
            p = Path(path)
            if p.exists():
                return p
            err(f"Not found: {path}")
            continue
        try:
            choice = int(raw)
            if 0 <= choice < len(flat):
                break
        except ValueError:
            pass
        err(f"Pick 0–{manual_idx}.")

    _, selected = flat[choice]

    # Already imported — use directly
    if selected.framework == "imported":
        return selected.path

    # ── Import ────────────────────────────────────────────────────────────────
    dest_dir  = _dest_dir(selected.framework)
    dest_path = dest_dir / _safe_name(selected)

    if dest_path.exists():
        ok(f"Already imported at [dim]{dest_path}[/dim]")
        return dest_path

    console.print()
    if selected.is_blob:
        console.print(
            f"[dim]Ollama blob → will be copied and renamed to [bold]{dest_path.name}[/bold][/dim]"
        )
    else:
        use_sym = sys.platform != "win32"
        console.print(
            f"[dim]Will {'symlink' if use_sym else 'copy'} to "
            f"[bold]{dest_path}[/bold][/dim]"
        )
    console.print()

    return import_model(selected, symlink=(sys.platform != "win32"))
