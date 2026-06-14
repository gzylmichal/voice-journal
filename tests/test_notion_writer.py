"""tests/test_notion_writer.py — Verify rpe/pain_note Notion payload behaviour."""

import json
from datetime import date
from unittest.mock import MagicMock, patch

import pytest

from pipeline.notion_client import create_notion_workout_entries

TODAY = date(2026, 6, 14)
FAKE_DB = "db-workout"
FAKE_TOKEN = "secret_test"


def _workout(exercises):
    return {"detected": True, "workout_name": "Push day", "exercises": exercises}


def _ex(name="Bench press", sets=3, rpe=None, pain_note=None, **kwargs):
    ex = {
        "name": name,
        "sets": sets,
        "sets_detail": [{"reps": 8, "weight": "80 kg"}] * sets,
        "is_bodyweight": False,
        "added_weight_kg": None,
    }
    if rpe is not None:
        ex["rpe"] = rpe
    if pain_note is not None:
        ex["pain_note"] = pain_note
    ex.update(kwargs)
    return ex


def _capture_posts():
    """Context manager that captures all Notion posts and returns 200."""
    posts = []

    def fake_post(url, **kwargs):
        posts.append(kwargs.get("json", {}))
        r = MagicMock()
        r.status_code = 200
        r.json.return_value = {"id": "fake"}
        return r

    return posts, fake_post


# ---------------------------------------------------------------------------
# rpe and pain_note included when present
# ---------------------------------------------------------------------------

def test_rpe_included_in_payload():
    posts, fake_post = _capture_posts()
    with (
        patch("pipeline.notion_client.NOTION_TOKEN", FAKE_TOKEN),
        patch("pipeline.notion_client.NOTION_WORKOUT_DB_ID", FAKE_DB),
        patch("pipeline.notion_client.requests.post", side_effect=fake_post),
    ):
        create_notion_workout_entries(_workout([_ex(rpe=8.0)]), TODAY)

    assert posts, "No Notion post was made"
    props = posts[0]["properties"]
    assert "RPE" in props
    assert props["RPE"] == {"number": 8.0}


def test_pain_note_included_in_payload():
    posts, fake_post = _capture_posts()
    with (
        patch("pipeline.notion_client.NOTION_TOKEN", FAKE_TOKEN),
        patch("pipeline.notion_client.NOTION_WORKOUT_DB_ID", FAKE_DB),
        patch("pipeline.notion_client.requests.post", side_effect=fake_post),
    ):
        create_notion_workout_entries(_workout([_ex(pain_note="left shoulder twinge")]), TODAY)

    props = posts[0]["properties"]
    assert "Pain note" in props
    assert props["Pain note"] == {"rich_text": [{"text": {"content": "left shoulder twinge"}}]}


def test_rpe_and_pain_note_both_included():
    posts, fake_post = _capture_posts()
    with (
        patch("pipeline.notion_client.NOTION_TOKEN", FAKE_TOKEN),
        patch("pipeline.notion_client.NOTION_WORKOUT_DB_ID", FAKE_DB),
        patch("pipeline.notion_client.requests.post", side_effect=fake_post),
    ):
        create_notion_workout_entries(_workout([_ex(rpe=9.5, pain_note="knee twinge")]), TODAY)

    props = posts[0]["properties"]
    assert props["RPE"]["number"] == 9.5
    assert "knee twinge" in props["Pain note"]["rich_text"][0]["text"]["content"]


# ---------------------------------------------------------------------------
# rpe and pain_note omitted when null/absent
# ---------------------------------------------------------------------------

def test_null_rpe_omitted():
    posts, fake_post = _capture_posts()
    with (
        patch("pipeline.notion_client.NOTION_TOKEN", FAKE_TOKEN),
        patch("pipeline.notion_client.NOTION_WORKOUT_DB_ID", FAKE_DB),
        patch("pipeline.notion_client.requests.post", side_effect=fake_post),
    ):
        create_notion_workout_entries(_workout([_ex(rpe=None)]), TODAY)

    props = posts[0]["properties"]
    assert "RPE" not in props


def test_empty_pain_note_omitted():
    posts, fake_post = _capture_posts()
    with (
        patch("pipeline.notion_client.NOTION_TOKEN", FAKE_TOKEN),
        patch("pipeline.notion_client.NOTION_WORKOUT_DB_ID", FAKE_DB),
        patch("pipeline.notion_client.requests.post", side_effect=fake_post),
    ):
        create_notion_workout_entries(_workout([_ex(pain_note="")]), TODAY)

    props = posts[0]["properties"]
    assert "Pain note" not in props


# ---------------------------------------------------------------------------
# Old-schema exercise dict (no rpe/pain_note keys) → identical payload
# ---------------------------------------------------------------------------

def test_old_schema_no_rpe_pain_keys_payload_unchanged():
    """Exercise dict without rpe/pain_note keys produces same payload as before Phase I."""
    posts_old, fake_post_old = _capture_posts()
    old_ex = {
        "name": "Bench press", "sets": 3,
        "sets_detail": [{"reps": 8, "weight": "80 kg"}] * 3,
        "is_bodyweight": False, "added_weight_kg": None,
    }

    posts_new, fake_post_new = _capture_posts()
    new_ex = dict(old_ex)  # same dict, rpe/pain_note keys simply absent

    patch_args = dict(
        NOTION_TOKEN=FAKE_TOKEN,
        NOTION_WORKOUT_DB_ID=FAKE_DB,
    )

    with (
        patch("pipeline.notion_client.NOTION_TOKEN", FAKE_TOKEN),
        patch("pipeline.notion_client.NOTION_WORKOUT_DB_ID", FAKE_DB),
        patch("pipeline.notion_client.requests.post", side_effect=fake_post_old),
    ):
        create_notion_workout_entries(_workout([old_ex]), TODAY)

    with (
        patch("pipeline.notion_client.NOTION_TOKEN", FAKE_TOKEN),
        patch("pipeline.notion_client.NOTION_WORKOUT_DB_ID", FAKE_DB),
        patch("pipeline.notion_client.requests.post", side_effect=fake_post_new),
    ):
        create_notion_workout_entries(_workout([new_ex]), TODAY)

    assert posts_old[0]["properties"] == posts_new[0]["properties"]
    assert "RPE" not in posts_old[0]["properties"]
    assert "Pain note" not in posts_old[0]["properties"]
