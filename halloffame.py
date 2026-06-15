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
    """Pure GitHub REST API — no git clone, no PyGithub, no gh pr create."""
    import base64
    import requests

    mf("Opening Pull Request — this is the moment of truth...")

    branch = f"hof/{model_name}-{date_str}".replace(" ", "-").lower()[:60]
    base_url = f"https://api.github.com/repos/{HALL_OF_FAME_REPO}"
    headers = {
        "Authorization": f"token {token}",
        "Accept": "application/vnd.github.v3+json",
    }

    try:
        # 1. Get default branch name
        r = requests.get(base_url, headers=headers, timeout=10)
        r.raise_for_status()
        default_branch = r.json()["default_branch"]

        # 2. Get current file content + SHA from default branch (always fresh)
        r = requests.get(
            f"{base_url}/contents/{HALL_OF_FAME_FILE}",
            headers=headers,
            params={"ref": default_branch},
            timeout=10,
        )
        if r.status_code == 200:
            data = r.json()
            current = base64.b64decode(data["content"]).decode("utf-8")
            file_sha = data["sha"]
        else:
            current = "# Hall of Fame\n\n"
            file_sha = None

        new_content = current + entry_markdown

        # 3. Get HEAD sha of default branch for new branch creation
        r = requests.get(
            f"{base_url}/git/ref/heads/{default_branch}",
            headers=headers, timeout=10,
        )
        r.raise_for_status()
        head_sha = r.json()["object"]["sha"]

        # 4. Create the branch (ignore 422 = already exists)
        r = requests.post(
            f"{base_url}/git/refs",
            headers=headers,
            json={"ref": f"refs/heads/{branch}", "sha": head_sha},
            timeout=10,
        )
        if r.status_code not in (201, 422):
            r.raise_for_status()

        # 5. If branch already existed, fetch the file SHA from THAT branch
        #    (it may differ from default branch after previous partial attempts)
        if r.status_code == 422:
            r2 = requests.get(
                f"{base_url}/contents/{HALL_OF_FAME_FILE}",
                headers=headers,
                params={"ref": branch},
                timeout=10,
            )
            if r2.status_code == 200:
                file_sha = r2.json()["sha"]
                # Use the base content from this branch too so we don't duplicate
                current = base64.b64decode(r2.json()["content"]).decode("utf-8")
                new_content = current + entry_markdown

        # 6. Commit the updated file to the branch
        commit_payload = {
            "message": f"hof: add {model_name} entry",
            "content": base64.b64encode(new_content.encode()).decode(),
            "branch": branch,
        }
        if file_sha:
            commit_payload["sha"] = file_sha

        r = requests.put(
            f"{base_url}/contents/{HALL_OF_FAME_FILE}",
            headers=headers,
            json=commit_payload,
            timeout=10,
        )
        r.raise_for_status()

        # 7. Open the PR
        r = requests.post(
            f"{base_url}/pulls",
            headers=headers,
            json={
                "title": f"Hall of Fame: {model_name} @ intensity {intensity_str}",
                "body": (
                    f"Auto-submitted via ModelFucker v3.1\n\n"
                    f"Model: `{model_name}` | Intensity: {intensity_str} | Date: {date_str}"
                ),
                "head": branch,
                "base": default_branch,
            },
            timeout=10,
        )

        if r.status_code == 422 and "already exists" in r.text:
            # PR for this branch is already open
            existing = requests.get(
                f"{base_url}/pulls",
                headers=headers,
                params={"head": f"{username}:{branch}", "state": "open"},
                timeout=10,
            ).json()
            pr_url = existing[0]["html_url"] if existing else f"https://github.com/{HALL_OF_FAME_REPO}/pulls"
        else:
            r.raise_for_status()
            pr_url = r.json()["html_url"]

        ok(f"PR opened: [link={pr_url}]{pr_url}[/link]")
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
