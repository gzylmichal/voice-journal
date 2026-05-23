"""
Synthesis — Gemini API.

Produces a 2-3 sentence TL;DR from structured collector data.
Template owns everything else (weather, agenda, news, markets).

Requires: GEMINI_API_KEY in .env
Docs: https://ai.google.dev/gemini-api/docs
"""

import logging
import requests

logger = logging.getLogger("debrief.synthesis")

GEMINI_API_URL = (
    "https://generativelanguage.googleapis.com/v1beta/models/"
    "gemini-2.5-flash:generateContent"
)

SYSTEM_PROMPT = """You write a one-paragraph TL;DR for a morning briefing email.

Constraints:
- 2 to 3 short sentences. Under 60 words total.
- Plain text only. No markdown, no bullets, no headers, no sign-offs.
- Be direct and practical. What should the reader DO or NOTICE today?
- Cover: what to wear (based on weather), what matters on the agenda,
  and one notable external signal (big market move, major news).
- Skip anything unremarkable. If nothing is notable in a category, omit it.
- Do not invent data. If a source is missing from the input, ignore it.
- Write in English. If Polish news is more relevant, mention it in English.
"""


WEEKLY_PROMPT = """You are writing the introduction paragraph for a Weekly Review email.

You will receive:
1. Gym training data from the past week (sessions, exercises, top sets)
2. Daily journal snippets from the past week (what the person did/noted each day)

Write a single paragraph of 3–5 sentences that:
- Names the week's training highlight (best lift, most consistent day, or biggest improvement)
- Mentions 1–2 notable life or work things from the journal notes
- Ends with a forward-looking sentence about the week ahead based on any calendar/journal mentions

Tone: direct, personal, like a smart friend reading your notes. No fluff.
Max 80 words. Output only the paragraph — no labels, no markdown."""


def synthesize_weekly(cfg: dict, workout_text: str, journal_entries: list[dict]) -> str:
    """
    Generate a short weekly intro paragraph combining gym + journal data.
    Falls back to empty string on failure (email still sends without it).
    """
    api_key = cfg.get("gemini_api_key", "") or cfg.get("google_api_key", "")
    model   = cfg.get("gemini_model", "gemini-2.5-flash")

    journal_lines = []
    for e in journal_entries:
        snippet = e.get("summary", "").strip()
        if snippet:
            journal_lines.append(f"{e['date']} — {e['title']}: {snippet}")

    journal_text = "\n".join(journal_lines) if journal_lines else "No journal entries this week."

    prompt = (
        f"## Training this week\n{workout_text}\n\n"
        f"## Daily notes\n{journal_text}"
    )

    try:
        url = (
            f"https://generativelanguage.googleapis.com/v1beta/models/"
            f"{model}:generateContent?key={api_key}"
        )
        resp = requests.post(
            url,
            headers={"content-type": "application/json"},
            json={
                "system_instruction": {"parts": [{"text": WEEKLY_PROMPT}]},
                "contents": [{"role": "user", "parts": [{"text": prompt}]}],
                "generationConfig": {"temperature": 0.4, "maxOutputTokens": 200},
            },
            timeout=30,
        )
        resp.raise_for_status()
        parts = resp.json()["candidates"][0]["content"]["parts"]
        return "".join(p.get("text", "") for p in parts).strip()
    except Exception as exc:
        logger.error("Weekly synthesis failed: %s", exc)
        return ""


def synthesize_tldr(cfg: dict, raw_context: str, date_str: str) -> str:
    """Generate a short TL;DR paragraph. Returns empty string on failure."""

    api_key = cfg.get("gemini_api_key", "")
    if not api_key:
        logger.warning("GEMINI_API_KEY not set — skipping synthesis")
        return ""

    user_prompt = (
        f"Today is {date_str}. Here is the raw data collected from "
        f"various sources:\n\n{raw_context}\n\n"
        "Write the TL;DR."
    )

    payload = {
        "contents": [{"role": "user", "parts": [{"text": user_prompt}]}],
        "systemInstruction": {"parts": [{"text": SYSTEM_PROMPT}]},
        "generationConfig": {
            "temperature": 0.3,
            "maxOutputTokens": 512,
            "thinkingConfig": {"thinkingBudget": 0},
        },
    }

    try:
        resp = requests.post(
            f"{GEMINI_API_URL}?key={api_key}",
            headers={"Content-Type": "application/json"},
            json=payload,
            timeout=60,
        )
        if resp.status_code != 200:
            logger.error("Gemini API %s: %s", resp.status_code, resp.text[:500])
            return ""
        result = resp.json()
        text = result["candidates"][0]["content"]["parts"][0]["text"]
        return text.strip()
    except (KeyError, IndexError, requests.exceptions.RequestException) as exc:
        logger.error("Synthesis failed: %s", exc)
        return ""
