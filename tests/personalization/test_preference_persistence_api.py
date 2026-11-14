from __future__ import annotations

from copy import deepcopy

from fastapi.testclient import TestClient

from api import server


client = TestClient(server.app)


def test_confirmed_preference_round_trip_is_isolated_by_student(monkeypatch, valid_preference_payload):
    monkeypatch.setattr(server, "session_preferences", {})
    monkeypatch.setattr(server, "_save_session_to_disk", lambda: None)
    request = {
        "student_id": "student-a",
        "confirmed": True,
        "preference": valid_preference_payload,
        "source_text": "  Em thích Toán và online.  ",
    }

    saved = client.put("/api/preferences/confirmed", json=request)
    own = client.get("/api/preferences/confirmed", params={"student_id": "student-a"})
    other = client.get("/api/preferences/confirmed", params={"student_id": "student-b"})

    assert saved.status_code == 200, saved.text
    assert saved.json()["status"] == "SAVED"
    assert saved.json()["confirmed_preference"]["preference_version"].startswith("pref-")
    assert own.json()["confirmed_preference"]["source_text"] == "Em thích Toán và online."
    assert own.json()["confirmed_preference"]["preference"] == valid_preference_payload
    assert other.json() == {
        "status": "EMPTY",
        "student_id": "student-b",
        "confirmed_preference": None,
    }


def test_unconfirmed_preference_cannot_be_persisted(monkeypatch, valid_preference_payload):
    monkeypatch.setattr(server, "session_preferences", {})
    monkeypatch.setattr(server, "_save_session_to_disk", lambda: None)

    response = client.put(
        "/api/preferences/confirmed",
        json={
            "student_id": "student-a",
            "confirmed": False,
            "preference": valid_preference_payload,
            "source_text": None,
        },
    )

    assert response.status_code == 422
    assert server.session_preferences == {}


def test_updating_preference_changes_content_version(monkeypatch, valid_preference_payload):
    monkeypatch.setattr(server, "session_preferences", {})
    monkeypatch.setattr(server, "_save_session_to_disk", lambda: None)
    base = {
        "student_id": "student-a",
        "confirmed": True,
        "preference": valid_preference_payload,
        "source_text": "Em thích Toán",
    }
    first = client.put("/api/preferences/confirmed", json=base).json()
    changed = deepcopy(base)
    changed["preference"]["topic_preferences"][0]["weight"] = 3

    second = client.put("/api/preferences/confirmed", json=changed).json()

    assert first["confirmed_preference"]["preference_version"] != second["confirmed_preference"]["preference_version"]


def test_delete_only_removes_named_students_preference(monkeypatch, valid_preference_payload):
    monkeypatch.setattr(
        server,
        "session_preferences",
        {
            "student-a": {"preference": valid_preference_payload},
            "student-b": {"preference": valid_preference_payload},
        },
    )
    monkeypatch.setattr(server, "_save_session_to_disk", lambda: None)

    response = client.delete("/api/preferences/confirmed", params={"student_id": "student-a"})

    assert response.json()["status"] == "DELETED"
    assert "student-a" not in server.session_preferences
    assert "student-b" in server.session_preferences
