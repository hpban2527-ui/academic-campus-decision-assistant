"""Regression checks for the leader-owned SP1 publication boundary."""
import json
import sys
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator, FormatChecker

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))

from api.lead_contract import ACTIVITY_FIELDS, audit_dataset, canonical_url, prepare_publication


def sample_draft():
    return {
        "record": {
            "activity_id": "TMP-test-01",
            "source": {
                "publisher": "HCMUS", "platform": "facebook",
                "URL_post": "https://facebook.com/events/abc?rdid=123&fbclid=tracker",
                "URL_registration": "https://example.org/apply",
            },
            "title": "Demo event", "domain": "skills",
            "start": "2026-10-30T14:00:00+07:00",
            "end": "2026-10-30T16:00:00+07:00",
            "registration_deadline": "2026-10-29T23:59:00+07:00",
            "mode": "offline", "location": "HCMUS",
            "points": None, "drl_recognized": None,
            "mandatory": None, "audience": ["Sinh vien"],
            "fee": None, "completion_requirements": "Check in at reception",
        },
        "meta": {"status": "valid", "flags": [], "evidence": {}},
    }


def schema():
    return json.loads((ROOT / "schemas/activity.schema.json").read_text(encoding="utf-8"))


def test_exactly_fourteen_fields_and_policy_defaults():
    draft = prepare_publication(sample_draft())
    assert set(draft["record"]) == set(ACTIVITY_FIELDS)
    assert draft["record"]["mandatory"] is False
    assert draft["record"]["fee"] == 0
    assert draft["meta"]["derived"]["mandatory"].startswith("group_default")
    assert draft["meta"]["derived"]["fee"].startswith("group_default")
    assert "drl_recognized" not in draft["record"]
    assert "drl_recognized" in draft["meta"]


def test_formal_schema_validates_only_published_shape():
    record = prepare_publication(sample_draft())["record"]
    Draft202012Validator(schema(), format_checker=FormatChecker()).validate(record)


def test_tracking_params_cannot_change_activity_identity():
    a = sample_draft()
    b = sample_draft()
    a["record"]["source"]["URL_post"] = "https://facebook.com/events/abc?rdid=a"
    b["record"]["source"]["URL_post"] = "https://facebook.com/events/abc?rdid=b"
    assert prepare_publication(a)["record"]["activity_id"] == prepare_publication(b)["record"]["activity_id"]


def test_never_auto_approve_an_unflagged_regex_draft():
    result = prepare_publication(sample_draft())
    assert result["meta"]["publication_status"] == "REVIEW_REQUIRED"
    assert result["meta"]["routed_to"] == "review_queue"


@pytest.mark.parametrize("missing", ["mode", "completion_requirements"])
def test_missing_required_field_is_flagged(missing):
    draft = sample_draft()
    draft["record"][missing] = None
    result = prepare_publication(draft)
    assert f"needs_review:{missing}" in result["meta"]["flags"]
    assert result["meta"]["publication_status"] == "REVIEW_REQUIRED"


def test_time_order_reversal_is_rejected():
    draft = sample_draft()
    draft["record"]["end"] = "2026-10-29T13:00:00+07:00"
    assert "invalid_value:end" in prepare_publication(draft)["meta"]["flags"]


def test_online_activity_must_not_claim_a_physical_location():
    draft = sample_draft()
    draft["record"]["mode"] = "online"
    assert "invalid_value:online_location" in prepare_publication(draft)["meta"]["flags"]


def test_non_iso_timezone_timestamp_is_flagged():
    draft = sample_draft()
    draft["record"]["start"] = "2026-10-30T14:00:00"
    assert "invalid_value:start" in prepare_publication(draft)["meta"]["flags"]


def test_source_url_canonicalization_preserves_valid_payload():
    assert canonical_url("https://facebook.com/posts/123?rdid=foo&utm_source=bar&id=42") == "https://facebook.com/posts/123?id=42"


def test_dataset_audit_surfaces_missing_values_without_inventing_them():
    r = sample_draft()["record"]
    r["mode"] = None
    r["completion_requirements"] = None
    d = audit_dataset([r])
    assert d["total"] == 1 and d["missing_mode"] == 1
    assert d["missing_completion_requirements"] == 1


def test_invalid_http_url_rejected():
    draft = sample_draft()
    draft["record"]["source"]["URL_post"] = "file:///etc/passwd"
    with pytest.raises(ValueError):
        prepare_publication(draft)


def test_quoted_prior_notice_dates_are_not_silently_accepted():
    draft = sample_draft()
    draft["record"]["start"] = "2026-09-24T00:00:00+07:00"
    draft["record"]["end"] = "2026-10-26T23:59:00+07:00"
    draft["meta"]["evidence"]["start"] = [
        "SV đã đăng ký tại cơ sở 2 (theo thông báo ngày 24/9/2026) chưa chọn ngày khám."
    ]
    draft["meta"]["evidence"]["end"] = [
        "Theo thông báo ngày 08/10/2026, Nhà trường sẽ bố trí ngày 26/10/2026."
    ]
    draft["record"]["source"]["URL_registration"] = (
        "https://datastudio.google.com/.../e586.../page/demo"
    )
    result = prepare_publication(draft)
    assert "needs_review:start_date_provenance" in result["meta"]["flags"]
    assert "needs_review:end_date_provenance" in result["meta"]["flags"]
    assert "needs_review:URL_registration" in result["meta"]["flags"]
    assert result["meta"]["publication_status"] == "REVIEW_REQUIRED"
