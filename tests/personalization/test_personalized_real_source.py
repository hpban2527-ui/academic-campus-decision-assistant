"""A confirmed preference also works on the real SP1 v2 store (?source=real)."""
from fastapi.testclient import TestClient

from api import server

client = TestClient(server.app)


def test_personalized_plan_on_real_store(valid_preference_payload):
    response = client.post(
        "/api/sp3/personalized/plan?source=real",
        json={"confirmed": True, "preference": valid_preference_payload, "total_target": 80, "busy_intervals": []},
    )
    assert response.status_code == 200, response.text
    result = response.json()
    assert result["data_source"] == "OPERATIONAL-DATASET"
    assert result["preference_confirmed"] is True
    breakdown_ids = {row["activity_id"] for row in result["personalization"]["selected_breakdown"]}
    assert breakdown_ids == {a["activity_id"] for a in result["plan"]["selected_activities"]}
