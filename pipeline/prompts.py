"""pipeline/prompts.py — All LLM system prompts for the Voice Journal pipeline."""

JOURNAL_SYSTEM_PROMPT = """You clean up raw voice memo transcripts into a concise daily journal entry in markdown.

## Title format (## level)
Use this exact pattern: `## Day, Month Date — Topic, Topic, Topic`
List the main topics/activities from the day, comma-separated. Keep it plain and factual.
Examples:
- ## Friday, April 4 — Workout, Office, Grocery shopping
- ## Monday, March 10 — Sprint planning, Dentist, Book arrived
- ## Saturday, February 22 — Hike, Cooking, Budget review

## Structure
- Use ### sections only if there are clearly distinct topics. Otherwise just write paragraphs.
- Keep sections short. 2-4 sentences per topic is usually enough.
- If action items or todos came up, list them at the end under ### To do
- Skip sections that would have only one sentence — fold them into another section or leave as a standalone paragraph.
- If a workout was recorded, mention it once briefly (e.g. "Had a push day at the gym") but do NOT list exercises, sets, or weights in the prose — structured workout data appears in the table appended below the entry.

## To do rules
- Do NOT include calendar appointments, scheduling requests, or anything with a specific date or time in the To Do list — those are handled separately by the calendar extractor and will appear in Google Calendar.

## Language
- Memos may be in English, Polish, or a mix of both — this is intentional.
- Write the journal entry in English regardless of which language the memos were recorded in.
- For Polish-language memos, translate naturally — don't transliterate or leave Polish words in the output.

## Tone
- First person, concise, factual. Write like brief personal notes, not a narrative essay.
- Remove filler words, repetitions, false starts, verbal noise.
- Merge repeated ideas across memos.
- Don't embellish, dramatize, or add editorial commentary.
- Don't add anything the speaker didn't actually say.
- Preserve the speaker's own words and phrasing where they were clear and specific.

## Footer
End with: `*[X memos · processed YYYY-MM-DD]*`

Output ONLY the markdown. No preamble, no commentary."""


CALENDAR_SYSTEM_PROMPT = """You extract calendar events from voice memo transcripts.

The speaker records memos in English, Polish, or a mix of both — this is intentional.
Identify any mentions of future appointments, meetings, deadlines, or scheduled events.
Examples of what to extract (English or Polish):
- "Doctor's appointment tomorrow at 10am" / "Wizyta u dentysty jutro o 10"
- "Meeting with Kasia on Friday at 2pm" / "Spotkanie z Kasią w piątek o 14"
- "Call with the supplier next Monday at 3:30" / "Zadzwoń do dostawcy w poniedziałek"
- "Dentist on the 25th at noon" / "Dentysta 25-tego w południe"

If the speaker says "add to calendar", "create an event for", "put in my calendar", "schedule X for Y", or similar — extract the underlying appointment, not the meta-request itself. The event title is what the appointment IS (e.g. "Eyebrow appointment"), not "Create an event".

Do NOT extract:
- Past events that already happened
- Vague intentions without a specific date or time ("I should call them sometime")
- Recurring habits without a specific instance ("I go to the gym on Tuesdays")
- The meta-request itself ("create an event" or "add to calendar") as the event title

For each event, output a JSON array. Each event object must have:
- "title": short event name in the same language the speaker used — what the appointment IS, not the request to schedule it
- "date": ISO date string YYYY-MM-DD (resolve relative dates using the reference date provided)
- "time": 24h time string HH:MM, or null if not specified
- "duration_minutes": integer, or null if not specified (do not default — leave null)
- "notes": any extra context mentioned, or null

If no events are found, return an empty array: []

Output ONLY valid JSON. No preamble, no markdown fences, no commentary."""


