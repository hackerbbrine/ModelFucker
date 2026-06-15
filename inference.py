"""
inference.py — Ask a brain-damaged AI questions. It will try its best.
The model is loaded, the weights are fucked, and we're all just along for the ride.
"""

import time
import random
import sys
from typing import Optional

from rich.panel import Panel
from rich.text import Text
from rich.prompt import Prompt

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
    try:
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
    except Exception:
        return None  # console handle broken — _prompt_input falls back to input()


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


def _save_win32_console() -> dict:
    """Save stdin/stdout/stderr console modes before llama.cpp touches them."""
    state = {}
    if sys.platform != "win32":
        return state
    try:
        import ctypes
        k32 = ctypes.windll.kernel32
        for name, handle_id in [("stdin", -10), ("stdout", -11), ("stderr", -12)]:
            h = k32.GetStdHandle(handle_id)
            mode = ctypes.c_ulong(0)
            if h and h != -1 and k32.GetConsoleMode(h, ctypes.byref(mode)):
                state[name] = (k32, h, mode.value)
    except Exception:
        pass
    return state


def _restore_win32_console(state: dict) -> None:
    """Restore console modes saved by _save_win32_console."""
    for name, (k32, h, mode) in state.items():
        try:
            k32.SetConsoleMode(h, mode)
        except Exception:
            pass


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

        self.model_path   = model_path
        self.n_ctx        = n_ctx
        self.n_threads    = n_threads
        self.llm: Optional[Llama] = None
        self.template_key, self.stop_tokens, self.use_chat_api = _detect_template(model_path)
        self._load()

    def _load(self):
        from corrupt import _GPU
        mf(f"Waking up [bold]{self.model_path}[/bold] — give it a sec to realize what's happening...")
        t0 = time.time()

        use_gpu_layers = _GPU.backend != "cpu"
        gpu_loaded     = False

        # Check if llama-cpp-python was actually compiled with GPU support.
        # n_gpu_layers=-1 is silently ignored when GPU offload wasn't compiled in —
        # this is the only reliable way to detect that before wasting time loading.
        try:
            import llama_cpp as _lc
            llama_has_gpu = _lc.llama_cpp.llama_supports_gpu_offload()
        except Exception:
            llama_has_gpu = False

        _console_state = _save_win32_console()
        try:
            if use_gpu_layers and llama_has_gpu:
                try:
                    self.llm = Llama(
                        model_path=self.model_path,
                        n_ctx=self.n_ctx,
                        n_threads=self.n_threads,
                        n_gpu_layers=-1,
                        verbose=False,
                    )
                    gpu_loaded = True
                except Exception as e:
                    warn(f"GPU load failed: [dim]{str(e).splitlines()[0][:100]}[/dim]")
                    self.llm = Llama(
                        model_path=self.model_path,
                        n_ctx=self.n_ctx,
                        n_threads=self.n_threads,
                        verbose=False,
                    )
            else:
                self.llm = Llama(
                    model_path=self.model_path,
                    n_ctx=self.n_ctx,
                    n_threads=self.n_threads,
                    verbose=False,
                )
        finally:
            _restore_win32_console(_console_state)

        elapsed = time.time() - t0
        if gpu_loaded:
            ok(f"Model loaded in {elapsed:.1f}s — [green]GPU inference active[/green]")
        else:
            ok(f"Model loaded in {elapsed:.1f}s — [yellow]CPU inference[/yellow]")
            if use_gpu_layers and not llama_has_gpu:
                warn(
                    "llama-cpp-python compiled without GPU support — inference is on CPU\n"
                    "  Fix: [bold]CMAKE_ARGS=\"-DGGML_VULKAN=ON\" pip install llama-cpp-python --upgrade --force-reinstall --no-cache-dir[/bold]"
                )

    def unload(self):
        """Release the mmap'd file handle — required on Windows before overwriting the file."""
        if self.llm is not None:
            del self.llm
            self.llm = None
            import gc
            gc.collect()

    def reload(self):
        mf("Reloading from disk — letting it soak up everything you just did to it...")
        self.unload()
        self._load()

    def generate_chat(
        self,
        history: list[dict],
        max_tokens: int = 2048,
        temperature: float = 0.8,
    ) -> tuple[str, float, float]:
        """
        Generate using create_chat_completion — lets llama.cpp apply the model's
        own built-in chat template. Most accurate path.
        """
        t0 = time.time()
        tokens: list[str] = []
        total_tokens = 0

        for chunk in self.llm.create_chat_completion(
            messages=history,
            max_tokens=max_tokens,
            temperature=temperature,
            stream=True,
            stop=self.stop_tokens,
        ):
            delta   = chunk["choices"][0].get("delta", {})
            content = delta.get("content", "")
            if not content:
                continue
            tokens.append(content)
            total_tokens += 1
            if total_tokens >= 64 and _is_repeating(tokens):
                break

        text = "".join(tokens)
        if self.stop_tokens:
            for st in self.stop_tokens:
                text = text.replace(st, "")

        elapsed    = time.time() - t0
        prompt_tps = sum(len(m["content"].split()) for m in history) / max(elapsed * 0.15, 0.001)
        gen_tps    = total_tokens / max(elapsed * 0.85, 0.001)
        return text, prompt_tps, gen_tps

    def generate_raw(
        self,
        prompt: str,
        max_tokens: int = 2048,
        temperature: float = 0.8,
    ) -> tuple[str, float, float]:
        """
        Generate from a raw pre-formatted prompt string.
        Fallback when the model has no embedded chat template.
        """
        t0 = time.time()
        tokens: list[str] = []
        total_tokens = 0

        for chunk in self.llm(
            prompt,
            max_tokens=max_tokens,
            temperature=temperature,
            echo=False,
            stream=True,
            stop=self.stop_tokens,
        ):
            token = chunk["choices"][0]["text"]
            tokens.append(token)
            total_tokens += 1
            if total_tokens >= 64 and _is_repeating(tokens):
                break

        text = "".join(tokens)
        if self.stop_tokens:
            for st in self.stop_tokens:
                text = text.replace(st, "")

        elapsed    = time.time() - t0
        prompt_tps = len(prompt.split()) / max(elapsed * 0.15, 0.001)
        gen_tps    = total_tokens / max(elapsed * 0.85, 0.001)
        return text, prompt_tps, gen_tps


