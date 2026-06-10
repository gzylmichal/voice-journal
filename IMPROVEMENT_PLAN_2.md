# Voice Journal — Improvement Plan 2

Follow-up to IMPROVEMENT_PLAN.md (done). Read `CLAUDE.md` first — it defines the
contracts and the definition of done. Every phase below ends with the same gate:

```bash
python3 -m pytest tests/ test_analytics.py test_cli.py -q   # all pass
python3 smoke_test.py                                        # all checks pass
```

Implement phases in order, one commit per phase, **stop and report after each
phase** rather than barreling through if anything is off. Phases D and E change
core data flow — they are the risky ones. F and G are low-risk.

---

## D. Unified extraction — one LLM call instead of four

**Why:** `extract_workout`, `extract_tasks`, `extract_calendar_events`, and
`extract_bodyweight` each call the LLM separately over the same transcripts
(4x cost/latency) with copy-pasted JSON-fence stripping. Separate extractors
also compete for the same numbers — the original bodyweight bug.

**What:**

1. New `EXTRACTION_SYSTEM_PROMPT` in `pipeline/prompts.py` combining the four
   existing prompts into one schema:
   `{"workout": {...}, "tasks": [...], "events": [...], "bodyweight": {...}}`.
   Keep every existing rule (PL/EN examples, negative rules, sets_detail rules,
   weigh-in rules). Add one cross-cutting rule: *each number belongs to exactly
   one category; a weight in an exercise context is never a bodyweight.*
2. New `extract_all(transcripts, recording_date) -> dict` in
   `pipeline/extractors.py` with ONE shared `_parse_json_response(raw)` helper
   (fence stripping + json.loads + type check) replacing the 4 copies.
3. **Keep the four existing functions as thin wrappers** that call
   `extract_all` (or accept its result) — so `cli.py`, `backfill_workouts.py`,
   and tests keep working. Do not delete them.
4. Keep the A1 bodyweight keyword pre-filter: if no weigh-in phrase is present,
   force `bodyweight: {"detected": false}` regardless of what the model said.
   Keep `validate_bodyweight` exactly where it is.
5. `voice_journal.run_upload_mode` calls `extract_all` once; buffer/pending_writes
   schema unchanged (same four keys).
6. Use `temperature=0` for this call.

**Out of scope:** provider tool-use/structured-output APIs (ai_client touches
three providers — too risky here; see G for the minimal ai_client fixes).

**Tests:** new `tests/test_extract_all.py` — canned combined JSON → all four
sub-results parsed; malformed JSON → safe empty defaults per category; the
"80 kg bench + no weigh-in phrase" case → bodyweight not detected even if the
model returns it. Update `smoke_test.py` CANNED_AI: add the combined label,
keep old labels for the wrapper paths.

---

## E. Concurrency safety + stop re-extracting overnight

**E1. Lock the pipeline.** `receiver.py` spawns a new `--mode upload` process
per upload with no lock. Two memos uploaded seconds apart → two concurrent
processes scanning the same inbox and read-modify-writing the same buffer JSON
(duplicate Notion rows, lost buffer data).

- Add an `fcntl.flock`-based exclusive lock (`buffer/.pipeline.lock`) around the
  body of `run_upload_mode` AND `run_overnight_mode`. Non-blocking attempt with
  retry: wait up to ~120 s (upload memos are short), then exit cleanly with a
  log line — the file stays in the inbox and the next trigger picks it up.
- Small helper `pipeline/lock.py` with a context manager; test with two
  processes via `multiprocessing` in `tests/test_lock.py`.

**E2. Reuse buffered extraction overnight.** `run_overnight_mode` currently
re-calls `extract_workout` over the whole day just to build the journal table —
an extra LLM call that can disagree with what was already written to Notion.

- Build the day's workout table from `pending_writes` entries (merge exercises
  from all batches of the day) instead of re-extracting. Only fall back to a
  fresh `extract_workout` in legacy mode (no buffer).
- `format_workout_table` already takes a workout dict — write a small
  `merge_buffered_workouts(pending_writes) -> dict` with unit tests (two batches
  same exercise → merged; empty → `{"detected": False}`).

