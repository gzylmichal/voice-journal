#!/usr/bin/env python3
"""cli.py — Interactive terminal menu for Voice Journal VPS."""

import json
import os
import shutil
import socket
import subprocess
import sys
import time
from datetime import date, datetime
from pathlib import Path
from typing import List, Optional, Tuple

sys.path.insert(0, str(Path(__file__).parent))

import questionary
import requests
from rich.console import Console
from rich.panel import Panel
from rich.table import Table

from pipeline.config import (
    ANTHROPIC_API_KEY,
    ARCHIVE_MD_DIR,
    BUFFER_DIR,
    CLAUDE_MODEL,
    GEMINI_MODEL,
    GOOGLE_API_KEY,
    GROQ_API_KEY,
    INBOX_DIR,
    LLAMA_MODEL,
    SUPPORTED_FORMATS,
)
import ai_client

BASE_DIR = Path("/opt/voice-journal")
console = Console()


# ---------------------------------------------------------------------------
# Pure utility functions (testable)
# ---------------------------------------------------------------------------

def _inbox_count(inbox_dir: Path = INBOX_DIR, formats: set = SUPPORTED_FORMATS) -> int:
    """Return count of audio files in inbox."""
    if not inbox_dir.exists():
        return 0
    return sum(1 for f in inbox_dir.iterdir() if f.is_file() and f.suffix.lower() in formats)


def _load_buffer(buffer_dir: Path = BUFFER_DIR, d: Optional[date] = None) -> List[dict]:
    """Load buffered transcripts for a given date. Returns [] if none."""
    if d is None:
        d = date.today()
    path = buffer_dir / f"{d.isoformat()}.json"
    if not path.exists():
        return []
    try:
        with open(path) as f:
            return json.load(f)
    except Exception:
        return []


# ---------------------------------------------------------------------------
# Header
# ---------------------------------------------------------------------------

def _show_header():
    hostname = socket.gethostname()
    now = datetime.now().strftime("%Y-%m-%d %H:%M")
    count = _inbox_count()
    inbox_str = f"{count} file{'s' if count != 1 else ''}"
    console.print(Panel(
        f"[bold]Voice Journal[/bold]  ·  {hostname}\n"
        f"{now}  ·  inbox: {inbox_str}",
        border_style="cyan",
        expand=False,
    ))


# ---------------------------------------------------------------------------
# View operations
# ---------------------------------------------------------------------------

def _show_inbox():
    if not INBOX_DIR.exists():
        console.print("[yellow]Inbox is empty.[/yellow]")
        return
    files = sorted(
        (f for f in INBOX_DIR.iterdir() if f.is_file() and f.suffix.lower() in SUPPORTED_FORMATS),
        key=lambda f: f.stat().st_mtime,
    )
    if not files:
        console.print("[yellow]Inbox is empty.[/yellow]")
        return
    table = Table(title="Inbox", show_header=True, header_style="bold cyan")
    table.add_column("Filename")
    table.add_column("Size", justify="right")
    table.add_column("Modified")
    for f in files:
        size_kb = f.stat().st_size / 1024
        mtime = datetime.fromtimestamp(f.stat().st_mtime).strftime("%Y-%m-%d %H:%M")
        table.add_row(f.name, f"{size_kb:.1f} KB", mtime)
    console.print(table)


def _show_buffer():
    entries = _load_buffer()
    if not entries:
        console.print("[yellow]No buffer for today.[/yellow]")
        return
    table = Table(title=f"Buffer — {date.today()}", show_header=True, header_style="bold cyan")
    table.add_column("Time", width=6)
    table.add_column("Preview")
    table.add_column("OK", width=4)
    for t in entries:
        preview = (t.get("text") or "")[:80]
        ok = "[red]✗[/red]" if t.get("error") else "[green]✓[/green]"
        table.add_row(t.get("time", "?"), preview, ok)
    console.print(table)


def _view_logs():
    for log_name in ("voice_journal.log", "weekly_report.log"):
        log_path = BASE_DIR / log_name
        if not log_path.exists():
            console.print(f"[yellow]{log_name} not found.[/yellow]")
            continue
        lines = log_path.read_text(encoding="utf-8").splitlines()[-50:]
        console.print(Panel(
            "\n".join(lines),
            title=f"[bold]{log_name}[/bold] — last 50 lines",
            border_style="blue",
        ))


