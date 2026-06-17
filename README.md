# Voice Journal VPS

Record voice memos throughout the day → a VPS transcribes and files them into Notion in
real time → an overnight pass consolidates the day into a journal entry → morning debrief
and weekly coaching emails close the loop. Optional push notifications give instant
feedback after every memo.

```
iPhone                              Hetzner VPS
┌──────────────┐                    ┌──────────────────────────────────────┐
│ iOS Shortcut │                    │ nginx → receiver.py (gunicorn :8675) │
│ Record memo  │──── HTTPS POST ───►│  saves .m4a → inbox/ → triggers      │
│ (any time)   │                    │  voice_journal.py --mode upload       │
└──────────────┘                    │   Groq Whisper → transcribe          │
                                    │   1 LLM pass → workout / tasks /      │
                                    │     events / bodyweight / metrics /   │
                                    │     query                             │
                                    │   → Notion + GCal (real time)         │
                                    │   → ntfy push (brief + summary)       │
                                    │                                      │
                                    │ 02:00 — voice_journal --mode overnight│
                                    │   buffer → journal MD → Notion        │
                                    │ 05:30 — debrief/main.py (email)       │
                                    │ 06:30 Sun — weekly_report.py          │
                                    │ 08:00 — healthcheck.py (self-test)    │
                                    └──────────────────────────────────────┘
```

> Memos are processed **per upload** (within ~10–20 s), not only overnight. The overnight
> pass only consolidates the day's buffer into one journal entry; it no longer re-extracts.

---

## Pipeline at a glance

A single LLM call per memo batch (`extract_all`) returns one JSON object with six
sections, so the categories never compete for the same numbers:

| Section | Goes to | Notes |
|---|---|---|
| `workout` | Notion Workout Log | per-set detail, RPE, pain note, bodyweight-exercise load |
| `tasks` | Notion Task DB | type/priority/due date |
| `events` | Google Calendar | resolved relative dates |
| `bodyweight` | Notion Bodyweight Log | keyword pre-filter + plausibility validation |
| `metrics` | Notion Daily metrics | qualitative sleep/energy/note (never numbers) |
| `query` | ntfy push only | history question — isolated, never touches the journal |

---

## Project Structure

```
voice_journal_vps/
│
├── voice_journal.py          # Pipeline: upload (real-time writes) + overnight consolidation
├── receiver.py               # gunicorn endpoint that accepts audio POSTs
├── weekly_report.py          # Sunday coaching report (analytics, charts, email)
├── analytics.py              # e1RM, volume, PRs, plateau, progression, session classify,
│                             #   cycle resolver, session plan, adherence
├── cli.py                    # Interactive terminal menu (questionary + rich)
├── ai_client.py              # Provider abstraction: Claude → Gemini → Llama, unified retries
├── models.py                 # Notion page → typed dict
├── backfill_workouts.py      # Reprocess archived audio to fill the Workout DB
├── backfill_sessions.py      # Relabel historical Session by day via classify_session (idempotent; --apply)
├── healthcheck.py            # 08:00 daily self-test → ntfy push on failure
├── gcal_auth.py              # One-time OAuth setup for Google Calendar
├── deploy.sh                 # One-shot consistent deploy to the VPS (rsync, protects .env/data)
├── workout_plan.json         # Daily planner config: cycle + per-split exercise templates
│
├── pipeline/
│   ├── config.py             # All env vars + path constants (single source of truth)
│   ├── plan_config.py        # Load/validate workout_plan.json (graceful when absent)
│   ├── audio.py              # Groq Whisper transcription + segment hallucination filter
│   ├── journal.py            # Format transcripts → markdown journal entry
│   ├── extractors.py         # extract_all + per-category wrappers, merge_buffered_workouts
│   ├── prompts.py            # Unified EXTRACTION_SYSTEM_PROMPT + journal prompt
│   ├── notion_client.py      # Notion writes + fetches; Session classified from exercises
│   ├── brief.py              # Pre-workout brief (deterministic progression, no LLM)
│   ├── notify.py             # ntfy transport + batch summary + session-plan push
│   ├── lock.py               # flock-based pipeline lock (concurrency safety)
│   ├── gcal_client.py        # Google Calendar event creation
│   └── storage.py            # Daily JSON buffer + markdown archive + raw-transcript audit
│
├── debrief/                  # Morning Debrief email system
│   ├── main.py · config.py · formatter.py · sender.py · synthesis.py
│   └── collectors/           # weather, calendar, notion, news, currency, crypto,
│                             #   airquality, history, workout (PRs), task (aging)
│
├── tests/                    # pytest suite (unit + smoke wiring)
├── smoke_test.py             # End-to-end wiring check (upload → overnight → query)
├── test_analytics.py · test_cli.py
│
├── .env.example · setup.sh · vps-reference.md
├── voice-journal-debrief.service / .timer   # systemd units for the morning email
└── IMPROVEMENT_PLAN*.md      # historical implementation plans (done)
```

