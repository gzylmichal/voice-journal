# Voice Journal — Improvement Plan

Plan for Claude Code. Two problem areas: (A) bodyweight false positives, (B) transcription quality. Plus (C) raw-transcript auditing. Implement in order; each phase is independently deployable.

---

## A. Bodyweight extraction — stop logging exercise weights as bodyweight

**Root cause:** `extract_bodyweight()` (pipeline/extractors.py) runs on every memo batch, including workout memos full of "80 kg x 8". `BODYWEIGHT_SYSTEM_PROMPT` (pipeline/prompts.py) has no instruction to ignore exercise loads, and there is no validation before `store_bodyweight()` writes to Notion (voice_journal.py:170, overnight retry ~line 275).

### A1. Keyword pre-filter (cheap, before any LLM call)

In `extract_bodyweight()`, skip the LLM entirely unless at least one transcript contains an explicit weigh-in phrase (case-insensitive):

- English: `i weigh`, `my weight`, `weighed myself`, `body weight is`, `bodyweight is`, `on the scale`, `scale says`
- Polish: `ważę`, `zważyłem`, `zważyłam`, `moja waga`, `waga wynosi`, `na wadze`

Return `{"detected": False}` if no phrase matches. Put the phrase list in a module constant so it's easy to extend.

### A2. Harden the prompt

Rewrite `BODYWEIGHT_SYSTEM_PROMPT`:

- Add explicit negative rules: weights spoken in the context of an exercise (bench, squat, dumbbell, "x reps", sets) are NEVER bodyweight. Workout memos must return `{"detected": false}` unless the speaker explicitly says they weighed *themselves*.
- Add Polish examples (memos are PL/EN mixed): `"Ważę dzisiaj 82 i pół" → {"detected": true, "weight_kg": 82.5}`; `"Wyciskanie 80 kilo, 8 powtórzeń" → {"detected": false}`.
- Add a negative example with a full workout memo.

### A3. Plausibility validation before write

New function `validate_bodyweight(weight_kg, recording_date) -> bool` in extractors or notion_client:

1. Hard range: reject outside 40–250 kg.
2. Fetch last known weight via `fetch_latest_bodyweight()`; if present, reject if `abs(new - last) > 5%` of last (a real human doesn't jump >5% day-to-day). Log a warning with both values when rejecting.
3. If no previous weight exists, accept within hard range.

Apply in **both** write paths: upload mode (voice_journal.py ~line 170) and overnight retry (~line 275). The retry path currently re-writes buffered `bodyweight` without any validation — fix that too.

### A4. Tests

Extend `tests/test_bodyweight.py`:

- Pre-filter: workout-only transcript → no LLM call (assert `ai_client.call_ai` not called), weigh-in phrase → LLM called. Polish phrases too.
- Validation: 80→81 accepted; 80→95 rejected; 300 rejected; no-history within range accepted.
- Prompt content: assert negative-rule keywords present.

---

## B. Transcription quality — reduce mis-hearing and invented content

**Root causes** (pipeline/audio.py):

1. The Whisper `prompt` includes literal example numbers ("60 kg, 70 kg … 3 powtórzenia, 5 powtórzeń, 3 serie, 4 serie…"). Whisper treats the prompt as preceding context and is biased to *reproduce* those exact phrases — a documented hallucination/substitution cause. This is the most likely source of "infers and interprets incorrectly".
2. `response_format="text"` discards segment metadata, so hallucinations on silence/noise (classic Whisper failure) can't be filtered.
3. Denoise chain (`afftdn,highpass,dynaudnorm`) runs unconditionally and can smear clean speech.

### B1. Fix the Whisper prompt

Replace the prompt with vocabulary only — exercise names and units, **no numeric examples**:

```
Smith machine bench press, Bulgarian split squat, pull-ups, chin-ups, deadlift,
Romanian deadlift, leg press, cable row, lat pulldown, overhead press, dumbbell,
barbell, kg, reps, sets, bodyweight, kilograms, curls, extension, triceps, biceps, 
Hack-squat, squat, hamstrings, quad
```

Keep under ~200 tokens (Whisper truncates at 224). Make it a constant in `pipeline/config.py` (`WHISPER_PROMPT`), overridable via env var.

### B2. Segment-level filtering

- Switch to `response_format="verbose_json"`.
- Drop segments where `no_speech_prob > 0.6`, or `avg_logprob < -1.0`, or `compression_ratio > 2.4` (standard Whisper hallucination heuristics — tune constants in config).
- Drop known filler hallucinations when they are the *entire* segment: "Thank you.", "Thanks for watching", "Dziękuję", "Napisy stworzone przez społeczność Amara.org" etc. (constant list).
- Join remaining segment texts; behavior otherwise unchanged. Keep a `"text"` fallback if verbose_json fails.
- Log how many segments were dropped per file.

### B3. Explicit temperature

Pass `temperature=0` to the transcription call.

*(Not in scope per user choice: model upgrade to large-v3, LLM correction pass, conditional denoising. Leave `WHISPER_MODEL` as is but it's already env-overridable via config — note in README that `whisper-large-v3` is the accuracy upgrade path.)*

### B4. Tests

New `tests/test_audio.py` (mock Groq client):

- Prompt constant contains no digits.
- Segment filtering: high `no_speech_prob` segment dropped; normal segments joined; filler-only segment dropped.
- verbose_json failure falls back gracefully.

---

## C. Raw transcript archiving (audit trail)

- In `transcribe_file()`, return the raw joined text (pre-filtering) alongside filtered text: add `"raw_text"` key to the result dict.
- In `pipeline/storage.py`, when archiving audio (`archive_files`) or appending to buffer, also write `archive/transcripts/YYYY-MM-DD/<audio-stem>.txt` containing: filename, timestamp, raw Whisper text, filtered text, dropped-segment count. Create `ARCHIVE_TRANSCRIPTS_DIR` in config.
- Keep buffer JSON storing the *filtered* text (current behavior) so downstream is unchanged.
- Test: archiving writes the txt file with both raw and filtered text.

---

## Deployment notes

- Files live at `/opt/voice-journal/` on the VPS, owned by `journal:journal` (see vps-reference.md / README deploy section).
- Touched files: `pipeline/audio.py`, `pipeline/prompts.py`, `pipeline/extractors.py`, `pipeline/config.py`, `pipeline/storage.py`, `voice_journal.py`, tests.
- After deploy: run `pytest`, then trigger `--mode upload` manually with a test memo containing both a workout weight and a weigh-in phrase; verify only the weigh-in lands in the bodyweight DB.
- No schema changes to Notion DBs; no changes to debrief/ or weekly_report.py.

## Suggested commit sequence

1. `fix(bodyweight): keyword pre-filter + hardened prompt + plausibility validation` (A1–A4)
2. `fix(transcription): remove number-biased whisper prompt, add segment filtering` (B1–B4)
3. `feat(audit): archive raw transcripts alongside audio` (C)
