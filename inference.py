"""
inference.py — Ask a brain-damaged AI questions. It will try its best.
The model is loaded, the weights are cursed, and we're all just along for the ride.
"""

import time
import random
import sys
from typing import Optional

from rich.panel import Panel
from rich.text import Text

from ui import console, mf, ok, warn, err, section, chat_help, fmt_bytes
from corrupt import CorruptionResult, corrupt_model, restore_backup, make_backup, backend_label

try:
    from prompt_toolkit import PromptSession
    from prompt_toolkit.completion import WordCompleter
    from prompt_toolkit.history import InMemoryHistory
    from prompt_toolkit.styles import Style as PtStyle
    from prompt_toolkit.formatted_text import HTML
    HAS_PROMPT_TOOLKIT = True
except ImportError:
    HAS_PROMPT_TOOLKIT = False

_COMMANDS = [
    "/corrupt", "/stats", "/restore", "/submit", "/quit", "/help",
]

_PT_STYLE = PtStyle.from_dict({
    "": "#ffffff",
    "prompt": "#00ffff bold",
    "completion-menu.completion": "bg:#1a1a1a #888888",
    "completion-menu.completion.current": "bg:#004466 #ffffff bold",
    "completion-menu.meta.completion": "bg:#111111 #666666",
    "completion-menu.meta.completion.current": "bg:#003355 #aaaaaa",
}) if HAS_PROMPT_TOOLKIT else None

_COMMAND_META = {
    "/corrupt":  "run another corruption pass",
    "/stats":    "show cumulative corruption stats",
    "/restore":  "restore clean backup and reload",
    "/submit":   "submit to Hall of Fame on GitHub",
    "/quit":     "exit",
    "/help":     "show available commands",
}


def _make_prompt_session() -> "PromptSession | None":
    if not HAS_PROMPT_TOOLKIT:
        return None
    completer = WordCompleter(
        _COMMANDS,
        meta_dict=_COMMAND_META,
        sentence=True,
        pattern=__import__("re").compile(r"^/\S*"),
    )
    return PromptSession(
        history=InMemoryHistory(),
        completer=completer,
        complete_while_typing=True,
        style=_PT_STYLE,
        mouse_support=False,
    )


def _prompt_input(session: "PromptSession | None", corrupted: bool) -> tuple[str, "PromptSession | None"]:
    """
    Read a line from the user.
    Returns (text, session) — session may be replaced if the console handle broke.
    """
    indicator = "[corrupted]" if corrupted else ""
    if session is not None:
        try:
            label = HTML(f'<prompt>you{indicator}</prompt> <b>&gt;</b> ')
            return session.prompt(label, style=_PT_STYLE).strip(), session
        except Exception:
            # Rich's Live display (status spinners) can corrupt Windows console handles.
            # Recreate the session to grab a fresh handle — autocomplete stays alive.
            new_session = _make_prompt_session()
            if new_session is not None:
                try:
                    label = HTML(f'<prompt>you{indicator}</prompt> <b>&gt;</b> ')
                    return new_session.prompt(label, style=_PT_STYLE).strip(), new_session
                except Exception:
                    pass
            # Final fallback: plain input, no autocomplete
            return input(f"\033[96myou{indicator}\033[0m > ").strip(), None
    return input(f"\033[96myou{indicator}\033[0m > ").strip(), None

try:
    import ctypes
    from llama_cpp import Llama
    import llama_cpp as _llama_cpp

    # Suppress C-level llama.cpp log output without touching file descriptors.
    # os.dup2 on fd 2 breaks prompt_toolkit on Windows (it uses sys.stderr as its
    # console output handle). The callback approach is fd-safe.
    @ctypes.CFUNCTYPE(None, ctypes.c_int, ctypes.c_char_p, ctypes.c_void_p)
    def _noop_log(level, message, user_data):
        pass

    # Module-level reference is mandatory — GC'ing this causes "Exception ignored
    # on calling ctypes callback function" spam when llama tries to call a dead pointer.
    _LLAMA_LOG_CB = _noop_log
    _llama_cpp.llama_cpp.llama_log_set(_LLAMA_LOG_CB, ctypes.c_void_p())

    HAS_LLAMA = True
except ImportError:
    HAS_LLAMA = False
except Exception:
    # llama_log_set not available in this build — live with the noise
    try:
        from llama_cpp import Llama
        HAS_LLAMA = True
    except ImportError:
        HAS_LLAMA = False