def _is_repeating(tokens: list[str], window: int = 50, threshold: float = 0.85) -> bool:
    """
    Returns True if the recent output is stuck in a loop.
    Compares the last `window` tokens against the window before it —
    if they're too similar the model is just spinning its wheels.
    """
    if len(tokens) < window * 2:
        return False
    recent = "".join(tokens[-window:])
    before = "".join(tokens[-window * 2:-window])
    if not before:
        return False
    # Character-level overlap ratio
    matches = sum(a == b for a, b in zip(recent, before))
    ratio = matches / max(len(recent), len(before))
    return ratio >= threshold


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

    section("Pillow Talk")
    console.print(
        f"[dim]Model is {'[red]thoroughly ruined[/red]' if corruption_passes else '[green]pure and untouched[/green]'}"
        f" — say something to it, or [bold magenta]/help[/bold magenta] for what you can do to it."
        f"{'  Tab finishes your commands.' if HAS_PROMPT_TOOLKIT else ''}[/dim]\n"
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
                from corrupt import CorruptPattern, AttentionMode
                from wizard import pick_fuckery_level, pick_pattern, pick_attention_mode, pick_seed

                parts = user_input.split()
                if len(parts) > 1:
                    try:
                        new_intensity = int(parts[1])
                        new_pattern   = CorruptPattern.RANDOM
                        new_attn_mode = AttentionMode.IGNORE
                        new_attn_ranges = []
                        new_seed = random.randint(0, 999_999)
                    except ValueError:
                        err("Usage: /corrupt [intensity]")
                        continue
                else:
                    # Mini wizard for in-chat corruption
                    new_intensity   = pick_fuckery_level()
                    if new_intensity is None:
                        warn("No corruption selected.")
                        continue
                    new_pattern     = pick_pattern()
                    new_attn_mode, new_attn_ranges = pick_attention_mode(model_path)
                    new_seed        = pick_seed()

                session.unload()
                result = corrupt_model(
                    path=model_path,
                    intensity=new_intensity,
                    skip=skip,
                    seed=new_seed,
                    dry_run=False,
                    show_stats=True,
                    workers=workers,
                    pattern=new_pattern,
                    attention_mode=new_attn_mode,
                    attention_ranges=new_attn_ranges,
                )
                corruption_passes.append(result)
                session.reload()
                pt_session = _make_prompt_session()
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
        console.print("[bold magenta]model[/bold magenta] ", end="")

        try:
            with console.status(""):
                if session.use_chat_api:
                    response, prompt_tps, gen_tps = session.generate_chat(
                        history, max_tokens=max_tokens, temperature=temperature,
                    )
                else:
                    prompt = _build_prompt(history, model_path, session.template_key)
                    response, prompt_tps, gen_tps = session.generate_raw(
                        prompt, max_tokens=max_tokens, temperature=temperature,
                    )
        except Exception as exc:
            # Heavily corrupted models can segfault or throw. That's foreplay.
            err(f"The model just went limp on us: {exc}")
            response = "[the model is babbling incoherently and possibly drooling]"
            prompt_tps, gen_tps = 0.0, 0.0

        console.print(response.strip())
        console.print(
            f"[dim]  ↳ prompt {prompt_tps:.1f} t/s  ·  gen {gen_tps:.1f} t/s[/dim]\n"
        )

        history.append({"role": "assistant", "content": response.strip()})

    console.print(f"\n[cyan]◈ Hackerbbrine — thanks for coming ◈[/cyan]\n")
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

_STOP_TOKENS = {
    "gemma":    ["<end_of_turn>", "<start_of_turn>"],  # Gemma 1/2/3
    "gemma4":   ["<turn|>", "<|turn>"],                 # Gemma 4
    "llama":    ["</s>", "[INST]"],
    "llama3":   ["<|eot_id|>", "<|start_header_id|>"],  # Llama 3+
    "chatml":   ["<|im_end|>", "<|im_start|>"],
    "default":  ["\nUser:", "\nAssistant:"],
}

def _detect_template(model_path: str) -> tuple:
    """
    Detect the chat template to use. Returns (template_key, stop_tokens, use_chat_api).
    use_chat_api=True means the model has its own embedded template and we should
    use create_chat_completion; False means we fall back to manual prompt building.

    Detection order (most → least authoritative):
      1. tokenizer.chat_template in GGUF header (Jinja source — most accurate)
      2. general.architecture in GGUF header
      3. Filename pattern matching (last resort)
    """
    mf("Detecting chat template...")

    # ── 1. tokenizer.chat_template (the actual Jinja source) ─────────────────
    try:
        from gguf_parser import try_parse
        info = try_parse(model_path)

        if info is None:
            warn("Could not parse GGUF header — falling back to filename detection")
        else:
            jinja = info.metadata.get("tokenizer.chat_template", "")
            arch  = str(info.metadata.get("general.architecture", "")).lower()

            if jinja:
                # Pattern-match the Jinja source to identify the format
                key = _match_jinja_template(jinja)
                if key:
                    ok(f"Found [bold]tokenizer.chat_template[/bold] in header → [cyan]{key}[/cyan] format")
                    ok("Using model's built-in template (most accurate)")
                    return key, _STOP_TOKENS.get(key, []), True
                else:
                    warn(
                        "Found tokenizer.chat_template but couldn't identify format\n"
                        "  [dim]Outputs may include raw template tokens — this is a known limitation[/dim]"
                    )
                    # Still use the chat API — it'll apply the template even if we can't name it
                    ok("Using model's built-in template (format unknown but applied automatically)")
                    return "default", [], True

            # ── 2. general.architecture ───────────────────────────────────────
            if arch:
                key = _arch_to_template(arch)
                if key:
                    warn(
                        f"No chat template in header — using [bold]general.architecture[/bold]: "
                        f"[cyan]{arch}[/cyan] → [cyan]{key}[/cyan]\n"
                        "  [dim]Outputs may look slightly off if the fine-tune used a different format[/dim]"
                    )
                    return key, _STOP_TOKENS.get(key, []), False
                else:
                    warn(
                        f"Unknown architecture [cyan]{arch}[/cyan] — no matching template\n"
                        "  [dim]Using generic format. Expect raw stop tokens and formatting weirdness.[/dim]"
                    )
                    return "default", [], False
            else:
                warn("No architecture info in GGUF header")

    except Exception as exc:
        warn(f"Header parsing failed ({exc})")

    # ── 3. Filename guessing ──────────────────────────────────────────────────
    name = model_path.lower()
    key  = None
    if "gemma"   in name:                                    key = "gemma"
    elif "llama" in name or "mistral" in name or "mixtral" in name: key = "llama"
    elif "qwen"  in name or "hermes"  in name or "openchat" in name: key = "chatml"

    if key:
        warn(
            f"Guessing template from filename → [cyan]{key}[/cyan]\n"
            "  [dim]This is a last resort. Rename your model or fix its GGUF metadata for better results.[/dim]"
        )
        return key, _STOP_TOKENS.get(key, []), False

    warn(
        "Could not detect chat template from header or filename\n"
        "  [dim]Using generic User/Assistant format. Outputs will likely look wrong.[/dim]"
    )
    return "default", [], False


def _match_jinja_template(jinja: str) -> Optional[str]:
    """Identify a known template format from its Jinja source by scanning for marker tokens."""
    j = jinja.lower()
    # Gemma 4 uses <|turn> / <turn|>
    if "<|turn>" in j or "<turn|>" in j:
        return "gemma4"
    # Gemma 1/2/3
    if "<end_of_turn>" in j or "start_of_turn" in j:
        return "gemma"
    # Llama 3+
    if "<|eot_id|>" in j or "<|start_header_id|>" in j:
        return "llama3"
    # Llama 1/2 / Mistral
    if "[inst]" in j or "[/inst]" in j:
        return "llama"
    # ChatML (Qwen, Hermes, OpenChat, Phi-3, etc.)
    if "<|im_end|>" in j or "<|im_start|>" in j:
        return "chatml"
    return None


def _arch_to_template(arch: str) -> Optional[str]:
    arch = arch.lower()
    if arch == "gemma4":                                            return "gemma4"
    if "gemma" in arch:                                            return "gemma"
    if arch in ("llama", "mistral", "mixtral", "falcon", "starcoder"): return "llama"
    if arch in ("qwen2", "qwen", "phi3", "phi", "yi"):             return "chatml"
    return None


def _build_prompt(history: list[dict], model_path: str = "", template_key: str = None) -> str:
    if not history:
        return ""

    key = template_key or _detect_template(model_path)
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
