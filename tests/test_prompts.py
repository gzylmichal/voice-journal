"""Tests that required rules are present in the LLM system prompts."""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

from pipeline.prompts import (
    JOURNAL_SYSTEM_PROMPT,
    CALENDAR_SYSTEM_PROMPT,
    EXTRACTION_SYSTEM_PROMPT,
    WORKOUT_SYSTEM_PROMPT,
)


def test_journal_prompt_has_workout_separation_rule():
    assert "do NOT list exercises, sets, or weights" in JOURNAL_SYSTEM_PROMPT


def test_journal_prompt_excludes_calendar_from_todo():
    assert "Do NOT include calendar appointments" in JOURNAL_SYSTEM_PROMPT


def test_calendar_prompt_handles_meta_requests():
    assert "add to calendar" in CALENDAR_SYSTEM_PROMPT.lower()
    assert "create an event for" in CALENDAR_SYSTEM_PROMPT.lower()


def test_calendar_prompt_title_rule():
    assert "Eyebrow appointment" in CALENDAR_SYSTEM_PROMPT or \
           "what the appointment IS" in CALENDAR_SYSTEM_PROMPT or \
           "what the event IS" in CALENDAR_SYSTEM_PROMPT


# ---------------------------------------------------------------------------
# RPE + pain_note field rules in extraction prompts
# ---------------------------------------------------------------------------

def test_extraction_prompt_has_rpe_field():
    assert '"rpe"' in EXTRACTION_SYSTEM_PROMPT
    assert "null" in EXTRACTION_SYSTEM_PROMPT

def test_extraction_prompt_rpe_effort_cue_rule():
    # Must state that rpe is only filled on a clear effort cue
    assert "clear effort cue" in EXTRACTION_SYSTEM_PROMPT or "NEVER guess" in EXTRACTION_SYSTEM_PROMPT

def test_extraction_prompt_rpe_english_cues():
    assert "to failure" in EXTRACTION_SYSTEM_PROMPT
    assert "hard" in EXTRACTION_SYSTEM_PROMPT or "RPE" in EXTRACTION_SYSTEM_PROMPT

def test_extraction_prompt_rpe_polish_cues():
    assert "ciężko szło" in EXTRACTION_SYSTEM_PROMPT
    assert "do upadku" in EXTRACTION_SYSTEM_PROMPT

def test_extraction_prompt_has_pain_note_field():
    assert '"pain_note"' in EXTRACTION_SYSTEM_PROMPT

def test_extraction_prompt_pain_english_cues():
    assert "hurt" in EXTRACTION_SYSTEM_PROMPT
    assert "twinge" in EXTRACTION_SYSTEM_PROMPT

def test_extraction_prompt_pain_polish_cues():
    assert "boli" in EXTRACTION_SYSTEM_PROMPT
    assert "kolano" in EXTRACTION_SYSTEM_PROMPT

def test_workout_prompt_has_rpe_and_pain():
    assert '"rpe"' in WORKOUT_SYSTEM_PROMPT
    assert '"pain_note"' in WORKOUT_SYSTEM_PROMPT
    assert "ciężko szło" in WORKOUT_SYSTEM_PROMPT
    assert "boli" in WORKOUT_SYSTEM_PROMPT


# ---------------------------------------------------------------------------
# Phase J: metrics key in extraction prompt
# ---------------------------------------------------------------------------

def test_extraction_prompt_has_metrics_key():
    assert '"metrics"' in EXTRACTION_SYSTEM_PROMPT

def test_extraction_prompt_metrics_sleep_values():
    assert "good" in EXTRACTION_SYSTEM_PROMPT
    assert "bad" in EXTRACTION_SYSTEM_PROMPT

def test_extraction_prompt_metrics_energy_values():
    assert "high" in EXTRACTION_SYSTEM_PROMPT
    assert "low" in EXTRACTION_SYSTEM_PROMPT

def test_extraction_prompt_metrics_polish_sleep_cues():
    assert "spałem jak kamień" in EXTRACTION_SYSTEM_PROMPT
    assert "słabo spałem" in EXTRACTION_SYSTEM_PROMPT

def test_extraction_prompt_metrics_qualitative_only():
    # Must explicitly state qualitative/no numbers
    assert "qualitative" in EXTRACTION_SYSTEM_PROMPT.lower() or \
           "never extract" in EXTRACTION_SYSTEM_PROMPT.lower() or \
           "STRICTLY qualitative" in EXTRACTION_SYSTEM_PROMPT

def test_extraction_prompt_six_keys():
    assert "six keys" in EXTRACTION_SYSTEM_PROMPT


# ---------------------------------------------------------------------------
# Phase M: query key in extraction prompt
# ---------------------------------------------------------------------------

def test_extraction_prompt_has_query_key():
    assert '"query"' in EXTRACTION_SYSTEM_PROMPT

def test_extraction_prompt_query_has_detected_and_question():
    assert '"detected"' in EXTRACTION_SYSTEM_PROMPT
    assert '"question"' in EXTRACTION_SYSTEM_PROMPT

def test_extraction_prompt_query_polish_cues():
    assert "co ostatnio" in EXTRACTION_SYSTEM_PROMPT or "ostatnio wyciskałem" in EXTRACTION_SYSTEM_PROMPT

def test_extraction_prompt_query_isolation_rule():
    # Must state that a query memo should NOT populate other keys
    assert "do NOT" in EXTRACTION_SYSTEM_PROMPT or "ONLY a question" in EXTRACTION_SYSTEM_PROMPT