def _run_search():
    keyword = questionary.text("Keyword or date (e.g. 'workout', '2026-05'):").ask()
    if not keyword:
        return
    if not ARCHIVE_MD_DIR.exists():
        console.print("[yellow]No markdown archive found.[/yellow]")
        return
    matches: List[Tuple[str, int, str]] = []
    for md_file in sorted(ARCHIVE_MD_DIR.glob("*.md")):
        for i, line in enumerate(md_file.read_text(encoding="utf-8").splitlines(), 1):
            if keyword.lower() in line.lower():
                matches.append((md_file.name, i, line.strip()))
    if not matches:
        console.print(f"[yellow]No entries found for '{keyword}'.[/yellow]")
        return
    table = Table(title=f"Search: '{keyword}'", show_header=True, header_style="bold cyan")
    table.add_column("File", width=28)
    table.add_column("Line", width=4, justify="right")
    table.add_column("Match")
    for filename, lineno, text in matches[:50]:
        table.add_row(filename, str(lineno), text[:100])
    console.print(table)
    if len(matches) > 50:
        console.print(f"[dim]... {len(matches) - 50} more results not shown[/dim]")


def _reprocess_memo():
    audio_dir = BASE_DIR / "archive" / "audio"
    if not audio_dir.exists():
        console.print("[yellow]No audio archive found.[/yellow]")
        return

    # Collect all audio files from the archive, newest first
    all_files = sorted(
        (f for f in audio_dir.rglob("*") if f.is_file() and f.suffix.lower() in SUPPORTED_FORMATS),
        key=lambda f: f.stat().st_mtime,
        reverse=True,
    )[:20]

    if not all_files:
        console.print("[yellow]No archived audio files found.[/yellow]")
        return

    # Build display choices grouped by date folder
    choices = []
    seen_dates: set = set()
    for f in all_files:
        date_label = f.parent.name  # YYYY-MM-DD directory
        if date_label not in seen_dates:
            seen_dates.add(date_label)
            choices.append(questionary.Separator(f"── {date_label}"))
        size_kb = f.stat().st_size / 1024
        choices.append(questionary.Choice(
            title=f"  {f.name}  ({size_kb:.0f} KB)",
            value=f,
        ))

    selected = questionary.checkbox("Select files to reprocess (space to select, enter to confirm):", choices=choices).ask()
    if not selected:
        console.print("[dim]No files selected.[/dim]")
        return

    inbox = INBOX_DIR
    inbox.mkdir(parents=True, exist_ok=True)
    copied = 0
    for src in selected:
        dest = inbox / src.name
        shutil.copy2(src, dest)
        console.print(f"[green]Copied[/green] {src.name} → inbox/")
        copied += 1

    console.print(f"\n[bold]{copied} file(s) added to inbox.[/bold]")
    console.print("[dim]Tip: run 'Transcribe inbox' now, then 'Run overnight' to regenerate the Notion entry for that date.[/dim]")

    if questionary.confirm("Transcribe now?", default=True).ask():
        _run_script(BASE_DIR / "voice_journal.py", "--mode", "upload")


_DOMAIN = "michal-journal.duckdns.org"


def _download_preview():
    candidates = [
        (BASE_DIR / "debrief-preview.html",  "Morning Debrief",  "debrief-preview.html"),
        (BASE_DIR / "weekly-preview.html",   "Weekly Review",    "weekly-preview.html"),
    ]
    available = [(label, fname, path) for path, label, fname in candidates if path.exists()]

    if not available:
        console.print("[yellow]No preview files found. Generate a preview first.[/yellow]")
        return

    token = os.getenv("UPLOAD_TOKEN", "")
    if not token:
        console.print("[yellow]UPLOAD_TOKEN not set — cannot build preview URL.[/yellow]")
        return

    choices = []
    for label, fname, path in available:
        mtime = datetime.fromtimestamp(path.stat().st_mtime).strftime("%Y-%m-%d %H:%M")
        size_kb = path.stat().st_size / 1024
        choices.append(questionary.Choice(f"{label}  ({size_kb:.0f} KB, {mtime})", value=fname))

    if len(choices) == 1:
        fname = choices[0].value
    else:
        fname = questionary.select("Which preview to open?", choices=choices).ask()
        if not fname:
            return

    url = f"https://{_DOMAIN}/preview/{fname}?token={token}"
    console.print(f"\n[bold cyan]Open in your browser:[/bold cyan]")
    console.print(f"[bold]{url}[/bold]")


