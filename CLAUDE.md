# CLAUDE.md — Guardrails for working on Voice Journal

This is a personal production system. It runs unattended on a VPS and the owner
finds out about breakage the next morning when his journal/workout data is wrong
or missing. A previous session broke the upload path. Follow these rules strictly.

## Definition of done — non-negotiable

A change is NOT done until BOTH pass locally:

```bash
python3 -m pytest tests/ test_analytics.py test_cli.py -q
python3 smoke_test.py
```

- `smoke_test.py` runs the real receiver → upload → overnight wiring offline
  (only Groq/Notion HTTP is faked). It exists precisely because unit mocks
  previously hid a broken upload path. If it fails, the pipeline is broken —
  fix the code, NEVER weaken the smoke test's checks to make it pass.
- If a test fails for a reason that looks unrelated to your change: STOP and
  report it. Do not "fix" it by changing the assertion or deleting the test.
- Never claim completion with failing tests, TODOs, or untested code paths.

## Contracts — do not change without updating ALL parties

These shapes are persisted on disk and/or shared across entry points. Old data
exists on the VPS in the old format; changes must be backward compatible.

1. **Transcript dict** (produced by `pipeline/audio.py:transcribe_file`):
   `{"file", "time", "text", "raw_text", "error"}` — consumed by extractors,
   journal, storage, and buffered to disk.
2. **Buffer JSON** (`buffer/YYYY-MM-DD.json`):
   `{"transcripts": [...], "pending_writes": [{batch_id, workout, tasks, events,
   bodyweight, *_written_at}]}`. `load_buffer` must keep reading old formats.
3. **Notion property names** (`Date`, `Weight (kg)`, `Top Set (kg)`, `Weight`,
   etc. in `pipeline/notion_client.py`) mirror real database schemas the owner
   cannot easily migrate. Never rename. New properties require asking first.
4. **CLI flags of `voice_journal.py`** (`--mode upload|overnight|morning`) are
   invoked by systemd timers, `receiver.py` (subprocess), and `cli.py`.
5. **`ai_client.call_ai(user_message, system_prompt, label, max_tokens,
   temperature)`** — used by extractors, journal, weekly_report, debrief.
6. **Receiver `/upload`** accepts BOTH multipart (`file` field) and raw-body
   POSTs — the iOS Shortcut sends raw body with a Content-Type header. Breaking
   raw-body upload breaks the only producer of data.

Before changing ANY function signature or return shape: grep for every caller.
Callers live outside the obvious module — check `cli.py`, `weekly_report.py`,
`backfill_workouts.py`, `receiver.py`, `debrief/`, and `tests/`.

## External API shapes — verify, don't assume

- Groq Whisper `verbose_json` segments are **dicts** (`seg.get(...)`), and the
  return object has `.text` / `.segments` attributes. If you change how the
  response is parsed, update `FakeTranscription` in `smoke_test.py` to match the
  REAL documented shape — not your assumption.
- Notion API version is pinned (`2022-06-28`). Don't bump casually.
- Whisper prompt (`WHISPER_PROMPT` in config) must contain NO digits — numeric
  examples bias Whisper into substituting them into transcripts. There is a test
  for this; keep it true.

## Scope discipline

- Touch ONLY what the task requires. No opportunistic refactors, renames,
  formatting sweeps, or "while I'm here" improvements. If you spot a problem,
  note it in your summary instead of fixing it unasked.
- One concern per commit, following the existing `fix(scope): ...` style.
- Don't add dependencies without asking. The VPS venv is managed manually.
- Don't modify: `.env*`, `gcal_token.json`, `gcal_credentials.json`,
  `*.log`, anything under `inbox/`, `buffer/`, `archive/`, `.git/`.

## Language

Memos are Polish + English mixed, on purpose. Any keyword list, prompt, or
filler-hallucination list must cover both languages. Journal output is English.

## Deployment reality

Code in this folder is the source of truth, but it runs at `/opt/voice-journal/`
on a Hetzner VPS (see `vps-reference.md`). Nothing you change here is live until
the owner deploys it. End every task summary with: which files must be copied to
the VPS, and a reminder to run `python3 smoke_test.py` there after deploying.

## When uncertain

If a task is ambiguous, or requires breaking any rule above — ask first.
A skipped feature is recoverable; silently corrupted journal data is not.
