"""
halloffame.py — Immortalize your corrupted model's best/worst/weirdest outputs.
Open a PR to the ModelFucker hall of fame repo. Science requires witnesses.

GitHub OAuth App setup (one-time):
  1. Go to https://github.com/settings/developers → "New OAuth App"
  2. Set Authorization callback URL to http://localhost (device flow doesn't need it)
  3. Copy the Client ID into GITHUB_CLIENT_ID below (or set env var MF_GITHUB_CLIENT_ID)
  4. Enable "Device authorization" under the app settings

Target repo: HALL_OF_FAME_REPO below — fork of Hackerbbrine/ModelFucker on GitHub.
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
HALL_OF_FAME_REPO = os.getenv("MF_HOF_REPO", "hackerbbrine/ModelFucker")
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
    from rich.table import Table
    from rich.columns import Columns
    from rich import box as rich_box

    if not corruption_passes:
        warn("Can't submit — no corruption passes recorded. Corrupt the model first.")
        return
    if not chat_history:
        warn("Can't submit — no chat history. Have a conversation first.")
        return

    # ── Header ───────────────────────────────────────────────────────────────
    console.print()
    console.print(Panel(
        "[bold white]Submit your corrupted model's finest moment to the public Hall of Fame.\n"
        "[dim]This opens a Pull Request on GitHub. Your transcript will be public.[/dim]",
        title="[bold yellow]◈ HALL OF FAME SUBMISSION ◈[/bold yellow]",
        border_style="yellow",
        padding=(1, 4),
    ))
    console.print()

    # ── Select messages ───────────────────────────────────────────────────────
    n_total = len(chat_history)
    console.print(f"[dim]You have [bold]{n_total}[/bold] messages in this session.[/dim]")
    while True:
        raw = Prompt.ask(
            f"[cyan]How many to include?[/cyan] [dim](last N)[/dim]",
            default=str(min(n_total, 6)),
        )
        try:
            n = int(raw)
            if 1 <= n <= n_total:
                break
            err(f"Pick a number between 1 and {n_total}.")
        except ValueError:
            err("Numbers only.")

    selected = chat_history[-n:]

    # ── Message preview panel ─────────────────────────────────────────────────
    preview_lines = []
    for msg in selected:
        if msg["role"] == "user":
            preview_lines.append(f"[cyan]you >[/cyan] {msg['content'][:200]}")
        else:
            preview_lines.append(f"[magenta]model >[/magenta] {msg['content'][:200]}")
        preview_lines.append("")

    console.print(Panel(
        "\n".join(preview_lines).strip(),
        title=f"[bold white]Selected Transcript[/bold white] [dim]({n} messages)[/dim]",
        border_style="dim cyan",
        padding=(1, 2),
    ))
    console.print()

    # ── Notable output ────────────────────────────────────────────────────────
    model_responses = [m["content"] for m in selected if m["role"] == "assistant"]
    auto_notable = model_responses[-1][:200] if model_responses else "(none)"
    console.print("[dim]This line gets highlighted in the Hall of Fame entry.[/dim]")
    notable = Prompt.ask(
        "[cyan]Notable output[/cyan]",
        default=auto_notable,
    )
    console.print()

    # ── Stats summary ─────────────────────────────────────────────────────────
    total_flips = sum(p.total_flips for p in corruption_passes)
    intensity_str = ", ".join(str(p.intensity) for p in corruption_passes)
    model_name = Path(model_path).stem

    stats_table = Table(box=rich_box.SIMPLE, show_header=False, padding=(0, 2))
    stats_table.add_column(style="dim white", no_wrap=True)
    stats_table.add_column(style="bold white")
    stats_table.add_row("Model",        Path(model_path).name)
    stats_table.add_row("Intensity",    intensity_str)
    stats_table.add_row("Passes",       str(len(corruption_passes)))
    stats_table.add_row("Total flips",  f"{total_flips:,}")
    stats_table.add_row("Messages",     str(n))

    console.print(Panel(
        stats_table,
        title="[bold white]Entry Summary[/bold white]",
        border_style="dim",
        padding=(0, 1),
    ))
    console.print()

    # ── Confirm ───────────────────────────────────────────────────────────────
    if not Confirm.ask(
        "[yellow]This will be public on GitHub.[/yellow] Open a PR?",
        default=False,
    ):
        console.print("[dim]Cancelled. Your experiments remain secret.[/dim]\n")
        return

    # ── Authenticate ──────────────────────────────────────────────────────────
    console.print()
    mf("Authenticating with GitHub...")
    token = _get_github_token()
    if not token:
        return

    # ── Build entry ───────────────────────────────────────────────────────────
    date_str = datetime.date.today().isoformat()
    github_username = _get_github_username(token)
    transcript_md = _format_transcript(selected)

    entry = (
        f"\n## [{model_name}] — Intensity {intensity_str}\n"
        f"**Submitted by:** @{github_username}  \n"
        f"**Date:** {date_str}  \n"
        f"**Model:** `{Path(model_path).name}`  \n"
        f"**Intensity:** {intensity_str}  \n"
        f"**Passes:** {len(corruption_passes)}  \n"
        f"**Total flips:** {total_flips:,}  \n"
        f"**Notable output:** {notable}\n\n"
        f"### Transcript\n{transcript_md}\n\n---\n"
    )

    # ── Preview formatted entry ───────────────────────────────────────────────
    console.print(Panel(
        Syntax(entry, "markdown", theme="monokai", word_wrap=True),
        title="[bold white]Formatted Hall of Fame Entry[/bold white]",
        border_style="yellow",
        padding=(1, 1),
    ))
    console.print()

    if not Confirm.ask("[yellow]Ship it?[/yellow]", default=True):
        console.print("[dim]Maybe next time.[/dim]\n")
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
    """Clone the repo directly (no fork — we own it), push a branch, open a PR."""
    try:
        import tempfile

        branch = f"hof/{model_name}-{date_str}".replace(" ", "-").lower()[:60]
        title = f"Hall of Fame: {model_name} @ intensity {intensity_str}"
        body = (
            f"Auto-submitted via ModelFucker v3.0\n\n"
            f"Model: `{model_name}` | Intensity: {intensity_str} | Date: {date_str}"
        )

        with tempfile.TemporaryDirectory() as tmp:
            # Clone directly — no fork needed when you own the repo
            clone_url = f"https://github.com/{HALL_OF_FAME_REPO}.git"
            result = subprocess.run(
                ["gh", "repo", "clone", HALL_OF_FAME_REPO, "--", "--depth=1"],
                cwd=tmp, capture_output=True, text=True, timeout=60
            )
            repo_name = HALL_OF_FAME_REPO.split("/")[1]
            repo_dir = os.path.join(tmp, repo_name)

            if not os.path.isdir(repo_dir):
                raise RuntimeError(f"Clone failed: {result.stderr}")

            # Set git identity in the temp clone — global config may not exist
            gh_user = subprocess.run(["gh", "api", "user", "--jq", ".login"],
                                     capture_output=True, text=True).stdout.strip() or "hackerbbrine"
            subprocess.run(["git", "config", "user.name", gh_user], cwd=repo_dir, check=True)
            subprocess.run(["git", "config", "user.email", f"{gh_user}@users.noreply.github.com"],
                           cwd=repo_dir, check=True)

            subprocess.run(["git", "checkout", "-b", branch],
                           cwd=repo_dir, capture_output=True, check=True)

            hof_path = os.path.join(repo_dir, HALL_OF_FAME_FILE)
            with open(hof_path, "a", encoding="utf-8") as f:
                f.write(entry_markdown)

            subprocess.run(["git", "add", HALL_OF_FAME_FILE], cwd=repo_dir, check=True)
            subprocess.run(["git", "commit", "-m", f"hof: add {model_name} entry"],
                           cwd=repo_dir, check=True)
            subprocess.run(["git", "push", "origin", branch],
                           cwd=repo_dir, check=True)

            pr_result = subprocess.run(
                ["gh", "pr", "create",
                 "--repo", HALL_OF_FAME_REPO,
                 "--title", title,
                 "--body", body],
                cwd=repo_dir, capture_output=True, text=True, check=True
            )

            pr_url = pr_result.stdout.strip()
            ok(f"PR opened: [link={pr_url}]{pr_url}[/link]")
            console.print(f"\n[cyan]your corruption is now public knowledge[/cyan]\n")
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
        repo = g.get_repo(HALL_OF_FAME_REPO)
        default_branch = repo.default_branch

        branch = f"hof/{model_name}-{date_str}".replace(" ", "-")[:60]

        # Fetch fresh SHA — stale SHA causes a 409 conflict
        try:
            file_content = repo.get_contents(HALL_OF_FAME_FILE, ref=default_branch)
            current = file_content.decoded_content.decode("utf-8")
            sha = file_content.sha
        except GithubException:
            current = "# Hall of Fame\n\n"
            sha = None

        new_content = current + entry_markdown

        # Create branch off latest default branch HEAD
        head_sha = repo.get_git_ref(f"heads/{default_branch}").object.sha
        try:
            repo.create_git_ref(f"refs/heads/{branch}", head_sha)
        except GithubException:
            pass  # branch already exists, carry on

        # Commit the updated file directly to the branch
        commit_msg = f"hof: add {model_name} entry"
        if sha:
            repo.update_file(HALL_OF_FAME_FILE, commit_msg, new_content, sha, branch=branch)
        else:
            repo.create_file(HALL_OF_FAME_FILE, commit_msg, new_content, branch=branch)

        # Open PR from branch → default
        pr = repo.create_pull(
            title=f"Hall of Fame: {model_name} @ intensity {intensity_str}",
            body=f"Auto-submitted via ModelFucker v3.0\n\nModel: `{model_name}` | Intensity: {intensity_str}",
            head=branch,
            base=default_branch,
        )

        ok(f"PR opened: [link={pr.html_url}]{pr.html_url}[/link]")
        console.print(f"\n[cyan]your corruption is now public knowledge[/cyan]\n")

    except Exception as exc:
        err(f"PR creation failed: {exc}")


def _format_transcript(messages: list[dict]) -> str:
    lines = []
    for msg in messages:
        role = "**User**" if msg["role"] == "user" else "**Model**"
        lines.append(f"{role}: {msg['content']}")
        lines.append("")
    return "\n".join(lines)
