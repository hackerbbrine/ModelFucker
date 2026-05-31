#!/usr/bin/env python3
"""
ModelFucker v3.0 — Installer
Detects your GPU, picks the right build flags, installs everything.
Run this once before using modelfucker.py.
"""

import sys
import os
import subprocess
import platform

# ── Minimum Python version ────────────────────────────────────────────────────
if sys.version_info < (3, 10):
    print(f"[ERROR] Python 3.10+ required (you have {sys.version})")
    sys.exit(1)

# ── Helpers ───────────────────────────────────────────────────────────────────

def run(cmd: list, **kwargs) -> subprocess.CompletedProcess:
    try:
        return subprocess.run(cmd, capture_output=True, text=True, **kwargs)
    except FileNotFoundError:
        return subprocess.CompletedProcess(cmd, returncode=1, stdout="", stderr="")

def pip(*args):
    """Run pip install with the current interpreter."""
    return subprocess.run(
        [sys.executable, "-m", "pip", "install", *args],
        check=False,
    )

def header(text: str):
    print(f"\n{'─' * 60}")
    print(f"  {text}")
    print(f"{'─' * 60}")

def ok(text: str):   print(f"  ✓  {text}")
def info(text: str): print(f"  →  {text}")
def warn(text: str): print(f"  ⚠  {text}")
def err(text: str):  print(f"  ✗  {text}")


# ── GPU detection ─────────────────────────────────────────────────────────────

class GPU:
    kind:   str = "cpu"   # "nvidia" | "amd" | "cpu"
    name:   str = ""
    target: str = ""      # gfx target (AMD) or "" (NVIDIA/CPU)


def _is_gfx(s: str) -> bool:
    return s.lower().startswith("gfx") and len(s) >= 6


def _detect_amd_target() -> str:
    """Try several methods to get the ROCm gfx target string (e.g. gfx1201)."""

    # hipconfig --amdgputarget
    r = run(["hipconfig", "--amdgputarget"])
    if r.returncode == 0:
        for token in r.stdout.split():
            if _is_gfx(token):
                return token.lower()

    # rocminfo — scan for Name: gfxNNNN lines
    r = run(["rocminfo"])
    if r.returncode == 0:
        for line in r.stdout.splitlines():
            stripped = line.strip()
            if stripped.lower().startswith("name:"):
                val = stripped.split(":", 1)[-1].strip()
                if _is_gfx(val):
                    return val.lower()

    # PyTorch ROCm (already installed from a previous run)
    try:
        import torch
        if torch.cuda.is_available() and getattr(torch.version, "hip", None):
            props = torch.cuda.get_device_properties(0)
            arch  = getattr(props, "gcnArchName", "")
            if arch and _is_gfx(arch.split(":")[0]):
                return arch.split(":")[0].lower()
    except Exception:
        pass

    return ""


def _detect_amd_name() -> str:
    """Get a human-readable AMD GPU name."""
    try:
        import torch, os, contextlib
        with open(os.devnull, "w") as dn:
            old = os.dup(2); os.dup2(dn.fileno(), 2)
            try:
                avail = torch.cuda.is_available()
                name  = torch.cuda.get_device_name(0) if avail and getattr(torch.version, "hip", None) else ""
            finally:
                os.dup2(old, 2); os.close(old)
        if name:
            return name
    except Exception:
        pass

    r = run(["rocm-smi", "--showproductname"])
    if r.returncode == 0:
        for line in r.stdout.splitlines():
            if ":" in line:
                candidate = line.split(":", 1)[-1].strip()
                if candidate:
                    return candidate

    return "AMD GPU"


# Known RDNA/GCN architecture → gfx target map (for display only — hipconfig is authoritative)
_AMD_NAMES = {
    "9070":  "gfx1201",   # RDNA 4
    "9060":  "gfx1201",
    "7900":  "gfx1100",   # RDNA 3
    "7800":  "gfx1101",
    "7700":  "gfx1101",
    "7600":  "gfx1102",
    "6900":  "gfx1030",   # RDNA 2
    "6800":  "gfx1030",
    "6700":  "gfx1031",
    "6600":  "gfx1032",
}

def detect_gpu() -> GPU:
    g = GPU()

    # ── NVIDIA ────────────────────────────────────────────────────────────────
    r = run(["nvidia-smi", "--query-gpu=name", "--format=csv,noheader"])
    if r.returncode == 0 and r.stdout.strip():
        g.kind = "nvidia"
        g.name = r.stdout.strip().splitlines()[0].strip()
        return g

    # ── AMD ───────────────────────────────────────────────────────────────────
    # Try rocm-smi for the GPU name
    r = run(["rocm-smi", "--showproductname"])
    if r.returncode == 0 and r.stdout.strip():
        g.kind   = "amd"
        g.name   = _detect_amd_name()
        g.target = _detect_amd_target()
        return g

    # No rocm-smi — try hipconfig alone
    r = run(["hipconfig", "--version"])
    if r.returncode == 0:
        g.kind   = "amd"
        g.name   = _detect_amd_name()
        g.target = _detect_amd_target()
        return g

    return g   # cpu


# ── Base dependencies (no GPU flags needed) ───────────────────────────────────

BASE_DEPS = [
    "rich",
    "numpy",
    "prompt_toolkit",
    "requests",
    "PyGithub",
]


# ── PyTorch install URLs ──────────────────────────────────────────────────────

