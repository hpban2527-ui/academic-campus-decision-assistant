import hashlib
import json
from copy import deepcopy

import pytest
from jsonschema import Draft202012Validator

from sp1.normalize import ROOT, ConfigError, load_config, normalize


SOURCE = {
    "post_id": "synthetic-1",
    "URL_post": "https://example.org/post",
    "publisher": "Campus Club",
    "platform": "facebook",
    "date_posted": "2026-07-03T09:00:00",
}
RECORD = {
    "post_type": "activity", "title": "Campus event", "domain": "academic",
    "multi_session": False, "window_open": None, "window_close": None,
    "duration_minutes_stated": None, "registration_deadline": None, "mode": "online",
    "location": None, "audience_text": None, "audience_scope": {"cohorts": [], "programs": []},
    "mandatory_stated": None, "recognition_stated": None, "points_stated": None, "fee": None,
    "registration_url": None, "join_url": None, "completion_requirements": [],
}
QUIZ = {"type": "quiz", "threshold": 70, "unit": "percent", "deadline": None}


@pytest.fixture(scope="module")
def config():
    return load_config()


@pytest.fixture(scope="module")
def schemas():
    validators = []
    for name in ("layer_a_record_v2", "activity_v2"):
        schema = json.loads((ROOT / "schemas" / f"{name}.schema.json").read_text(encoding="utf-8"))
        Draft202012Validator.check_schema(schema)
        validators.append(Draft202012Validator(schema))
    return validators


@pytest.fixture
def run(config, schemas):
    def convert(*, flags=(), year_inferred=(), **fields):
        record = {**deepcopy(RECORD), **deepcopy(fields)}
        data = {"record": record, "flags": list(flags), "year_inferred": list(year_inferred), "evidence": {}}
        before = deepcopy(data)
        schemas[0].validate(data)
        result = normalize(data, SOURCE, config)
        assert result == normalize(data, SOURCE, config)
        assert data == before
        schemas[1].validate(result)

        # Find fields that layer B computed or replaced across all scenarios.
        expected = {"activity_id", "campus", "semester_by_program"}
        if result["drl_recognized"] is not None:
            expected.add("drl_recognized")
        if record["mandatory_stated"] is None:
            expected.add("mandatory")
        if record["fee"] is None:
            expected.add("fee")
        if result["audience"]["all_students"]:
            expected.add("audience")
        if record["location"] != result["location"]:
            expected.add("location")
        if result["duration_minutes"] is not None and record["duration_minutes_stated"] is None:
            expected.add("duration_minutes")
        for field in ("window_open", "window_close", "registration_deadline"):
            if record[field] is not None and "T" not in record[field]:
                expected.add(field)
        for index, item in enumerate(record["completion_requirements"]):
            if item["deadline"] is not None and "T" not in item["deadline"]:
                expected.add(f"completion_requirements[{index}].deadline")
        assert expected <= result["meta"]["derived"].keys()
        return result
    return convert


@pytest.mark.parametrize(("fields", "expected", "flag", "rule"), [
    ({"mandatory_stated": True}, None, "needs_review:drl_recognized", "rule:mandatory_no_participation_cue"),
    ({"mandatory_stated": True, "registration_url": "https://example.org/form"}, True, None, "rule:post_type_activity"),
    ({"mandatory_stated": True, "join_url": "https://example.org/join"}, True, None, "rule:post_type_activity"),
    ({"mandatory_stated": True, "recognition_stated": True}, True, None, "rule:post_type_activity"),
    ({}, True, None, "rule:post_type_activity"),
    ({"post_type": "info_only"}, False, None, "rule:post_type_info_only"),
    ({"post_type": "insufficient"}, None, "needs_review:post_type", None),
    ({"post_type": None}, None, "needs_review:post_type", None),
])
def test_recognition(run, fields, expected, flag, rule):
    result = run(**fields)
    assert result["drl_recognized"] is expected
    assert result["meta"]["flags"] == ([flag] if flag else [])
    assert result["meta"]["derived"].get("drl_recognized") == rule


