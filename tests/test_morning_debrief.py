"""Tests for Morning Debrief code block handling in notion_collector and formatter."""
import sys
from pathlib import Path

# Add morning-debrief to path
sys.path.insert(0, str(Path("/Users/michalgzyl/Desktop/Projects/Morning debrief/morning-debrief")))


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


def test_render_notion_includes_pre_for_code_blocks():
    # Need to import after setting sys.path
    import importlib
    formatter_module = importlib.import_module("formatter")
    render_notion = formatter_module.render_notion
    
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


def test_render_notion_escapes_code_content():
    import importlib
    formatter_module = importlib.import_module("formatter")
    render_notion = formatter_module.render_notion
    
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