def _change_location():
    ENV_FILE = BASE_DIR / ".env"

    city = questionary.text("Enter city name:").ask()
    if not city:
        return

    try:
        resp = requests.get(
            "https://geocoding-api.open-meteo.com/v1/search",
            params={"name": city, "count": 8, "language": "en", "format": "json"},
            timeout=10,
        )
        resp.raise_for_status()
        results = resp.json().get("results") or []
    except Exception as exc:
        console.print(f"[red]Geocoding lookup failed: {exc}[/red]")
        return

    if not results:
        console.print(f"[yellow]No results found for '{city}'.[/yellow]")
        return

    choices = [
        questionary.Choice(
            title=f"{r['name']}, {r.get('admin1', '')} — {r.get('country', '')}  ({r['latitude']:.4f}, {r['longitude']:.4f})",
            value=r,
        )
        for r in results
    ]
    chosen = questionary.select("Select location:", choices=choices).ask()
    if not chosen:
        return

    new_name = f"{chosen['name']}, {chosen.get('country', '')}".strip(", ")
    new_lat  = f"{chosen['latitude']:.4f}"
    new_lon  = f"{chosen['longitude']:.4f}"

    try:
        lines = ENV_FILE.read_text(encoding="utf-8").splitlines()
        updated = []
        for line in lines:
            if line.startswith("LOCATION_NAME="):
                updated.append(f"LOCATION_NAME={new_name}")
            elif line.startswith("LATITUDE="):
                updated.append(f"LATITUDE={new_lat}")
            elif line.startswith("LONGITUDE="):
                updated.append(f"LONGITUDE={new_lon}")
            else:
                updated.append(line)
        ENV_FILE.write_text("\n".join(updated) + "\n", encoding="utf-8")
    except Exception as exc:
        console.print(f"[red]Failed to update .env: {exc}[/red]")
        return

    console.print(f"[green]Location updated:[/green] {new_name}  ({new_lat}, {new_lon})")


def _run_cleanup():
    removed = 0
    freed = 0

    buffer_archive = BUFFER_DIR / "archive"
    if buffer_archive.exists():
        cutoff = time.time() - 30 * 86400
        for f in buffer_archive.iterdir():
            if f.is_file() and f.stat().st_mtime < cutoff:
                freed += f.stat().st_size
                f.unlink()
                removed += 1

    for tmp_dir in Path("/tmp").glob("pipeline_*"):
        if tmp_dir.is_dir():
            freed += sum(f.stat().st_size for f in tmp_dir.rglob("*") if f.is_file())
            shutil.rmtree(tmp_dir)
            removed += 1

    if removed == 0:
        console.print("[green]Nothing to clean up.[/green]")
    else:
        console.print(f"[green]Removed {removed} item(s) ({freed / 1024:.1f} KB freed).[/green]")


def _run_diagnostics():
    providers = [
        (
            "Claude", ANTHROPIC_API_KEY, CLAUDE_MODEL,
            "https://api.anthropic.com/v1/models",
            {"x-api-key": ANTHROPIC_API_KEY, "anthropic-version": "2023-06-01"},
        ),
        (
            "Gemini", GOOGLE_API_KEY, GEMINI_MODEL,
            f"https://generativelanguage.googleapis.com/v1beta/models?key={GOOGLE_API_KEY}",
            {},
        ),
        (
            "Groq", GROQ_API_KEY, LLAMA_MODEL,
            "https://api.groq.com/openai/v1/models",
            {"Authorization": f"Bearer {GROQ_API_KEY}"},
        ),
    ]
    active = ai_client.resolve_provider()
    table = Table(title="Provider Diagnostics", show_header=True, header_style="bold cyan")
    table.add_column("Provider", width=10)
    table.add_column("Status", width=8)
    table.add_column("Latency", justify="right", width=10)
    table.add_column("Model")
    table.add_column("Active", width=6)
    for name, key, model, url, headers in providers:
        if not key:
            table.add_row(name, "[dim]no key[/dim]", "—", model, "")
            continue
        try:
            t0 = time.time()
            resp = requests.get(url, headers=headers, timeout=10)
            ms = int((time.time() - t0) * 1000)
            status = f"[green]✓ {resp.status_code}[/green]" if resp.status_code == 200 else f"[red]✗ {resp.status_code}[/red]"
            latency = f"{ms} ms"
        except Exception:
            status = "[red]✗ err[/red]"
            latency = "—"
        is_active = "[bold cyan]●[/bold cyan]" if name.lower() == active else ""
        table.add_row(name, status, latency, model, is_active)
    console.print(table)
    console.print(f"[dim]Active provider: {active.upper()}[/dim]")


# ---------------------------------------------------------------------------
# Pipeline runner
# ---------------------------------------------------------------------------

def _run_script(*args):
    """Run a pipeline script as a subprocess, streaming output live."""
    try:
        subprocess.run(["python3"] + [str(a) for a in args], cwd=str(BASE_DIR))
    except KeyboardInterrupt:
        console.print("\n[yellow]Interrupted.[/yellow]")