@pytest.mark.parametrize(("field", "key", "value", "expected", "trace"), [
    ("window_open", "open", "2026-09-01T09:15+07:00", "2026-09-01T09:15:00+07:00", None),
    ("window_open", "open", "2026-09-01", "2026-09-01T00:00:00+07:00", "date_only_0000"),
    ("window_close", "close", "2026-09-01T10:15+07:00", "2026-09-01T10:15:00+07:00", None),
    ("window_close", "close", "2026-09-01", "2026-09-01T23:59:00+07:00", "date_only_2359"),
    ("window_open", "open", None, None, None),
    ("window_close", "close", None, None, None),
])
def test_window(run, field, key, value, expected, trace):
    result = run(**{field: value})
    assert result["window"][key] == expected
    assert result["meta"]["time_defaults"].get(field) == trace


def test_reversed_window(run):
    result = run(window_open="2026-09-02", window_close="2026-09-01")
    assert result["window"] == {"open": "2026-09-02T00:00:00+07:00", "close": "2026-09-01T23:59:00+07:00"}
    assert "end_before_start" in result["meta"]["flags"]
    assert result["meta"]["status"] == "failed"


@pytest.mark.parametrize(("fields", "minutes", "source"), [
    ({"duration_minutes_stated": 45, "mode": None}, 45, "stated"),
    ({"mode": None}, None, "unknown"),
    ({"mode": "hybrid"}, None, "unsupported"),
    ({"mode": "offline", "window_open": "2026-09-01T09:15+07:00", "window_close": "2026-09-01T10:30+07:00"}, 75, "window_span"),
    ({"mode": "offline", "window_open": "2026-09-01T09:15+07:00"}, 120, "default_offline_2h"),
    ({"mode": "offline", "window_open": "2026-09-01T09:15+07:00", "window_close": "2026-09-01"}, 120, "default_offline_2h"),
    ({"mode": "offline", "window_open": "2026-09-01T09:15+07:00", "window_close": "2026-09-02T10:00+07:00"}, 120, "default_offline_2h"),
    ({"mode": "offline", "window_open": "2026-09-01"}, None, "unsupported"),
    ({"mode": "offline"}, None, "unsupported"),
    ({"mode": "offline", "window_open": "2026-09-01T09:15+07:00", "window_close": "2026-09-01T09:15+07:00"}, None, "unsupported"),
    ({"mode": "offline", "window_open": "2026-09-01T09:15+07:00", "window_close": "2026-09-01T09:00+07:00"}, None, "unsupported"),
    ({"completion_requirements": [QUIZ], "multi_session": True}, 30, "default_quiz_30m"),
    ({"multi_session": True}, None, "unsupported"),
    ({}, 30, "default_online_30m"),
])
def test_duration(run, fields, minutes, source):
    result = run(**fields)
    assert (result["duration_minutes"], result["duration_source"]) == (minutes, source)
    assert ("duration_minutes" in result["meta"]["unsupported"]) == (source == "unsupported")


@pytest.mark.parametrize(("mode", "location", "campus", "flag"), [
    ("online", None, [], None),
    ("online", "Room A", [], "location_dropped_online"),
    ("offline", None, [], "campus_unknown"),
    ("hybrid", None, [], "campus_unknown"),
    ("offline", "227 Nguyễn Văn Cừ, phường Chợ Quán", ["CS1"], None),
    ("offline", "Cơ sở phường Đông Hoà", ["CS2"], None),
    ("offline", "Nhà Văn hóa Sinh viên", ["Other"], None),
    # "cơ sở 2" must not match inside "cơ sở 227" (bug found in the 2026-11-14 manual check).
    ("offline", "Trường; cơ sở 227 Nguyễn Văn Cừ, TP.HCM", ["CS1"], None),
    ("offline", "một trong hai cơ sở", ["CS1", "CS2"], None),
    ("hybrid", "CS2 or  CS1", ["CS1", "CS2"], None),
    (None, "ĐÔNG  HÒA", ["CS2"], "needs_review:mode"),
    (None, None, [], "needs_review:mode"),
])
def test_place(run, mode, location, campus, flag):
    result = run(mode=mode, location=location)
    assert result["location"] == (None if mode == "online" else location)
    assert result["campus"] == campus
    assert result["meta"]["flags"] == ([flag] if flag else [])
    assert result["meta"]["status"] == ("partial" if mode is None else "valid")
    if location is not None and mode != "online":
        assert result["meta"]["derived"]["campus"] == "dict:campus_v1.0.0"


