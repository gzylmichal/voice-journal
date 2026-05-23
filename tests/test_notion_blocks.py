"""Tests for markdown_to_notion_blocks — code fence handling."""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

from pipeline.notion_client import markdown_to_notion_blocks


def test_code_fence_produces_code_block():
    md = "Some text\n\n```\nline1\nline2\n```\n"
    blocks = markdown_to_notion_blocks(md)
    types = [b["type"] for b in blocks]
    assert "code" in types


def test_code_block_content_is_preserved():
    md = "```\nExercise    Sets  Detail\n──────────\nBench press   3  80x5\n```\n"
    blocks = markdown_to_notion_blocks(md)
    code_blocks = [b for b in blocks if b["type"] == "code"]
    assert len(code_blocks) == 1
    content = code_blocks[0]["code"]["rich_text"][0]["text"]["content"]
    assert "Bench press" in content
    assert "80x5" in content


def test_code_block_language_is_plain_text():
    md = "```\nhello\n```\n"
    blocks = markdown_to_notion_blocks(md)
    code_blocks = [b for b in blocks if b["type"] == "code"]
    assert code_blocks[0]["code"]["language"] == "plain text"


def test_code_block_surrounded_by_other_blocks():
    md = "## Heading\n\nSome paragraph.\n\n```\ntable content\n```\n\n- bullet item\n"
    blocks = markdown_to_notion_blocks(md)
    types = [b["type"] for b in blocks]
    assert types == ["heading_2", "paragraph", "code", "bulleted_list_item"]


def test_non_code_content_unchanged():
    md = "## Title\n\nParagraph text.\n\n- list item\n"
    blocks = markdown_to_notion_blocks(md)
    types = [b["type"] for b in blocks]
    assert "code" not in types
    assert "heading_2" in types
    assert "paragraph" in types
    assert "bulleted_list_item" in types
