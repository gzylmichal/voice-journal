# Changelog

Summary of everything that changed since the initial commit (`67ead2c`).
**39 commits · 48 files · +6,450 / −314.** Baseline (Plan 1: transcription quality,
bodyweight false-positive fixes, raw-transcript audit) was already in the initial commit;
this log covers Plan 2 (efficiency/safety/feedback) and Plan 3 (features).

---

## Plan 2 — efficiency, safety, feedback, cleanup

**Unified extraction (D).** Replaced four separate LLM calls (workout, tasks, events,
bodyweight) with a single `extract_all` pass returning one JSON object. One shared JSON
parser; the four old functions kept as thin wrappers. Lower cost/latency and the
categories no longer compete for the same numbers.

**Concurrency safety (E1).** Added an `flock`-based pipeline lock (`pipeline/lock.py`)
around both upload and overnight modes, so two memos uploaded seconds apart can't
double-write Notion or corrupt the buffer. Empty transcripts are skipped.

**No re-extraction overnight (E2).** The overnight pass now builds the journal's workout
table from the buffered data (`merge_buffered_workouts`) instead of calling the LLM
again — it only falls back to extraction in legacy (no-buffer) mode.

**Feedback push (F + N0).** New `pipeline/notify.py`: an ntfy.sh transport plus
`send_batch_summary`, sent at the end of each upload (workout/tasks/bodyweight summary +
transcript snippet, with a "BW rejected" case). Never raises; off when `NTFY_TOPIC` empty.

**Cleanup (G).** Fixed `MUSCLE_GROUP_RULES` ordering (leg/wrist curls no longer
misclassified as biceps); `ai_client` imports config constants instead of re-reading env;
extraction calls pinned to `temperature=0`; unified retry loop across all three providers;
`WHISPER_MODEL` env-overridable; docstring + stale-test fixes.

---

## Plan 3 — features

**H · Pre-workout brief.** `pipeline/brief.py` pushes last session's numbers + a
progression target when the first workout of the day is logged. Recommendations are
**deterministic** (`analytics.recommend_progression`) — never the LLM — using
double-progression rules, lower-body +5 kg, bodyweight/loaded handling, gap detection,
and RPE/pain hooks. New `fetch_prior_workout_session` finds the comparison day by
exercise overlap.

**I · RPE + pain flags.** Extraction schema gained per-exercise `rpe` and `pain_note`
(filled only on clear effort/pain cues, PL+EN). Written to the Workout DB only when
present (old rows unaffected). Weekly report flags **flat e1RM + rising RPE** and repeated
pain on the same body part. *(Requires Workout DB props `RPE`, `Pain note`.)*

**J · Sleep/energy.** New top-level `metrics` (qualitative sleep/energy/note — never
hours). Keyword pre-filter + once-per-day guarded write to a new **Daily metrics** Notion
DB. Weekly report adds a bad-sleep × top-set correlation line. Buffer keys are additive
(old buffers still load). *(Requires `NOTION_METRICS_DB_ID` + the Daily metrics DB.)*

**K · Coaching upgrades.** `analytics.detect_prs` (weight + rep PRs); 🏆 PR lines in the
debrief; plateau flags (flat/declining e1RM 3+ weeks); gap alerts for untrained muscle
groups; two-axis **bodyweight × strength** SVG with a recomposition callout.

**L · Debrief upgrades.** Task-aging section (open ≥ `TASK_AGING_DAYS`, cap 3, oldest
first) via new `task_collector.py`; today's training suggestion from split rotation
(days-since fallback when unclear). Both LLM-free.

**M · Voice queries.** New top-level `query`; a history-question memo is **isolated** —
no journal, no Notion writes — and answered (1–2 lines, strictly from fetched Workout
rows) via ntfy. Honest "no records" on missing data; failures never lose the memo.

---

## Infrastructure & docs

- `healthcheck.py` — 08:00 daily self-test; ntfy push only on failure.
- `deploy.sh` — one-shot consistent deploy (rsync, protects `.env`/`venv`/runtime data),
  replacing error-prone file-by-file `scp`.
- `voice-journal-debrief.service` / `.timer` — systemd units for the morning email.
- README rewritten to match the current system.
- Test suite grew to ~300 tests + a full end-to-end `smoke_test.py`.

---

## Manual setup that must exist (code degrades gracefully if absent)

- Workout DB: `RPE` (number), `Pain note` (rich text).
- Daily metrics DB: `Date`, `Sleep` (good/ok/bad), `Energy` (high/normal/low), `Note`;
  `NOTION_METRICS_DB_ID` in `.env`.
- `NTFY_TOPIC` in `.env` to enable pushes.
