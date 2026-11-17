from __future__ import annotations

import json
from pathlib import Path

from personalization.models import CampusId, TimeSlotId, TopicId


ROOT = Path(__file__).resolve().parents[2]


def test_activity_feature_sidecar_covers_current_catalog():
    activities = json.loads((ROOT / "data" / "activities.json").read_text(encoding="utf-8"))
    features = json.loads((ROOT / "data" / "activity_features.json").read_text(encoding="utf-8"))

    activity_ids = {item["activity_id"] for item in activities}
    feature_ids = set(features["activities"])

    assert features["schema_version"] == "personalization-features/0.1"
    assert feature_ids == activity_ids
    assert len(feature_ids) >= 10


def test_activity_feature_values_use_the_strict_catalog():
    payload = json.loads((ROOT / "data" / "activity_features.json").read_text(encoding="utf-8"))
    for activity_id, feature in payload["activities"].items():
        assert feature["topics"], f"{activity_id} needs at least one topic"
        assert len(feature["topics"]) == len(set(feature["topics"]))
        for topic in feature["topics"]:
            TopicId(topic)
        CampusId(feature["campus_id"])
        for time_slot in feature["time_tags"]:
            TimeSlotId(time_slot)
