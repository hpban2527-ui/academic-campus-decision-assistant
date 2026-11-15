"""Lenient replay mode of the LLM reply parser (used by decide()).

It may only remove model choices, never add a value, so grounding by construction still holds.
"""
import json

import pytest

from sp1.llm_v2 import LLMReplyError, decide, parse_classify, parse_roles

from test_llm_v2 import CLASS, POST, setup_roles


def test_extra_classify_key_is_dropped_with_warning():
    warnings = []
    reply = json.dumps({**CLASS, "domain_evidence": None})
    with pytest.raises(LLMReplyError):
        parse_classify(reply, 5)                       # strict default unchanged
    obj = parse_classify(reply, 5, strict=False, warnings=warnings)
    assert obj == CLASS and warnings == ["extra_key:domain_evidence"]


def test_invalid_activity_type_or_domain_becomes_null():
    warnings = []
    obj = parse_classify(json.dumps({**CLASS, "activity_type": "party", "domain": "tech"}), 5,
                         strict=False, warnings=warnings)
    assert obj["activity_type"] is None and obj["domain"] is None
    assert sorted(warnings) == ["bad_enum_dropped:activity_type", "bad_enum_dropped:domain"]


def test_bad_mode_evidence_removes_mode_only():
    obj = parse_classify(json.dumps({**CLASS, "mode_evidence": "L99"}), 5, strict=False, warnings=[])
    assert obj["mode"] is None and obj["mode_evidence"] is None and obj["post_type"] == "activity"


@pytest.mark.parametrize("change", [{"post_type": "event"}, {"post_type_evidence": "L99"}])
def test_core_classify_errors_still_reject(change):
    with pytest.raises(LLMReplyError):
        parse_classify(json.dumps({**CLASS, **change}), 5, strict=False, warnings=[])


def test_roles_unknown_missing_and_bad_roles_are_neutralised():
    _, _, cands, roles = setup_roles()
    roles["dates"] = {"D1": "first_start", "D9": "first_end"}          # D9 unknown, D2 missing
    roles["times"] = {"T1": "first_start", "T2": "lunch", "T3": "other"}  # bad role
    roles["title"] = "H7"
    roles["extra"] = 1
    warnings = []
    obj = parse_roles(json.dumps(roles), cands, strict=False, warnings=warnings)
    assert obj["dates"] == {"D1": "first_start", "D2": "other"}
    assert obj["times"]["T2"] == "other" and obj["title"] == "none" and "extra" not in obj
    assert set(warnings) == {"extra_key:extra", "unknown_id_dropped:D9", "missing_id_as_other:D2",
                             "bad_role_as_other:T2", "unknown_title_dropped"}
    # The cleaned object is valid under the strict contract.
    assert parse_roles(json.dumps(obj), cands) == obj


def test_roles_broken_structure_still_rejects():
    _, _, cands, roles = setup_roles()
    roles["dates"] = ["D1"]
    with pytest.raises(LLMReplyError):
        parse_roles(json.dumps(roles), cands, strict=False, warnings=[])


def test_decide_uses_lenient_mode_and_records_warnings():
    _, _, _, roles = setup_roles()
    roles["dates"]["D9"] = "first_start"
    replies = {"classify": json.dumps({**CLASS, "domain_evidence": "L1"}), "roles": json.dumps(roles)}
    result = decide(POST, replies)
    assert result["classify"] is not None and result["roles"] is not None and result["errors"] == []
    codes = {w["code"] for w in result["warnings"]}
    assert codes == {"extra_key:domain_evidence", "unknown_id_dropped:D9"}
    assert result["values"]["record"].get("window_open") is None     # D9 never becomes a value


def test_candidate_text_written_as_key_is_mapped_to_its_id():
    _, _, cands, roles = setup_roles()
    d1 = next(c for c in cands if c.kind == "date" and c.id == "D1")
    roles["dates"] = {d1.text: "first_start"}                 # model wrote the date, not "D1"
    warnings = []
    obj = parse_roles(json.dumps(roles), cands, strict=False, warnings=warnings)
    assert obj["dates"]["D1"] == "first_start"
    assert "text_mapped_to_id:D1" in warnings
    assert parse_roles(json.dumps(obj), cands) == obj        # strict-valid after cleaning


def test_text_not_matching_exactly_one_candidate_is_still_dropped():
    _, _, cands, roles = setup_roles()
    roles["dates"] = {"D1": "first_end", "99/99/2026": "first_start"}
    d1 = next(c for c in cands if c.kind == "date" and c.id == "D1")
    roles["dates"][d1.text] = "first_start"                  # D1 already present: no remap
    warnings = []
    obj = parse_roles(json.dumps(roles), cands, strict=False, warnings=warnings)
    assert obj["dates"]["D1"] == "first_end"
    assert "unknown_id_dropped:99/99/2026" in warnings and f"unknown_id_dropped:{d1.text}" in warnings
