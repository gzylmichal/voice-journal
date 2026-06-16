"""pipeline/plan_config.py — Load and validate workout_plan.json.

Usage:
    from pipeline.plan_config import load_plan_config
    config = load_plan_config()   # returns dict or None
"""

import json
import logging
import os
from pathlib import Path

log = logging.getLogger("plan_config")

_PROJECT_ROOT = Path(__file__).parent.parent


def load_plan_config(path: "str | None" = None) -> "dict | None":
    """Load workout_plan.json and validate required keys.

    Returns the parsed dict on success, or None if the file is missing,
    contains invalid JSON, or fails validation. Never raises.

    Required shape: {"cycle": [non-empty list], "templates": {dict}, ...}
    """
    if path is None:
        path = os.getenv("PLAN_CONFIG_PATH", "workout_plan.json")

    resolved = Path(path)
    if not resolved.is_absolute():
        resolved = _PROJECT_ROOT / path

    if not resolved.exists():
        log.info("plan_config: %s not found — session planner disabled", resolved)
        return None

    try:
        with open(resolved, encoding="utf-8") as fh:
            data = json.load(fh)
    except json.JSONDecodeError as exc:
        log.info("plan_config: malformed JSON in %s (%s) — session planner disabled", resolved, exc)
        return None

    if not isinstance(data, dict):
        log.info("plan_config: root is not an object — session planner disabled")
        return None

    cycle = data.get("cycle")
    if not cycle or not isinstance(cycle, list):
        log.info("plan_config: missing or empty 'cycle' list — session planner disabled")
        return None

    templates = data.get("templates")
    if not templates or not isinstance(templates, dict):
        log.info("plan_config: missing or empty 'templates' dict — session planner disabled")
        return None

    return data
