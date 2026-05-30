"""
halloffame.py — Immortalize your corrupted model's best/worst/weirdest outputs.
Open a PR to the FIBERCORE hall of fame repo. Science requires witnesses.

GitHub OAuth App setup (one-time):
  1. Go to https://github.com/settings/developers → "New OAuth App"
  2. Set Authorization callback URL to http://localhost (device flow doesn't need it)
  3. Copy the Client ID into GITHUB_CLIENT_ID below (or set env var MF_GITHUB_CLIENT_ID)
  4. Enable "Device authorization" under the app settings

Target repo: HALL_OF_FAME_REPO below — fork of Hbbrine/ModelFucker on GitHub.
"""

import os
import sys
import time
import datetime
import subprocess
from pathlib import Path
from typing import Optional

from rich.prompt import Prompt, Confirm
from rich.panel import Panel
from rich.syntax import Syntax

from ui import console, mf, ok, warn, err, section

# ── Config ───────────────────────────────────────────────────────────────────
HALL_OF_FAME_REPO = os.getenv("MF_HOF_REPO", "Hbbrine/ModelFucker")
HALL_OF_FAME_FILE = "HALL_OF_FAME.md"

# Your GitHub OAuth App client ID (device flow, no secret needed for public repo scope)
# Override with env var MF_GITHUB_CLIENT_ID if you've created your own OAuth App.
GITHUB_CLIENT_ID = os.getenv("MF_GITHUB_CLIENT_ID", "")


# ── Entry point ───────────────────────────────────────────────────────────────
def submit_to_hall_of_fame(
    model_path: str,
    corruption_passes: list,
    chat_history: list[dict],
) -> None:
    if not corruption_passes:
        warn("Can't submit — no corruption passes recorded. Corrupt the model first.")
        return

    if not chat_history:
        warn("Can't submit — no chat history. Have a conversation first.")
        return

    section("Hall of Fame Submission")
    mf("Preparing your entry for posterity...")
    console.print()

    # ── Select messages ──────────────────────────────────────────────────────
    n_messages = len(chat_history)
    raw = Prompt.ask(
        f"[cyan]How many messages to include?[/cyan] (last N of {n_messages})",
        default=str(min(n_messages, 6)),
    )
    try:
        n = int(raw)
        n = max(1, min(n, n_messages))
    except ValueError:
        err("That's not a number.")
        return

    selected = chat_history[-n:]

    # ── Preview ──────────────────────────────────────────────────────────────
    section("Message Preview")
    for msg in selected:
        role_style = "cyan" if msg["role"] == "user" else "magenta"
        console.print(f"[{role_style}]{msg['role']}:[/{role_style}] {msg['content'][:300]}")
    console.print()

    # ── Notable output ───────────────────────────────────────────────────────
    model_responses = [m["content"] for m in selected if m["role"] == "assistant"]
    auto_notable = model_responses[-1][:200] if model_responses else "(none)"
    notable = Prompt.ask(
        "[cyan]Notable output to highlight[/cyan] (auto-filled, edit or leave blank to use)",
        default=auto_notable,
    )

    # ── Confirm ──────────────────────────────────────────────────────────────
    console.print()
    if not Confirm.ask("[yellow]This will open a public PR on GitHub. Proceed?[/yellow]", default=False):
        warn("Submission cancelled — your secrets are safe (for now)")
        return

    # ── Authenticate ─────────────────────────────────────────────────────────
    console.print()
    mf("Authenticating with GitHub...")

    token = _get_github_token()
    if not token:
        return

    # ── Format entry ─────────────────────────────────────────────────────────
    model_name = Path(model_path).stem
    intensity_str = ", ".join(str(p.intensity) for p in corruption_passes)
    total_flips = sum(p.total_flips for p in corruption_passes)
    date_str = datetime.date.today().isoformat()

    github_username = _get_github_username(token)
    transcript_md = _format_transcript(selected)

    entry = f"""
## [{model_name}] — Intensity {intensity_str}
**Submitted by:** @{github_username}
**Date:** {date_str}
**Model:** `{Path(model_path).name}`
**Intensity:** {intensity_str}
**Passes:** {len(corruption_passes)}
**Total flips:** {total_flips:,}
**Notable output:** {notable}

### Transcript
{transcript_md}

---
"""

    # ── Preview entry ─────────────────────────────────────────────────────────
    section("Formatted Entry Preview")
    console.print(Syntax(entry, "markdown", theme="monokai", word_wrap=True))
    console.print()

    if not Confirm.ask("[yellow]Submit this entry?[/yellow]", default=True):
        warn("Submission cancelled at final step — coward move but understandable")
        return

    # ── Open PR ───────────────────────────────────────────────────────────────
    _open_pr(token, github_username, model_name, date_str, intensity_str, entry)


