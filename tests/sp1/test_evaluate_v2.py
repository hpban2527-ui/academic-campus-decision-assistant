import pytest
from sp1.evaluate_v2 import outcome, equal


@pytest.mark.parametrize(("field", "predicted", "gold", "expected"), [
    ("title", ' “HỘI  THẢO.” ', "hội thảo", "correct"),
    ("window_open", "2026-11-01T08:00+07:00", "2026-11-01", "correct"),
    ("window_open", "2026-11-01", "2026-11-01T08:00+07:00", "wrong"),
    ("title", None, "Event", "missed"),
    ("title", "Event", None, "fabricated"),
    ("title", None, None, "correct"),
    ("mandatory_stated", False, None, "fabricated"),
    ("fee", 0, None, "fabricated"),
    ("audience_scope", {"cohorts": ["K25", "K24"], "programs": []},
     {"cohorts": ["K24", "K25"], "programs": []}, "correct"),
    ("completion_requirements", [{"type": "quiz", "threshold": 70, "unit": "percent", "deadline": None}],
     [{"type": "quiz", "threshold": 70, "unit": "percent", "deadline": "2026-11-01"}], "correct"),
    ("completion_requirements", [], [{"type": "form", "threshold": None, "unit": None}], "missed"),
    ("fee", {"amount_vnd": 1000, "per": "team", "deposit": True},
     {"amount_vnd": 1000, "per": "team", "deposit": False}, "wrong"),
])
def test_comparison(field, predicted, gold, expected):
    assert outcome(field, predicted, gold) == expected


def test_legacy_mapping():
    assert equal("fee", {"amount_vnd": 50000, "per": "team", "deposit": False}, 50000, True)
    assert equal("registration_url", "https://example.org/form", "http://example.org/form", True)
    assert equal("window_open", "2026-11-01", "2026-11-01T00:00:00+07:00", True)