# ---------------------------------------------------------------------------
# Menu
# ---------------------------------------------------------------------------

_W = 28  # label column width for alignment

MENU_CHOICES = [
    questionary.Choice(f"{'Transcribe inbox':<{_W}} Transcribe new audio files and buffer transcripts",      value="process_inbox"),
    questionary.Choice(f"{'Run overnight':<{_W}} Consolidate today's buffer into a journal entry",            value="overnight"),
    questionary.Choice(f"{'Reprocess memo':<{_W}} Pick archived audio files to re-transcribe and buffer",    value="reprocess_memo"),
    questionary.Separator(),
    questionary.Choice(f"{'Morning Debrief — send':<{_W}} Collect all sources and email today's debrief",    value="debrief_send"),
    questionary.Choice(f"{'Morning Debrief — preview':<{_W}} Render debrief HTML → debrief-preview.html",    value="debrief_preview"),
    questionary.Choice(f"{'Change debrief location':<{_W}} Update city, lat/lon used for weather and debrief", value="change_location"),
    questionary.Choice(f"{'Weekly Review — send':<{_W}} Build and email the weekly coaching analysis",        value="weekly_review_send"),
    questionary.Choice(f"{'Weekly Review — preview':<{_W}} Render weekly review HTML → weekly-preview.html", value="weekly_review_preview"),
    questionary.Choice(f"{'Download preview':<{_W}} Show SCP command to copy a preview file to your Mac",    value="download_preview"),
    questionary.Separator(),
    questionary.Choice(f"{'View inbox':<{_W}} List audio files waiting in the inbox",                        value="view_inbox"),
    questionary.Choice(f"{'View buffer':<{_W}} Show today's buffered transcripts",                           value="view_buffer"),
    questionary.Choice(f"{'Provider diagnostics':<{_W}} Ping all AI APIs and report status / latency",       value="diagnostics"),
    questionary.Choice(f"{'View logs':<{_W}} Tail voice_journal.log and weekly_report.log",                  value="view_logs"),
    questionary.Choice(f"{'Search journal entries':<{_W}} Grep the markdown archive by keyword or date",     value="search"),
    questionary.Choice(f"{'Archive cleanup':<{_W}} Remove stale temp files",                                 value="cleanup"),
    questionary.Separator(),
    questionary.Choice("Exit",                                                                                value="exit"),
]

DEBRIEF_DIR = BASE_DIR / "debrief"


def _run_debrief(*args):
    """Run a debrief script using the project venv."""
    venv_python = BASE_DIR / "venv/bin/python3"
    interpreter = str(venv_python) if venv_python.exists() else "python3"
    try:
        subprocess.run([interpreter] + [str(a) for a in args], cwd=str(DEBRIEF_DIR))
    except KeyboardInterrupt:
        console.print("\n[yellow]Interrupted.[/yellow]")


ACTIONS = {
    "process_inbox":         lambda: _run_script(BASE_DIR / "voice_journal.py", "--mode", "upload"),
    "overnight":             lambda: _run_script(BASE_DIR / "voice_journal.py", "--mode", "overnight"),
    "reprocess_memo":        _reprocess_memo,
    "debrief_send":          lambda: _run_debrief(DEBRIEF_DIR / "main.py"),
    "debrief_preview":       lambda: _run_debrief(DEBRIEF_DIR / "main.py", "--preview"),
    "change_location":       _change_location,
    "weekly_review_send":    lambda: _run_script(BASE_DIR / "weekly_report.py"),
    "weekly_review_preview": lambda: _run_script(BASE_DIR / "weekly_report.py", "--preview"),
    "download_preview":      _download_preview,
    "view_inbox":            _show_inbox,
    "view_buffer":           _show_buffer,
    "diagnostics":           _run_diagnostics,
    "view_logs":             _view_logs,
    "search":                _run_search,
    "cleanup":               _run_cleanup,
}


def run_menu():
    while True:
        console.clear()
        _show_header()
        console.print()

        choice = questionary.select("Select action", choices=MENU_CHOICES).ask()

        if choice is None or choice == "exit":
            console.print("[dim]Goodbye.[/dim]")
            break

        console.print()
        action = ACTIONS.get(choice)
        if action:
            action()

        console.print()
        questionary.press_any_key_to_continue("Press any key to return to the menu...").ask()


def main():
    try:
        run_menu()
    except KeyboardInterrupt:
        console.print("\n[dim]Goodbye.[/dim]")


if __name__ == "__main__":
    main()