---

## Scripts

### `voice_journal.py`

| Mode | Trigger | What it does |
|---|---|---|
| `--mode upload` | per upload (receiver) | transcribe → `extract_all` → write Notion/GCal → buffer → ntfy push |
| `--mode overnight` | 02:00 timer | consolidate the day's buffer → journal MD → Notion (no re-extraction) |

Both modes hold a `flock` pipeline lock so concurrent uploads can't double-write or
corrupt the buffer. Upload writes are real-time; the overnight pass also retries any
upload-time writes that failed.

### `weekly_report.py`

Sunday. Fetches recent workout + journal data and produces an AI coaching report with:
estimated 1RMs (Epley), top-set progression chart, a **two-axis bodyweight × strength**
chart, muscle-group pie, **PR detection**, **plateau flags** (flat e1RM, optionally with
rising RPE), **gap alerts** (untrained muscle groups), a **bad-sleep correlation** line,
and **planned-vs-actual adherence** (hit / beat / missed against the daily plan). Posts to
a Notion page, exports `reports/workouts.xlsx`, emails HTML.
Options: `--weeks N`, `--dry-run`, `--preview`, `--excel`, `--excel-all`.

### `debrief/main.py`

Daily 05:30. Collects 8 sources + yesterday's workout (same-exercise rows merged, with
🏆 PR lines), **task-aging** ("open 12 days, still relevant?"), and — when
`workout_plan.json` is present — a full **"Today's session"** plan (the next split in your
cycle with a per-exercise target); otherwise it falls back to a one-line split-rotation
suggestion. Synthesizes a TL;DR, renders + sends HTML.
Options: `--dry-run`, `--preview`, `--collect`.

### `healthcheck.py`

Daily 08:00 self-test. All green → one log line, no email. Any failure → a single
high-priority ntfy push listing what's broken.

### `cli.py`

Interactive menu: process inbox, overnight run, weekly report/preview, debrief
send/preview, view inbox/buffer/logs, provider diagnostics, journal search, cleanup.

---

## Daily session planner

Deterministic (no LLM). Configured in `workout_plan.json`:

- **Cycle** — a completion-driven rotation (e.g. `Chest → Deadlift → Squat`). "Next
  session" is the successor of the most recent *completed* in-cycle session; missing a day
  never advances it, and off-cycle Arms/Other sessions are ignored (`analytics.next_split`).
- **Templates** — a fixed exercise list per split, with **keyword slots** that tolerate
  variations (squat↔hack-squat, row↔machine row). Matching uses word-start boundaries +
  longest-keyword-wins, so `wrist curl`→Forearms but `narrow grip`≠Rows
  (`analytics.match_slot`).
- **Plan** — for the next split, each slot's most-recent variation is fed to
  `recommend_progression` for a target (`analytics.build_session_plan`). Surfaced in the
  05:30 debrief and as an ntfy push.
- **Adherence** — `analytics.score_adherence` recomputes, per past session, what *would*
  have been suggested and compares to what was done (hit/beat/missed); summarized in the
  weekly report. Recomputed each run, stores nothing.

`Session` labels are classified from the **exercises present** (`analytics.classify_session`:
bench→Chest, deadlift→Deadlift, real squat→Squat, accessories-only→Arms), so the cycle
resolver works. `backfill_sessions.py` relabels historical rows the same way (dry-run by
default; `--apply` to write; idempotent).