def torch_install_cmd(gpu: GPU) -> list:
    if gpu.kind == "nvidia":
        return [
            sys.executable, "-m", "pip", "install",
            "torch", "--index-url", "https://download.pytorch.org/whl/cu124",
        ]
    if gpu.kind == "amd":
        return [
            sys.executable, "-m", "pip", "install",
            "torch", "--index-url", "https://download.pytorch.org/whl/rocm6.2",
        ]
    return [sys.executable, "-m", "pip", "install", "torch"]


# ── llama-cpp-python build flags ──────────────────────────────────────────────

def llama_env(gpu: GPU) -> dict:
    env = os.environ.copy()
    if gpu.kind == "nvidia":
        env["CMAKE_ARGS"] = "-DGGML_CUDA=on"
    elif gpu.kind == "amd" and gpu.target:
        env["CMAKE_ARGS"] = f"-DGGML_HIPBLAS=on -DAMDGPU_TARGETS={gpu.target}"
    elif gpu.kind == "amd":
        env["CMAKE_ARGS"] = "-DGGML_HIPBLAS=on"
    return env


# ── Main ──────────────────────────────────────────────────────────────────────

def main():
    print()
    print("  ModelFucker v3.0 — Installer")
    print("  by Hackerbbrine")
    print()

    # ── Detect GPU ────────────────────────────────────────────────────────────
    header("Detecting GPU")
    gpu = detect_gpu()

    if gpu.kind == "nvidia":
        ok(f"NVIDIA GPU detected: {gpu.name}")
        ok("Will build llama-cpp-python with CUDA support")
        ok("Will install PyTorch CUDA")
    elif gpu.kind == "amd":
        ok(f"AMD GPU detected: {gpu.name}")
        if gpu.target:
            ok(f"GFX target: {gpu.target}")
        else:
            warn("Could not auto-detect GFX target — will build without -DAMDGPU_TARGETS")
            warn("If inference fails, run: hipconfig --amdgputarget  and set it manually")
        ok("Will build llama-cpp-python with ROCm/HIP support")
        ok("Will install PyTorch ROCm")
    else:
        warn("No GPU detected — installing CPU-only builds")
        warn("Corruption will use NumPy (slower), inference will use CPU")

    # ── Confirm ───────────────────────────────────────────────────────────────
    print()
    try:
        ans = input("  Proceed with installation? [Y/n] ").strip().lower()
    except KeyboardInterrupt:
        print("\n  Cancelled.")
        sys.exit(0)
    if ans not in ("", "y", "yes"):
        print("  Cancelled.")
        sys.exit(0)

    # ── Base deps ─────────────────────────────────────────────────────────────
    header("Installing base dependencies")
    for dep in BASE_DEPS:
        info(f"Installing {dep}...")
        r = pip(dep, "-q")
        if r.returncode == 0:
            ok(dep)
        else:
            warn(f"{dep} may have failed — continuing anyway")

    # ── PyTorch ───────────────────────────────────────────────────────────────
    header("Installing PyTorch")
    cmd = torch_install_cmd(gpu)
    info(f"Running: {' '.join(cmd[3:])}")
    result = subprocess.run(cmd, check=False)
    if result.returncode == 0:
        ok("PyTorch installed")
    else:
        warn("PyTorch install may have failed — inference GPU support might not work")

    # ── llama-cpp-python ──────────────────────────────────────────────────────
    header("Building llama-cpp-python (this takes 5–15 minutes)")
    if gpu.kind != "cpu":
        info(f"CMAKE_ARGS = {llama_env(gpu).get('CMAKE_ARGS', '')}")
    info("Building from source...")

    env = llama_env(gpu)
    result = subprocess.run(
        [sys.executable, "-m", "pip", "install",
         "llama-cpp-python", "--upgrade", "--force-reinstall", "--no-cache-dir"],
        env=env,
        check=False,
    )
    if result.returncode == 0:
        ok("llama-cpp-python built and installed")
        if gpu.kind != "cpu":
            ok("GPU inference support compiled in")
    else:
        err("llama-cpp-python build failed")
        if gpu.kind == "amd":
            print()
            print("  Possible fixes:")
            print("  1. Make sure ROCm is installed: https://rocm.docs.amd.com")
            print("  2. Make sure HIP SDK is in PATH")
            print(f"  3. Verify your GFX target: hipconfig --amdgputarget")
            print("  4. Try CPU-only: pip install llama-cpp-python")
        elif gpu.kind == "nvidia":
            print()
            print("  Possible fixes:")
            print("  1. Make sure CUDA toolkit is installed")
            print("  2. Try CPU-only: pip install llama-cpp-python")

    # ── Summary ───────────────────────────────────────────────────────────────
    header("Done")
    print()
    if gpu.kind == "nvidia":
        ok(f"Corruption backend: GPU · CUDA · {gpu.name}")
        ok("Inference backend:  GPU · CUDA")
    elif gpu.kind == "amd":
        ok(f"Corruption backend: GPU · ROCm · {gpu.name}")
        ok(f"Inference backend:  GPU · ROCm ({gpu.target or 'target auto-detected at runtime'})")
    else:
        ok("Corruption backend: CPU (NumPy)")
        ok("Inference backend:  CPU")

    print()
    print("  Run:  python modelfucker.py")
    print()


if __name__ == "__main__":
    main()