**Gate:** standard gate, plus `smoke_test.py` must show the overnight stage
passing with NO `Workout extraction` AI call (assert via the canned-AI call log
if convenient).

---

## F. Feedback loop — push confirmation after each upload batch

**Why:** the system is fire-and-forget; mistakes surface the next morning. A
push notification after each batch builds trust and catches bad extractions in
minutes, not days.

**What:**

1. [ntfy.sh](https://ntfy.sh) publish via plain `requests.post` (no new deps).
   Config in `pipeline/config.py`: `NTFY_TOPIC` (empty = feature off),
   `NTFY_SERVER` (default `https://ntfy.sh`). Document in `.env.example`.
2. New `pipeline/notify.py`: `send_batch_summary(workout, tasks, events,
   bodyweight, transcripts)` → short message like:
   `✓ Bench 80x8,80x8,82.5x6 → Workout DB · 1 task · BW 82.5 kg`
   plus the filtered transcript text (truncated ~500 chars) so mishearings are
   visible immediately. Failures log a warning, NEVER raise — notification must
   not break the pipeline.
3. Call at the end of `run_upload_mode` only (not overnight).

**Tests:** message formatting unit tests (workout-only, bodyweight-rejected
case shows `BW rejected: 95 kg vs last 82 kg`, empty batch sends nothing);
requests.post mocked; exception in notify does not propagate.

---

## G. Cleanup — small, independent fixes

1. **`MUSCLE_GROUP_RULES` ordering bug** (`pipeline/extractors.py`): `("curl",
   "Biceps")` matches before `("leg curl", "Legs")` and `("wrist curl",
   "Forearms")` — leg/wrist curls are misclassified as Biceps, skewing the
   weekly pie chart. Sort rules by keyword length descending at module load (or
   reorder the list) + regression tests for "leg curl", "wrist curl", "hammer
   curl", "lat pulldown".
2. **`ai_client.py` config duplication:** it re-reads env vars that
   `pipeline/config.py` owns. Import the constants from `pipeline.config`
   instead (config has no import back to ai_client, so no cycle). Behavior
   identical.
3. **Extractor temperature:** extraction calls pass `temperature=0`
   (journal prose keeps the 0.3 default).
4. **Unify retries in `ai_client.py`:** the Gemini-only retry loop becomes a
   small `_with_retries(fn)` applied to all three providers (same constants:
   3 attempts, 10 s, on 429/500/503 and network errors).
5. **`WHISPER_MODEL` env-overridable** in `pipeline/config.py`:
   `os.getenv("WHISPER_MODEL", "whisper-large-v3-turbo")`. Note in README that
   `whisper-large-v3` is the accuracy upgrade path.
6. **Stale docstring:** `storage.mark_written` — add `bodyweight` to the list of
   valid resources.
7. **Debrief code-block rendering (optional):** `debrief/formatter.py:render_notion`
   ignores `code`-type blocks, so any code block in the day's Notion journal entry
   is silently dropped from the debrief email. Two tests in
   `tests/test_morning_debrief.py` are skipped because of this — they were written
   against the old standalone morning-debrief project, which had this feature.
   Either render code blocks as escaped `<pre>` (then un-skip the tests) or, if
   the workout-collector table makes this redundant, delete the skipped tests.
   Ask the owner which.

Each item is its own commit. If any one turns out to be larger than it looks —
stop and report instead of improvising.

---

## Explicitly NOT in scope

- No provider structured-output/tool-use migration.
- No changes to `debrief/` or `weekly_report.py` beyond what G1 touches
  (`infer_muscle_group` is imported by analytics — run `pytest test_analytics.py`).
- No Notion schema changes, no renaming of DB properties.
- No voice-correction intent ("scratch that") — future plan, needs design.

## Deployment

After all phases: copy changed files to `/opt/voice-journal/` per README deploy
workflow, then on the VPS run the full gate (`pytest` + `python3 smoke_test.py`)
and send one real test memo end-to-end.