---

## Configuration

Single `.env` at `/opt/voice-journal/.env`:

```
# Core
GROQ_API_KEY=
UPLOAD_TOKEN=
WHISPER_MODEL=whisper-large-v3-turbo   # whisper-large-v3 = accuracy upgrade path
ANTHROPIC_API_KEY=                     # optional; Claude used if set
GOOGLE_API_KEY=                        # also GEMINI_API_KEY
AI_PROVIDER=auto                       # or claude|gemini|llama

# Notion
NOTION_TOKEN=                          # also NOTION_API_KEY
NOTION_DATABASE_ID=                    # journal DB; also NOTION_JOURNAL_DB_ID
NOTION_WORKOUT_DB_ID=
NOTION_TASK_DB_ID=
NOTION_BODYWEIGHT_DB_ID=
NOTION_METRICS_DB_ID=                  # Daily metrics DB (sleep/energy)
NOTION_TRAINER_PAGE_ID=

# Notifications (optional — empty = off)
NTFY_TOPIC=                            # your unique ntfy.sh topic
NTFY_SERVER=https://ntfy.sh

# Morning Debrief
SMTP_HOST= / SMTP_PORT=587 / SMTP_USER= / SMTP_PASSWORD= / EMAIL_FROM= / EMAIL_TO=
LATITUDE= / LONGITUDE= / TIMEZONE=Europe/Warsaw / LOCATION_NAME=
GOOGLE_CREDENTIALS_FILE=/opt/voice-journal/debrief/service-account.json
TASK_AGING_DAYS=7
```

`SMTP_PASSWORD` must be an **app-specific password**. Values with spaces don't need
quotes in `.env`; if you quote, balance them — an unterminated quote silently swallows
later lines.

The Notion DBs requiring manual schema: Workout Log needs `RPE` (number) + `Pain note`
(rich text); a `Daily metrics` DB needs `Date`, `Sleep` (good/ok/bad), `Energy`
(high/normal/low), `Note`. Code degrades gracefully when an id/property is absent.

The daily planner reads `workout_plan.json` from the project root (override with
`PLAN_CONFIG_PATH`); if it's missing or invalid, the planner is simply skipped.

---

## AI Provider Fallback

`ai_client.py` tries **Claude → Gemini → Llama (Groq)**; first available key wins, with a
unified retry loop (3 attempts on 429/5xx/network) across all three. Pin with
`AI_PROVIDER`. Extraction calls run at `temperature=0`; journal prose at 0.3.

---

## Deployment

Use the one-shot script from your Mac — it pushes the whole tree consistently and never
touches secrets or runtime data (`.env`, `venv/`, `inbox/`, `buffer/`, `archive/`,
`reports/`, logs, tokens):

```bash
./deploy.sh            # uses SSH alias "vps"; override: ./deploy.sh user@host
```

It stages to `/tmp/vj-deploy`, installs with `sudo rsync` into `/opt/voice-journal`,
fixes ownership, restarts the receiver, and runs the smoke test on the box.

> Avoid copying individual files — mismatched versions (e.g. a new `voice_journal.py`
> against an old `pipeline/config.py`) cause runtime `AttributeError`s. Deploy the tree.

---

## Systemd Timers

| Timer | Time | Command |
|---|---|---|
| `voice-journal-process.timer` | 02:00 daily | `voice_journal.py --mode overnight` |
| `voice-journal-debrief.timer` | 05:30 daily | `debrief/main.py` |
| `voice-journal-weekly.timer` | 06:30 Sunday | `weekly_report.py` |
| `voice-journal-healthcheck.timer` | 08:00 daily | `healthcheck.py` |

```bash
sudo systemctl list-timers | grep voice-journal   # check schedule
sudo systemctl start voice-journal-process        # trigger manually
```

---

## Testing

```bash
python3 -m pytest tests/ test_analytics.py test_cli.py -q   # unit suite
python3 smoke_test.py                                       # end-to-end wiring
```

The smoke test exercises the full chain on canned data: upload → Notion writes (incl. RPE
/ pain / bodyweight-vs-bench disambiguation) → overnight journal (asserting no extra
workout-extraction call) → query memo isolation + answer push.