def _get_github_token() -> Optional[str]:
    """Try gh CLI first (it's already authed), then fall back to device flow."""
    # Try gh CLI
    try:
        result = subprocess.run(
            ["gh", "auth", "token"],
            capture_output=True, text=True, timeout=5
        )
        if result.returncode == 0 and result.stdout.strip():
            ok("Using gh CLI auth — frictionless")
            return result.stdout.strip()
    except (FileNotFoundError, subprocess.TimeoutExpired):
        pass

    # Device flow fallback
    if not GITHUB_CLIENT_ID:
        err(
            "No GitHub auth available.\n"
            "  Option 1: Install gh CLI and run [bold]gh auth login[/bold]\n"
            "  Option 2: Set [bold]MF_GITHUB_CLIENT_ID[/bold] env var with your OAuth App client ID"
        )
        return None

    return _device_flow_auth()


def _device_flow_auth() -> Optional[str]:
    """GitHub device flow OAuth — no browser redirect needed."""
    try:
        import requests
    except ImportError:
        err("requests library not installed. Run: pip install requests")
        return None

    mf("Starting GitHub device flow OAuth...")

    r = requests.post(
        "https://github.com/login/device/code",
        data={"client_id": GITHUB_CLIENT_ID, "scope": "public_repo"},
        headers={"Accept": "application/json"},
        timeout=10,
    )
    data = r.json()

    device_code = data["device_code"]
    user_code = data["user_code"]
    verification_uri = data.get("verification_uri", "https://github.com/login/device")
    interval = data.get("interval", 5)
    expires_in = data.get("expires_in", 900)

    console.print(
        f"\n  [bold white]1.[/bold white] Open: [link={verification_uri}]{verification_uri}[/link]\n"
        f"  [bold white]2.[/bold white] Enter code: [bold yellow]{user_code}[/bold yellow]\n"
    )

    deadline = time.time() + expires_in
    with console.status("Waiting for authorization..."):
        while time.time() < deadline:
            time.sleep(interval)
            r = requests.post(
                "https://github.com/login/oauth/access_token",
                data={
                    "client_id": GITHUB_CLIENT_ID,
                    "device_code": device_code,
                    "grant_type": "urn:ietf:params:oauth:grant-type:device_code",
                },
                headers={"Accept": "application/json"},
                timeout=10,
            )
            resp = r.json()

            if "access_token" in resp:
                ok("GitHub authorized — welcome to the Hall of Fame pipeline")
                return resp["access_token"]
            elif resp.get("error") == "authorization_pending":
                continue
            elif resp.get("error") == "slow_down":
                interval += 5
            else:
                err(f"Auth failed: {resp.get('error_description', resp.get('error'))}")
                return None

    err("Device code expired — try again")
    return None


def _get_github_username(token: str) -> str:
    try:
        from github import Github
        g = Github(token)
        return g.get_user().login
    except Exception:
        pass

    try:
        import requests
        r = requests.get(
            "https://api.github.com/user",
            headers={"Authorization": f"token {token}"},
            timeout=10,
        )
        return r.json().get("login", "anonymous")
    except Exception:
        return "anonymous"


def _open_pr(
    token: str,
    username: str,
    model_name: str,
    date_str: str,
    intensity_str: str,
    entry_markdown: str,
) -> None:
    mf("Opening Pull Request — this is the moment of truth...")

    # Try gh CLI first (simplest)
    if _try_gh_cli_pr(model_name, date_str, intensity_str, entry_markdown):
        return

    # Fall back to PyGithub
    _try_pygithub_pr(token, username, model_name, date_str, intensity_str, entry_markdown)


