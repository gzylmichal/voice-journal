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