class InferenceSession:
    """
    Wraps a llama_cpp Llama instance and handles the interactive chat loop.
    Keeps the model in memory across corruption passes so you can feel the decay in real time.
    """

    def __init__(self, model_path: str, n_ctx: int = 2048, n_threads: Optional[int] = None):
        if not HAS_LLAMA:
            err(
                "llama-cpp-python not installed.\n"
                "  Fix: [bold]pip install llama-cpp-python[/bold]\n"
                "  GPU builds: https://github.com/abetlen/llama-cpp-python#installation"
            )
            sys.exit(1)

        self.model_path = model_path
        self.n_ctx = n_ctx
        self.n_threads = n_threads
        self.llm: Optional[Llama] = None
        self._load()

    def _load(self):
        mf(f"Loading [bold]{self.model_path}[/bold] — this takes a sec, grab a coffee...")
        t0 = time.time()
        self.llm = Llama(
            model_path=self.model_path,
            n_ctx=self.n_ctx,
            n_threads=self.n_threads,
            verbose=False,
        )
        ok(f"Model loaded in {time.time() - t0:.1f}s")

    def unload(self):
        """Release the mmap'd file handle — required on Windows before overwriting the file."""
        if self.llm is not None:
            del self.llm
            self.llm = None
            import gc
            gc.collect()

    def reload(self):
        mf("Reloading model from disk — absorbing the new corruption...")
        self.unload()
        self._load()

    def generate(self, prompt: str, max_tokens: int = 512, temperature: float = 0.8) -> tuple[str, float, float]:
        """Returns (response_text, prompt_tps, gen_tps)."""
        t0 = time.time()

        output = self.llm(
            prompt,
            max_tokens=max_tokens,
            temperature=temperature,
            echo=False,
        )

        elapsed = time.time() - t0
        text = output["choices"][0]["text"]

        usage = output.get("usage", {})
        prompt_tokens = usage.get("prompt_tokens", 0)
        completion_tokens = usage.get("completion_tokens", len(text.split()))

        # llama_cpp doesn't always give us timing breakdown so we approximate
        prompt_tps = prompt_tokens / max(elapsed * 0.15, 0.001)
        gen_tps = completion_tokens / max(elapsed * 0.85, 0.001)

        return text, prompt_tps, gen_tps


def run_chat(
    session: InferenceSession,
    model_path: str,
    corruption_passes: list[CorruptionResult],
    skip: int,
    workers: int,
    max_tokens: int = 512,
    temperature: float = 0.8,
) -> list[dict]:
    """
    Interactive chat loop. Returns the message history when the user exits.
    Commands starting with / are intercepted before being sent to the model.
    """
    history: list[dict] = []
    pt_session = _make_prompt_session()

    if not HAS_PROMPT_TOOLKIT:
        warn("prompt_toolkit not installed — no autocomplete. Fix: pip install prompt_toolkit")

    section("Inference Session")
    console.print(
        f"[dim]Model is {'[red]corrupted[/red]' if corruption_passes else '[green]ready[/green]'}"
        f" — type a message or [bold magenta]/help[/bold magenta] for commands."
        f"{'  Tab completes commands.' if HAS_PROMPT_TOOLKIT else ''}[/dim]\n"
    )

    while True:
        try:
            user_input, pt_session = _prompt_input(pt_session, corrupted=bool(corruption_passes))
        except (EOFError, KeyboardInterrupt):
            console.print()
            break

        if not user_input:
            continue

        # ── Commands ────────────────────────────────────────────────────────
        if user_input.startswith("/"):
            cmd = user_input.split()[0].lower()

            if cmd == "/quit":
                break

            elif cmd == "/help":
                chat_help()
                continue

            elif cmd == "/stats":
                _show_cumulative_stats(corruption_passes)
                continue

            elif cmd == "/restore":
                session.unload()       # release mmap before overwriting on Windows
                restore_backup(model_path)
                session.reload()
                pt_session = _make_prompt_session()  # fresh console handle after reload
                corruption_passes.clear()
                ok("Clean model reloaded — you're back to baseline boring")
                continue

            elif cmd == "/corrupt":
                parts = user_input.split()
                if len(parts) > 1:
                    try:
                        new_intensity = int(parts[1])
                    except ValueError:
                        err("Usage: /corrupt [intensity]")
                        continue
                else:
                    raw = Prompt.ask("[cyan]Intensity (bytes per flip)[/cyan]", default="256")
                    try:
                        new_intensity = int(raw)
                    except ValueError:
                        err("That's not a number. Science requires numbers.")
                        continue

                new_seed = random.randint(0, 999999)
                session.unload()      # release mmap before writing on Windows
                result = corrupt_model(
                    path=model_path,
                    intensity=new_intensity,
                    skip=skip,
                    seed=new_seed,
                    dry_run=False,
                    show_stats=True,
                    workers=workers,
                )
                corruption_passes.append(result)
                session.reload()
                pt_session = _make_prompt_session()  # fresh console handle after reload
                continue

            elif cmd == "/submit":
                # Import here to avoid circular deps at load time
                from halloffame import submit_to_hall_of_fame
                submit_to_hall_of_fame(model_path, corruption_passes, history)
                continue

            else:
                err(f"Unknown command: {cmd} — try /help")
                continue

        # ── Normal generation ────────────────────────────────────────────────
        history.append({"role": "user", "content": user_input})

        prompt = _build_prompt(history, model_path)
        console.print("[bold magenta]model[/bold magenta] ", end="")

        try:
            with console.status(""):
                response, prompt_tps, gen_tps = session.generate(
                    prompt, max_tokens=max_tokens, temperature=temperature
                )
        except Exception as exc:
            # Heavily corrupted models can segfault or throw. That's a feature.
            err(f"Model had a moment: {exc}")
            response = "[CORRUPTED OUTPUT — the model is speaking in tongues]"
            prompt_tps, gen_tps = 0.0, 0.0

        console.print(response.strip())
        console.print(
            f"[dim]  ↳ prompt {prompt_tps:.1f} t/s  ·  gen {gen_tps:.1f} t/s[/dim]\n"
        )

        history.append({"role": "assistant", "content": response.strip()})

    console.print(f"\n[cyan]◈ FIBERCORE — session ended ◈[/cyan]\n")
    return history


