# Voice Journal VPS

Record throughout the day → VPS processes at **02:00 CET/CEST** → Notion entry ready for morning debrief.

```
iPhone                              Hetzner VPS (YOUR_VPS_IP)
┌──────────────┐                    ┌──────────────────────────────────────┐
│ iOS Shortcut │                    │ nginx (80/443)                       │
│ Record memo  │──── HTTPS POST ───►│ ↓                                    │
│ (any time)   │                    │ receiver.py (gunicorn :8675)         │
└──────────────┘                    │  saves .m4a → inbox/                 │
                                    │                                      │
                                    │ 02:00 CET — systemd timer            │
                                    │ voice_journal.py --mode overnight    │
                                    │  Groq Whisper → transcribe           │
                                    │  Claude/Gemini → format + extract    │
                                    │  → .md archive + Notion entry        │
                                    │                                      │
                                    │ 06:30 daily — systemd timer          │
                                    │ debrief/main.py                      │
                                    │  8 collectors (weather, calendar,    │
                                    │  news, crypto, AQI, history …)       │
                                    │  Gemini TL;DR → HTML email           │
                                    │                                      │
                                    │ 06:30 Sunday — systemd timer         │
                                    │ weekly_report.py                     │
                                    │  Workout analytics + journal digest  │
                                    │  → Notion page + Excel + HTML email  │
                                    └──────────────────────────────────────┘
```

---

## Project Structure

```
voice_journal_vps/
│
├── voice_journal.py          # Main pipeline: upload (daytime) + overnight consolidation
├── receiver.py               # Flask/gunicorn endpoint that accepts audio POSTs
├── weekly_report.py          # Sunday coaching report (analytics, charts, email)
├── cli.py                    # Interactive terminal menu (questionary + rich)
├── ai_client.py              # Provider abstraction: Claude → Gemini → Llama fallback
├── analytics.py              # Workout analytics engine (e1RM, adherence, volume)
├── models.py                 # parse_workout_entry — Notion page → typed dict
├── backfill_workouts.py      # Reprocess historical audio to fill Notion workout DB
├── gcal_auth.py              # One-time OAuth setup for Google Calendar
│
├── pipeline/                 # Voice journal sub-modules
│   ├── config.py             # All env vars and path constants
│   ├── audio.py              # Groq Whisper transcription
│   ├── journal.py            # Format transcripts → markdown journal entry
│   ├── extractors.py         # Extract workouts, tasks, calendar events from text
│   ├── prompts.py            # All LLM prompts (journal, workout, tasks, events)
│   ├── notion_client.py      # Notion DB writes + bodyweight fetch
│   ├── gcal_client.py        # Google Calendar event creation
│   └── storage.py            # Buffer (daily JSON) read/write + markdown archive
│
├── debrief/                  # Morning Debrief email system
│   ├── main.py               # Entry point: collect → synthesize → render → send
│   ├── config.py             # Reads parent .env with dual key-name fallbacks
│   ├── formatter.py          # HTML email renderer (all sections)
│   ├── sender.py             # SMTP send (Zoho)
│   ├── synthesis.py          # Gemini TL;DR + weekly snapshot generation
│   └── collectors/
│       ├── weather.py        # Open-Meteo current conditions + forecast
│       ├── calendar_collector.py  # Google Calendar via service account JSON
│       ├── notion_collector.py    # Today's Notion journal entry (blocks → HTML)
│       ├── news.py           # RSS feeds (feedparser)
│       ├── currency.py       # Fiat FX rates
│       ├── binance_collector.py   # Crypto prices
│       ├── airquality_collector.py  # Open-Meteo European AQI, PM2.5, PM10
│       ├── history_collector.py   # "On this day" events (muffinlabs API)
│       └── workout_collector.py   # Notion Workout DB (today + weekly)
│
├── tests/                    # pytest suite
├── test_analytics.py         # Analytics unit tests (root, run: pytest test_analytics.py)
├── test_cli.py               # CLI unit tests
│
├── .env.example              # Template for all required keys
├── vps-reference.md          # Server details, SSH config, deploy commands
└── setup.sh                  # First-time VPS provisioning script
```

---

## Scripts

### `voice_journal.py`

| Mode | Trigger | What it does |
|---|---|---|
| `--mode upload` | CLI / manual | Transcribes inbox audio → buffers to daily JSON |
| `--mode overnight` | 02:00 timer | Consolidates buffer → journal MD → Notion + archive |

Overnight extracts: workout entries → Notion Workout DB, tasks → Notion Task DB, calendar events → Google Calendar.

### `weekly_report.py`