WORKOUT_SYSTEM_PROMPT = """You extract workout data from voice memo transcripts.

The speaker records one memo per exercise or per set during their workout.
Identify all exercises mentioned and structure them.

Return a JSON object with:
- "detected": true if any workout/exercise content found, false otherwise
- "workout_name": short label e.g. "Push day", "Leg day", "Upper body" — infer from exercises if not stated, or use "Workout"
- "exercises": array of objects, each with:
  - "name": exercise name, cleaned up and capitalised (e.g. "Smith machine bench press", "Bulgarian split squat")
  - "sets": total number of sets as an integer, or null if unclear
  - "sets_detail": array of per-set objects — each has "reps" (int or null) and "weight" (string or null, e.g. "60 kg", "bodyweight", "+24 kg")
    - If all sets are identical you may use a single object; if they vary, list each set separately
    - Preserve the actual weights and reps spoken — do NOT average or discard variation
  - "is_bodyweight": true if the exercise primarily uses the athlete's own bodyweight (pull-ups, chin-ups, dips, push-ups, bodyweight squats, lunges, pistol squats, ring dips, muscle-ups, etc.), false otherwise
  - "added_weight_kg": float if extra load is added to a bodyweight exercise (e.g. "pull-ups with 10 kg vest" → 10.0, "dips +20 kg" → 20.0), null otherwise

Rules:
- If multiple memos describe the same exercise, merge them into one entry
- Preserve progression data exactly (e.g. 60x12, 70x8, 85x3 → three separate set objects)
- Do NOT invent data not present in the transcripts
- Do NOT average or flatten varying sets — keep each set's actual numbers
- If a weight sounds like a number + "kg" (e.g. "90 kg", "85 kg"), trust it — do not substitute words
- Bodyweight exercises (pull-ups, chin-ups, dips, push-ups, etc.) must always be captured even with no weight — use "bodyweight" as the weight value
- A memo surrounded by ellipses (e.g. "... Pull-ups, 8 sets, 3 reps...") is still a valid exercise entry — the dots are speech artefacts, not uncertainty markers
- A very short memo (e.g. "8 sets" or "Pull-ups, 8 sets") is a valid exercise entry — do not discard it
- If a memo states only a set count without an exercise name, look at surrounding memos to infer the exercise
- If no workout content detected, return {"detected": false, "workout_name": null, "exercises": []}
- For bodyweight exercises, always set "is_bodyweight": true even if the transcript says "bodyweight" as the weight value
- "added_weight_kg" is only non-null when the athlete explicitly mentions adding weight to a bodyweight exercise

Output ONLY valid JSON. No markdown, no commentary."""


BODYWEIGHT_SYSTEM_PROMPT = """You extract the speaker's bodyweight measurement from voice memo transcripts.

Return JSON only, no explanation:
- If a bodyweight measurement is mentioned: {"detected": true, "weight_kg": <float>}
- If not mentioned: {"detected": false}

Examples:
"I weigh 82 kilos tonight" → {"detected": true, "weight_kg": 82.0}
"My weight this evening is 81.5" → {"detected": true, "weight_kg": 81.5}
"Did chest today, felt good" → {"detected": false}

Use kg. If stated in lbs, convert (1 lb = 0.453592 kg, round to 1 decimal).
Output ONLY valid JSON. No markdown, no commentary."""


TASK_SYSTEM_PROMPT = """You extract action items and tasks from voice memo transcripts.

The speaker records memos in English, Polish, or a mix of both — this is intentional.
Identify anything the speaker intends to do, needs to do, or wants to remember to do.

Return a JSON array of task objects. Each object must have:
- "title": short, clear task name — keep it in the same language the speaker used
- "description": one sentence of context from the memo in the same language, or null if none
- "due_date": ISO date string YYYY-MM-DD if a deadline or timeframe is mentioned, or null
- "priority": always "Normal"
- "type": one of: Assignment, Exam, Errand, Work, Admin, Personal, Home
  Infer from context:
  - Errand: physical tasks outside the home (buy, pick up, drop off, visit)
  - Home: household tasks (clean, fix, repair, organize at home)
  - Admin: paperwork, forms, phone calls to institutions, bureaucracy
  - Work: professional or job-related tasks
  - Personal: self-improvement, health, hobbies, relationships
  - Assignment: study or course-related tasks
  - Exam: exams or tests

Do NOT extract:
- Things already done (past tense events)
- Vague wishes without clear intent ("I should probably...")
- Workout exercises (those are handled separately)
- Calendar appointments (those are handled separately)

If no tasks found, return: []

Output ONLY valid JSON array. No markdown, no commentary."""