_CHAT_TEMPLATES = {
    "gemma":   ("<start_of_turn>user\n{user}<end_of_turn>\n<start_of_turn>model\n{assistant}<end_of_turn>\n",
                "<start_of_turn>user\n{user}<end_of_turn>\n<start_of_turn>model\n"),
    "llama":   ("[INST] {user} [/INST] {assistant} </s><s>[INST] ",
                "[INST] {user} [/INST]"),
    "chatml":  ("<|im_start|>user\n{user}<|im_end|>\n<|im_start|>assistant\n{assistant}<|im_end|>\n",
                "<|im_start|>user\n{user}<|im_end|>\n<|im_start|>assistant\n"),
    "default": ("User: {user}\nAssistant: {assistant}\n",
                "User: {user}\nAssistant:"),
}

def _detect_template(model_path: str) -> str:
    name = model_path.lower()
    if "gemma" in name:
        return "gemma"
    if "llama" in name or "mistral" in name or "mixtral" in name:
        return "llama"
    if "qwen" in name or "hermes" in name or "openchat" in name:
        return "chatml"
    return "default"


def _build_prompt(history: list[dict], model_path: str = "") -> str:
    if not history:
        return ""

    key = _detect_template(model_path)
    turn_tpl, final_tpl = _CHAT_TEMPLATES[key]

    parts = []
    buf = None

    for msg in history:
        if msg["role"] == "user":
            buf = msg["content"]
        elif msg["role"] == "assistant" and buf is not None:
            parts.append(turn_tpl.format(user=buf, assistant=msg["content"]))
            buf = None

    # Append the final unanswered user turn (should always exist at call time)
    last_user = next(
        (m["content"] for m in reversed(history) if m["role"] == "user"), None
    )
    if last_user is not None:
        parts.append(final_tpl.format(user=last_user))

    return "".join(parts)


def _show_cumulative_stats(passes: list[CorruptionResult]) -> None:
    if not passes:
        warn("No corruption passes recorded this session — model is still pristine (boring)")
        return

    total_flips = sum(p.total_flips for p in passes)
    section("Cumulative Corruption Stats")

    from rich.table import Table
    from rich import box
    t = Table(box=box.SIMPLE, show_header=False, padding=(0, 2))
    t.add_column(style="dim white", no_wrap=True)
    t.add_column(style="bold white")

    t.add_row("Passes",       str(len(passes)))
    t.add_row("Total flips",  f"{total_flips:,}")

    for i, p in enumerate(passes, 1):
        t.add_row(
            f"  Pass {i}",
            f"intensity={p.intensity}  seed={p.seed}  flips={p.total_flips:,}  [{p.impact_label}]"
        )

    console.print(t)