Runs every Sunday. Fetches last 4 weeks of workout data + journal entries, runs AI coaching analysis, then:
- Posts formatted report to a Notion trainer page
- Exports full workout history to `reports/workouts.xlsx`
- Sends HTML email with: estimated 1RMs (Epley), top-set progression SVG chart, muscle group pie chart, AI analysis

Options: `--weeks N`, `--dry-run`, `--preview` (writes `weekly-preview.html`), `--excel`, `--excel-all`

### `debrief/main.py`

Runs daily at 06:30. Collects 8 data sources in sequence, synthesizes a TL;DR via Gemini, renders HTML, sends email.

Sources: weather, calendar, Notion journal, news, currency, crypto, air quality, "on this day"  
Also fetches today's (or yesterday's) workout and shows it as a table above the journal notes.

Options: `--dry-run` (HTML to stdout), `--preview` (writes `debrief-preview.html`)

### `cli.py`

Interactive menu. Run `python3 cli.py` on the VPS (or `ssh vps` then `python3 /opt/voice-journal/cli.py`).

Actions available: process inbox, overnight run, weekly report, debrief send/preview, weekly review send/preview, view inbox/buffer/logs, provider diagnostics, journal search, archive cleanup.

---

## Configuration

Single `.env` at project root (`/opt/voice-journal/.env`):

```
# Voice Journal
GROQ_API_KEY=
UPLOAD_TOKEN=
NOTION_TOKEN=                    # also accepted as NOTION_API_KEY
NOTION_DATABASE_ID=              # journal DB; also NOTION_JOURNAL_DB_ID
NOTION_WORKOUT_DB_ID=
NOTION_TASK_DB_ID=
NOTION_BODYWEIGHT_DB_ID=
NOTION_TRAINER_PAGE_ID=          # weekly report posts here
ANTHROPIC_API_KEY=               # optional; Claude used if set
GOOGLE_API_KEY=                  # also GEMINI_API_KEY

# Morning Debrief
SMTP_HOST=
SMTP_PORT=587
SMTP_USER=
SMTP_PASSWORD=
EMAIL_FROM=
EMAIL_TO=
LATITUDE=
LONGITUDE=
TIMEZONE=Europe/Warsaw
LOCATION_NAME=
GOOGLE_CREDENTIALS_FILE=/opt/voice-journal/debrief/service-account.json
BINANCE_SYMBOLS=BTCUSDT,ETHUSDT
CURRENCY_CODES=USD,EUR,GBP
NEWS_SOURCES=5
NEWS_ITEMS_PER_SOURCE=3
```

`debrief/config.py` reads this via `python-dotenv` with dual key-name fallbacks so both old and new names work.

---

## AI Provider Fallback

`ai_client.py` tries providers in order: **Claude → Gemini → Llama (Groq)**. First available key wins. Set `AI_PROVIDER=claude|gemini|llama` in `.env` to pin a specific one.

Weekly report uses Claude for the coaching analysis when available (better reasoning for prescriptive advice); falls back to Gemini.

---

## Deployment

Files are owned by `journal:journal` on VPS. Deploy workflow:

```bash
# From Mac
scp <file> YOUR_USER@YOUR_VPS_IP:/tmp/

# On VPS (run with ! prefix in Claude Code, or SSH in)
sudo cp /tmp/<file> /opt/voice-journal/<path>
sudo chown journal:journal /opt/voice-journal/<path>
```

The `debrief/` subdirectory lives at `/opt/voice-journal/debrief/` and shares the same venv (`/opt/voice-journal/venv/`).

---

## Systemd Timers

| Timer | Time | Command |
|---|---|---|
| `voice-journal-process.timer` | 02:00 daily | `voice_journal.py --mode overnight` |
| `voice-journal-debrief.timer` | 06:30 daily | `debrief/main.py` |
| `voice-journal-weekly.timer` | 06:30 Sunday | `weekly_report.py` |

```bash
sudo systemctl list-timers | grep voice-journal   # check schedule
sudo systemctl start voice-journal-process        # trigger manually
```

---

## Key Data Flows

**Workout data** lives in two places:
- **Notion Workout DB** — source of truth, written by `voice_journal.py overnight` + `backfill_workouts.py`
- Read by: `weekly_report.py` (analytics + charts), `debrief/collectors/workout_collector.py` (today's table in debrief email)

**Journal data** lives in:
- **Notion Journal DB** — written by `voice_journal.py overnight`
- Read by: `debrief/collectors/notion_collector.py` (today's entry), `weekly_report.py` / `fetch_journal_entries()` (weekly digest)

**Google Calendar**:
- Written by: `voice_journal.py` (extracts events from transcripts via `pipeline/gcal_client.py`)  
- Read by: `debrief/collectors/calendar_collector.py` (uses service account JSON, not OAuth token)
