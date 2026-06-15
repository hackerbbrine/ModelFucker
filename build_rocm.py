#!/usr/bin/env python3
"""
build_rocm.py — Build llama-cpp-python against the pip-installed ROCm SDK.

The AMD "rocm-sdk-devel" pip package ships the whole HIP toolchain (compiler,
hipblas/rocblas, CMake configs) inside site-packages. llama.cpp's build just
needs to be pointed at it. This figures out the paths and runs the build.
"""

import os
import sys
import subprocess


def find_rc() -> str:
    """Locate the Windows SDK resource compiler (rc.exe) — needed by Clang+Ninja."""
    import glob
    # Already on PATH?
    from shutil import which
    if which("rc"):
        return which("rc")
    if which("llvm-rc"):
        return which("llvm-rc")
    roots = [r"C:\Program Files (x86)\Windows Kits\10\bin",
             r"C:\Program Files\Windows Kits\10\bin"]
    hits = []
    for r in roots:
        hits += glob.glob(os.path.join(r, "**", "x64", "rc.exe"), recursive=True)
    return sorted(set(hits))[-1] if hits else ""


def rocm_root() -> str:
    out = subprocess.run([sys.executable, "-m", "rocm_sdk", "path", "--root"],
                         capture_output=True, text=True)
    root = out.stdout.strip()
    if not root or not os.path.isdir(root):
        print("[!] Could not locate the pip ROCm SDK. Is rocm-sdk-devel installed?")
        print("    pip install rocm[devel]")
        sys.exit(1)
    return root


def main():
    target = sys.argv[1] if len(sys.argv) > 1 else "gfx1201"
    root   = rocm_root()
    llvm   = os.path.join(root, "lib", "llvm", "bin")
    fs     = lambda p: p.replace("\\", "/")   # CMake wants forward slashes

    clang   = os.path.join(llvm, "clang.exe")
    clangpp = os.path.join(llvm, "clang++.exe")

    print(f"[*] ROCm root : {root}")
    print(f"[*] Compiler  : {clangpp}")
    print(f"[*] GPU target: {target}")

    # IMPORTANT: the user's path contains a space ("Tony Stark"). CMAKE_ARGS is
    # split on whitespace by the build backend, so anything with a space must go
    # through environment variables instead — those hold spaces just fine.
    #   CC / CXX     → C and C++ compilers
    #   HIPCXX       → CMake's HIP language compiler
    #   CMAKE_PREFIX_PATH → where find_package(hip/hipblas/rocblas) looks
    #   CMAKE_GENERATOR   → Ninja (required for HIP on Windows)
    cmake_args = " ".join([
        "-DGGML_HIP=ON",
        f"-DAMDGPU_TARGETS={target}",
    ])

    env = os.environ.copy()
    env["CMAKE_ARGS"]       = cmake_args
    env["CMAKE_GENERATOR"]  = "Ninja"
    env["CC"]               = clang
    env["CXX"]              = clangpp
    env["HIPCXX"]           = clangpp
    env["CMAKE_PREFIX_PATH"] = os.pathsep.join([root, os.path.join(root, "lib", "cmake")])
    env["HIP_PATH"]         = root
    env["ROCM_PATH"]        = root
    env["HIP_PLATFORM"]     = "amd"   # hip-config.cmake rejects an empty platform

    # clang can't auto-find the GPU device bitcode (ocml.bc etc.) in the pip SDK's
    # nonstandard layout. Point it there explicitly via the env var clang reads.
    bitcode = os.path.join(root, "lib", "llvm", "amdgcn", "bitcode")
    if os.path.isdir(bitcode):
        env["HIP_DEVICE_LIB_PATH"] = bitcode
        print(f"[*] Device libs: {bitcode}")

    # Clang+Ninja on Windows needs a resource compiler (rc.exe from the Win SDK)
    rc = find_rc()
    if rc:
        env["RC"] = rc
        print(f"[*] RC compiler: {rc}")
        rc_dir = os.path.dirname(rc)
    else:
        print("[!] No rc.exe found — install the Windows SDK if the build complains")
        rc_dir = ""

    env["PATH"] = os.pathsep.join([
        p for p in (os.path.join(root, "bin"), llvm, rc_dir, env.get("PATH", "")) if p
    ])

    print(f"[*] CMAKE_ARGS = {cmake_args}")
    print(f"[*] CC/CXX/HIPCXX via env (handles the space in your path)")
    print("[*] Building llama-cpp-python (5–15 min)...\n")

    r = subprocess.run(
        [sys.executable, "-m", "pip", "install", "llama-cpp-python",
         "--upgrade", "--force-reinstall", "--no-cache-dir", "--verbose"],
        env=env,
    )

    if r.returncode != 0:
        print("\n[!] Build failed. See errors above.")
        sys.exit(r.returncode)

    # Verify GPU offload actually compiled in
    check = subprocess.run(
        [sys.executable, "-c",
         "import llama_cpp; print(llama_cpp.llama_cpp.llama_supports_gpu_offload())"],
        capture_output=True, text=True,
    )
    if check.stdout.strip().lower() == "true":
        print("\n[OK] llama-cpp-python built with ROCm — GPU inference is live.")
    else:
        print("\n[!] Built, but GPU offload reports False. Something didn't link right.")
        sys.exit(1)


if __name__ == "__main__":
    main()
