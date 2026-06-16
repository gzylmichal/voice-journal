"""tests/test_plan_config.py — Unit tests for pipeline.plan_config.load_plan_config."""

import json
import os
import tempfile
from pathlib import Path

import pytest

from pipeline.plan_config import load_plan_config


def _write_tmp(content: str) -> str:
    """Write content to a temp file and return its path."""
    fh = tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False, encoding="utf-8")
    fh.write(content)
    fh.close()
    return fh.name


VALID_CONFIG = {
    "cycle": ["Chest", "Deadlift", "Squat"],
    "templates": {
        "Chest": [{"slot": "Bench press", "type": "main", "match": ["bench"]}],
        "Deadlift": [],
        "Squat": [],
    },
}


def test_valid_file_loads():
    path = _write_tmp(json.dumps(VALID_CONFIG))
    try:
        result = load_plan_config(path)
        assert result is not None
        assert result["cycle"] == ["Chest", "Deadlift", "Squat"]
        assert "templates" in result
    finally:
        os.unlink(path)


def test_missing_file_returns_none():
    result = load_plan_config("/tmp/__nonexistent_plan_config_xyz__.json")
    assert result is None


def test_malformed_json_returns_none_no_raise():
    path = _write_tmp("{ this is not valid json }")
    try:
        result = load_plan_config(path)
        assert result is None
    finally:
        os.unlink(path)


def test_missing_cycle_returns_none():
    config = {"templates": VALID_CONFIG["templates"]}
    path = _write_tmp(json.dumps(config))
    try:
        result = load_plan_config(path)
        assert result is None
    finally:
        os.unlink(path)


def test_empty_cycle_returns_none():
    config = {"cycle": [], "templates": VALID_CONFIG["templates"]}
    path = _write_tmp(json.dumps(config))
    try:
        result = load_plan_config(path)
        assert result is None
    finally:
        os.unlink(path)


def test_missing_templates_returns_none():
    config = {"cycle": ["Chest", "Deadlift", "Squat"]}
    path = _write_tmp(json.dumps(config))
    try:
        result = load_plan_config(path)
        assert result is None
    finally:
        os.unlink(path)


def test_empty_templates_returns_none():
    config = {"cycle": ["Chest", "Deadlift", "Squat"], "templates": {}}
    path = _write_tmp(json.dumps(config))
    try:
        result = load_plan_config(path)
        assert result is None
    finally:
        os.unlink(path)
