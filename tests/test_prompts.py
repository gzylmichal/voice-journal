"""Tests that required rules are present in the LLM system prompts."""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

from pipeline.prompts import JOURNAL_SYSTEM_PROMPT, CALENDAR_SYSTEM_PROMPT


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
