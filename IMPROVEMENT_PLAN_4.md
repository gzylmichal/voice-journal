# Voice Journal — Improvement Plan 4: Daily session planner + adherence

Goal: each training day, produce a **full prescribed session** for the next split —
every slot with a target derived from last time — and report **planned-vs-actual
adherence** (plus existing trends) in the weekly.

Read `CLAUDE.md` first. Same gate every phase:

```bash
python3 -m pytest tests/ test_analytics.py test_cli.py -q
python3 smoke_test.py
```

One phase per session, one commit per sub-item, **stop and report after each phase**.

---

## Design (decided with the owner)

**Rotation is completion-driven, not calendar-based.** Fixed cycle
`Chest → Deadlift → Squat → Chest …`, rest day between. "Next session" = the
successor of the **most recent completed session** whose `Session` is in the cycle.
Missing a day never advances the cycle; an **Arms** (or `Other`) session is off-cycle
and is ignored for advancement. No state stored — recomputed from the Workout DB each run.

**Templates are fixed per split, with variation slots** (keyword-matched, since the owner
swaps variations). Stored in `workout_plan.json` (see seed file). Slot types:
- `main` — a named lift with `match` keywords (e.g. Squat slot matches `squat`,
  `hack-squat`). Progression follows whichever variation was done most recently.
- `accessory` — an open muscle slot (Biceps/Triceps/Forearms): a reminder, with
  last-done numbers + progression only if that specific accessory has ≥2 sessions.

**Per-slot target = existing `analytics.recommend_progression`** — no new progression
math, no LLM. Slots with <2 prior sessions show last numbers only (never an invented
target), exactly as today.

**Delivery:** a "Today's session" section in the 05:30 debrief, plus an optional ntfy push.

**Weekly = both:** adherence (recompute what each performed exercise *would* have been
suggested from its prior session, compare to the actual top set → hit / missed / beat)
**and** the existing e1RM / PR / plateau trends. Adherence needs **no storage** — it's
deterministic from history, like `detect_prs`.

---

## Manual setup (owner)

- Fill in / edit `workout_plan.json` (seeded from your templates — see the file).
  Code must **degrade gracefully** if it's missing or malformed: log info, skip the
  planner, change nothing else.
- No Notion schema changes. No new env vars (optional: `PLAN_CONFIG_PATH`,
  default `workout_plan.json`).

---

## Phase N1 — cycle resolver + plan config (foundation, pure functions)

1. `pipeline/plan_config.py`: load + validate `workout_plan.json` (cycle list,
   per-split slot templates). Missing/invalid → return `None`, log info. No raise.
2. `analytics.next_split(entries, cycle) -> str|None`: most recent session whose
   `Session` ∈ cycle → return its successor (wraps). Off-cycle sessions (Arms/Other)
   ignored. No history → `cycle[0]`.
3. `analytics.match_slot(exercise_name, slots) -> slot|None`: case-insensitive match.
   **Word-start boundary, NOT raw substring:** a keyword matches only when it begins at a
   word boundary in the name (regex `\b` + escaped keyword). This catches plurals/casing
   (`tricep`→"Triceps Pushdown", `pull-up`→"Pull-ups", `curl`→"Hammer Curls") while
   rejecting accidental substrings (`row` must NOT match "na**rrow** grip pulldown").
   **Collision rule:** when an exercise matches more than one slot, the slot whose
   *matched keyword is longest* wins (same principle as the G1 `MUSCLE_GROUP_RULES`
   length-sort) — so `wrist curl`→Forearms (not Biceps via "curl"), `cable curl`→Biceps,
   `preacher curl`→Biceps.
Tests (`test_analytics.py`): next_split for each position + wrap; off-cycle ignored;
empty history → first; real-name matches from the DB (Smith Machine Bench Press→Bench,
Overhead Barbell Press→Overhead Press, Triceps Pushdown→Triceps, Pull-ups→Pull-ups,
Leg Extension→Leg extension); variations (squat↔hack-squat, machine row→Rows);
**boundary case `narrow grip pulldown` must NOT match Rows**; **collision cases
(wrist curl→Forearms, cable curl→Biceps, preacher curl→Biceps)**.
**Gate. Commit.**

## Phase N2 — daily session-plan builder + delivery

1. `analytics.build_session_plan(entries, split, template) -> list[slot_plan]`: for each
   slot, find the most recent matching exercise, pull its last session, run
   `recommend_progression`; accessory slots with no/﹤2 history → reminder only. Pure
   function, no I/O, no LLM.
2. Render a compact plan, e.g.
   `Chest day → Bench 75×5 (last 70×5) · Pull-ups +1 rep (last BW×8) · Bulgarian SS 22.5×8
   (last 20×8) · Triceps + Biceps`.
   Reuse `extractors._sets_detail_summary` for the numbers.
3. Deliver: new debrief collector/section `Today's session` (gracefully omitted when no
   plan/config). Optional dedicated ntfy push via `pipeline/notify.send_notification`.
Tests (`tests/test_session_plan.py`): plan from canned history (main + accessory +
variation-swap + too-few-sessions); debrief section renders / omits cleanly; push attempted.
**Gate. Commit.**

## Phase N3 — weekly adherence + trends

1. `analytics.score_adherence(entries, window_days, templates) -> dict`: for each session
   in the window, for each performed exercise, recompute the suggestion from its prior
   same-slot session and compare to the actual top set → `hit` / `missed` / `beat`.
   Deterministic, stores nothing.
2. `weekly_report.py`: add an adherence summary line/section (e.g. `Adherence: 7/9 lifts
   hit target, 2 beat`) **alongside** the existing e1RM / PR / plateau trends. No-op
   cleanly when there's no plan config or not enough data.
Tests: adherence scoring (hit/miss/beat, not-enough-data → skipped); weekly renders the
line only when data present.
**Gate. Commit.**

---

## Explicitly NOT in scope
- No LLM in planning or scoring (deterministic, same philosophy as Phases H/K).
- No Notion schema changes; no buffer changes.
- No auto-editing of `workout_plan.json` from history (optional future bootstrap).

## Rollout
Low risk (read-only analytics + one debrief section + one weekly section). Branch
optional. Deploy via `./deploy.sh`; verify the debrief shows "Today's session".