def _try_gh_cli_pr(
    model_name: str,
    date_str: str,
    intensity_str: str,
    entry_markdown: str,
) -> bool:
    """Use gh CLI to fork, commit, and open a PR. Returns True on success."""
    try:
        import tempfile, shutil

        branch = f"hof/{model_name}-{date_str}".replace(" ", "-").lower()[:60]
        title = f"Hall of Fame: {model_name} @ intensity {intensity_str}"
        body = (
            f"Auto-submitted via ModelFucker v3.0\n\n"
            f"Model: `{model_name}` | Intensity: {intensity_str} | Date: {date_str}"
        )

        # Clone the repo shallowly into a temp dir
        with tempfile.TemporaryDirectory() as tmp:
            clone_url = f"https://github.com/{HALL_OF_FAME_REPO}.git"
            result = subprocess.run(
                ["gh", "repo", "fork", HALL_OF_FAME_REPO, "--clone", "--default-branch-only"],
                cwd=tmp, capture_output=True, text=True, timeout=60
            )
            # gh forks into a subdir named after the repo
            repo_name = HALL_OF_FAME_REPO.split("/")[1]
            repo_dir = os.path.join(tmp, repo_name)

            if not os.path.isdir(repo_dir):
                raise RuntimeError(f"Clone failed: {result.stderr}")

            subprocess.run(
                ["git", "checkout", "-b", branch],
                cwd=repo_dir, capture_output=True, check=True
            )

            hof_path = os.path.join(repo_dir, HALL_OF_FAME_FILE)
            if os.path.exists(hof_path):
                with open(hof_path, "a", encoding="utf-8") as f:
                    f.write(entry_markdown)
            else:
                with open(hof_path, "w", encoding="utf-8") as f:
                    f.write(f"# Hall of Fame\n\n{entry_markdown}")

            subprocess.run(["git", "add", HALL_OF_FAME_FILE], cwd=repo_dir, check=True)
            subprocess.run(
                ["git", "commit", "-m", f"hof: add {model_name} entry"],
                cwd=repo_dir, check=True
            )
            subprocess.run(["git", "push", "origin", branch], cwd=repo_dir, check=True)

            pr_result = subprocess.run(
                ["gh", "pr", "create",
                 "--repo", HALL_OF_FAME_REPO,
                 "--title", title,
                 "--body", body],
                cwd=repo_dir, capture_output=True, text=True, check=True
            )

            pr_url = pr_result.stdout.strip()
            ok(f"PR opened: [link={pr_url}]{pr_url}[/link]")
            console.print(f"\n[cyan]◈ FIBERCORE — your corruption is now public knowledge ◈[/cyan]\n")
            return True

    except Exception as exc:
        warn(f"gh CLI path failed ({exc}) — trying PyGithub...")
        return False


def _try_pygithub_pr(
    token: str,
    username: str,
    model_name: str,
    date_str: str,
    intensity_str: str,
    entry_markdown: str,
) -> None:
    try:
        from github import Github, GithubException
    except ImportError:
        err(
            "PyGithub not installed and gh CLI path failed.\n"
            "  Fix: [bold]pip install PyGithub[/bold]"
        )
        return

    try:
        g = Github(token)
        user = g.get_user()
        target_repo = g.get_repo(HALL_OF_FAME_REPO)

        # Get or create fork
        try:
            fork = user.get_repo(HALL_OF_FAME_REPO.split("/")[1])
        except GithubException:
            mf("Forking repo...")
            fork = user.create_fork(target_repo)
            time.sleep(3)

        # Get current file
        branch = f"hof/{model_name}-{date_str}".replace(" ", "-")[:60]
        default_branch = target_repo.default_branch

        try:
            file_content = fork.get_contents(HALL_OF_FAME_FILE, ref=default_branch)
            current = file_content.decoded_content.decode("utf-8")
            sha = file_content.sha
        except GithubException:
            current = "# Hall of Fame\n\n"
            sha = None

        new_content = current + entry_markdown

        # Create branch
        ref = fork.get_git_ref(f"heads/{default_branch}")
        try:
            fork.create_git_ref(f"refs/heads/{branch}", ref.object.sha)
        except GithubException:
            pass

        # Update or create file
        commit_msg = f"hof: add {model_name} entry"
        if sha:
            fork.update_file(HALL_OF_FAME_FILE, commit_msg, new_content, sha, branch=branch)
        else:
            fork.create_file(HALL_OF_FAME_FILE, commit_msg, new_content, branch=branch)

        # Open PR
        pr = target_repo.create_pull(
            title=f"Hall of Fame: {model_name} @ intensity {intensity_str}",
            body=f"Auto-submitted via ModelFucker v3.0\n\nModel: `{model_name}` | Intensity: {intensity_str}",
            head=f"{username}:{branch}",
            base=default_branch,
        )

        ok(f"PR opened: [link={pr.html_url}]{pr.html_url}[/link]")
        console.print(f"\n[cyan]◈ FIBERCORE — your corruption is now public knowledge ◈[/cyan]\n")

    except Exception as exc:
        err(f"PR creation failed: {exc}")


def _format_transcript(messages: list[dict]) -> str:
    lines = []
    for msg in messages:
        role = "**User**" if msg["role"] == "user" else "**Model**"
        lines.append(f"{role}: {msg['content']}")
        lines.append("")
    return "\n".join(lines)
