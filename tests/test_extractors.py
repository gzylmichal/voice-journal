import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

import pytest
from pipeline.extractors import infer_muscle_group


# ---------------------------------------------------------------------------
# G1: MUSCLE_GROUP_RULES ordering — longer keywords must take precedence
# ---------------------------------------------------------------------------

def test_leg_curl_is_legs():
    assert infer_muscle_group("leg curl") == "Legs"

def test_wrist_curl_is_forearms():
    assert infer_muscle_group("wrist curl") == "Forearms"

def test_hammer_curl_is_biceps():
    assert infer_muscle_group("hammer curl") == "Biceps"

def test_lat_pulldown_is_back():
    assert infer_muscle_group("lat pulldown") == "Back"

def test_plain_curl_is_biceps():
    assert infer_muscle_group("barbell curl") == "Biceps"
