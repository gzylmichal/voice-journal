"""Tests for Morning Debrief code block handling in notion_collector and formatter."""
import importlib.util
import sys
from pathlib import Path

import pytest

# The debrief code lives inside this repo at debrief/
DEBRIEF_DIR = Path(__file__).parent.parent / "debrief"
sys.path.insert(0, str(DEBRIEF_DIR))


def _load_formatter():
    """Load debrief/formatter.py by file path.

    Python 3.9 ships a deprecated stdlib module also named 'formatter' which
    shadows ours via normal import — loading by explicit path avoids that.
    """
    spec = importlib.util.spec_from_file_location(
        "debrief_formatter", DEBRIEF_DIR / "formatter.py"
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _make_notion_code_block(content: str) -> dict:
    """Simulate a Notion API code block response."""
    return {
        "type": "code",
        "code": {
            "rich_text": [{"plain_text": content, "type": "text"}],
            "language": "plain text",
        },
    }


def test_normalize_blocks_handles_code_type():
    from collectors.notion_collector import _normalize_blocks
    raw = [_make_notion_code_block("Exercise  Sets\nBench       3")]
    result = _normalize_blocks(raw)
    assert len(result) == 1
    assert result[0]["type"] == "code"
    assert "Bench" in result[0]["text"]


def test_normalize_blocks_skips_empty_code_block():
    from collectors.notion_collector import _normalize_blocks
    raw = [_make_notion_code_block("")]
    result = _normalize_blocks(raw)
    assert result == []


@pytest.mark.skip(reason="render_notion in this repo does not render code blocks yet "
                         "(feature from the old standalone morning-debrief project, never ported; "
                         "workout tables reach the email via workout_collector instead). "
                         "See IMPROVEMENT_PLAN_2.md G7.")
def test_render_notion_includes_pre_for_code_blocks():
    render_notion = _load_formatter().render_notion

    data = {
        "configured": True,
        "found": True,
        "blocks": [
            {"type": "paragraph", "text": "Had a push day."},
            {"type": "code", "text": "Exercise  Sets\nBench       3"},
        ],
    }
    html = render_notion(data)
    assert "<pre" in html
    assert "Bench" in html


@pytest.mark.skip(reason="render_notion does not render code blocks yet — see above / IMPROVEMENT_PLAN_2.md G7.")
def test_render_notion_escapes_code_content():
    render_notion = _load_formatter().render_notion

    data = {
        "configured": True,
        "found": True,
        "blocks": [
            {"type": "code", "text": "a < b & c > d"},
        ],
    }
    html = render_notion(data)
    assert "&lt;" in html
    assert "&amp;" in html
    assert "<script" not in html