@pytest.mark.parametrize("value", [None, True, False])
def test_mandatory(run, value):
    result = run(mandatory_stated=value)
    assert result["mandatory"] is (value is True)
    assert result["meta"]["derived"].get("mandatory") == ("team_default:mandatory_false" if value is None else None)


@pytest.mark.parametrize("value", [None, 0, {"amount_vnd": 42000, "per": "team", "deposit": True}])
def test_fee(run, value):
    result = run(fee=value)
    assert result["fee"] == (0 if value is None else value)
    assert result["meta"]["derived"].get("fee") == ("team_default:fee_not_stated_free" if value is None else None)


@pytest.mark.parametrize(("cohorts", "programs"), [([], []), (["K26"], []), ([], ["high_quality"]), (["K26"], ["standard"])])
def test_audience(run, cohorts, programs):
    scope = {"cohorts": cohorts, "programs": programs}
    result = run(audience_scope=scope, audience_text="Campus students")
    assert result["audience"] == {**scope, "all_students": not (cohorts or programs), "text": "Campus students"}
    assert result["meta"]["derived"].get("audience") == (None if cohorts or programs else "team_default:audience_all")


@pytest.mark.parametrize(("day", "semester"), [
    (None, "insufficient_data"), ("2026-05-16", "out_of_scope_semester"),
    ("2026-05-17", "HK3_2025_2026"), ("2026-08-28", "HK3_2025_2026"),
    ("2026-08-29T00:00+07:00", "HK1_2026_2027"), ("2026-11-15", "HK1_2026_2027"),
    ("2026-11-16", "out_of_scope_semester"),
])
def test_semester(run, day, semester):
    assert run(window_open=day)["semester_by_program"] == {"standard": semester, "high_quality": semester}


def test_overlapping_inclusive_semesters_raise(tmp_path):
    config_dir = tmp_path / "data" / "config"
    config_dir.mkdir(parents=True)
    source_dir = ROOT / "data/config"
    config = json.loads((source_dir / "semesters.json").read_text(encoding="utf-8"))
    config["semesters"][1]["programs"]["high_quality"][0] = "2026-08-28"
    (config_dir / "semesters.json").write_text(json.dumps(config), encoding="utf-8")
    (config_dir / "campus_dictionary.json").write_bytes((source_dir / "campus_dictionary.json").read_bytes())
    with pytest.raises(ConfigError, match="Overlapping semesters for high_quality"):
        load_config(tmp_path)


@pytest.mark.parametrize(("deadline", "expected", "trace"), [
    (None, None, None),
    ("2026-09-01", "2026-09-01T23:59:00+07:00", "date_only_2359"),
    ("2026-09-01T10:15+07:00", "2026-09-01T10:15:00+07:00", None),
])
def test_deadlines(run, deadline, expected, trace):
    path = "completion_requirements[0].deadline"
    result = run(registration_deadline=deadline, completion_requirements=[{**QUIZ, "deadline": deadline}])
    assert result["registration_deadline"] == result["completion_requirements"][0]["deadline"] == expected
    assert result["meta"]["time_defaults"].get("registration_deadline") == trace
    assert result["meta"]["time_defaults"].get(path) == trace
    assert ("registration_deadline" in result["meta"]["unsupported"]) == (deadline is None)


@pytest.mark.parametrize(("flags", "title", "mode", "expected", "added"), [
    ((), "Event", "online", "valid", []),
    (("needs_review:domain",), None, None, "partial", ["needs_review:title", "needs_review:mode"]),
    (("invalid_value:fee",), None, "online", "failed", ["needs_review:title"]),
])
def test_status_and_passthrough(run, flags, title, mode, expected, added):
    result = run(flags=flags, year_inferred=["window_open"], title=title, mode=mode, points_stated=3.5)
    assert result["meta"]["flags"] == [*flags, *added]
    assert result["meta"]["status"] == expected
    assert result["meta"]["year_inferred"] == ["window_open"]
    assert result["points_announced"] == 3.5
    assert result["source"] == SOURCE
    assert result["activity_id"] == f"TMP-{hashlib.sha1(SOURCE['URL_post'].encode()).hexdigest()[:8]}-01"


def test_default_config_matches_explicit_config(config):
    data = {"record": deepcopy(RECORD), "flags": [], "year_inferred": [], "evidence": {}}
    assert normalize(data, SOURCE) == normalize(data, SOURCE, config)
