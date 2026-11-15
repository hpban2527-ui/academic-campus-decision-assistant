import json
from copy import deepcopy
from pathlib import Path

import jsonschema
import pytest

from sp1.candidates import build_candidates
from sp1.devdata import dev_posts
from sp1.extract_v2 import extract_v2
from sp1.hybrid import DECIDABLE_FIELDS, merge
from sp1.llm_v2 import decide
from sp1.normalize import normalize
from sp1.preprocess import preprocess
from sp1.segment import segment

ROOT = Path(__file__).resolve().parents[2]


def fake_replies(post):
    pre = preprocess(post["raw_content"])
    cands = build_candidates(pre, segment(pre))
    return {"classify": json.dumps({"post_type": "activity", "post_type_evidence": "L1",
            "activity_type": "other", "domain": "skills", "mode": "online", "mode_evidence": "L1"}),
            "roles": json.dumps({"title": "H1" if any(c.id == "H1" for c in cands) else "none",
            "multi_session": None, "dates": {c.id: "other" for c in cands if c.kind == "date"},
            "times": {c.id: "other" for c in cands if c.kind == "time"},
            "urls": {c.id: "other" for c in cands if c.kind == "url"}})}


@pytest.mark.parametrize("policy,expected,method", [("rules", "academic", "rules"),
    ("llm", "skills", "llm"), ("llm_if_rules_null", "academic", "rules"),
    ("agree_else_review", "academic", "rules")])
def test_policy_modes(policy, expected, method):
    post = dev_posts()[0]
    rules = extract_v2(post)
    rules["layer_a"]["record"]["domain"] = "academic"
    before = deepcopy(rules)
    decision = decide(post, fake_replies(post))
    output = merge(rules, decision, {"domain": policy})
    assert output["layer_a"]["record"]["domain"] == expected
    assert output["field_methods"]["domain"] == method
    assert rules == before
    if policy == "agree_else_review":
        assert "needs_review:domain" in output["layer_a"]["flags"]


def test_null_agree_and_fallback():
    post = dev_posts()[0]
    rules = extract_v2(post)
    rules["layer_a"]["record"]["domain"] = None
    decision = decide(post, fake_replies(post))
    assert merge(rules, decision, {"domain": "llm_if_rules_null"})["layer_a"]["record"]["domain"] == "skills"
    rules["layer_a"]["record"]["domain"] = "skills"
    assert merge(rules, decision, {"domain": "agree_else_review"})["field_methods"]["domain"] == "agree"
    fallback = merge(rules, None, dict.fromkeys(DECIDABLE_FIELDS, "llm"))
    assert fallback["layer_a"] == rules["layer_a"]
    assert all(fallback["field_methods"][f] == "rules_fallback" for f in DECIDABLE_FIELDS)


def test_mode_without_evidence():
    post = dev_posts()[0]
    replies = fake_replies(post)
    classification = json.loads(replies["classify"])
    classification["mode_evidence"] = None
    replies["classify"] = json.dumps(classification)
    output = merge(extract_v2(post), decide(post, replies), {"mode": "llm"})
    assert output["layer_a"]["record"]["mode"] is None


def test_dev_invariants_with_fake_client():
    schema = json.loads((ROOT / "schemas/layer_a_record_v2.schema.json").read_bytes())["$defs"]["record"]
    activity_schema = json.loads((ROOT / "schemas/activity_v2.schema.json").read_bytes())
    for post in dev_posts():
        replies = fake_replies(post)
        def client(prompt):
            return replies["classify" if prompt.startswith("# prompt: sp1_classify") else "roles"]
        rules = extract_v2(post)
        output = merge(rules, decide(post, client), dict.fromkeys(DECIDABLE_FIELDS, "llm"))
        jsonschema.validate(output["layer_a"]["record"], schema)
        for field, value in rules["layer_a"]["record"].items():
            if field not in DECIDABLE_FIELDS:
                assert output["layer_a"]["record"][field] == value
        for spans in [*output["layer_a"]["evidence"].values(), output["classification"]["evidence"]]:
            for span in spans:
                assert span["text"] == post["raw_content"][span["start"]:span["end"]]
        source = {key: post.get(key) for key in ("post_id", "date_posted", "publisher", "platform")}
        source["URL_post"] = post["url"]
        activity = normalize(output["layer_a"], source)
        jsonschema.validate(activity, activity_schema)


def test_close_follows_llm_when_open_comes_from_another_day():
    # Synthetic: rules took an admin step "05-08/10" as the window, the LLM chose the event on 25/10.
    rules = {"method": "rules_v2", "classification": {"activity_type": "contest"},
             "layer_a": {"record": {"window_open": "2026-10-05", "window_close": "2026-10-08"},
                         "evidence": {"window_open": [], "window_close": []}, "flags": [], "year_inferred": []}}
    decision = {"classify": {}, "values": {"record": {"window_open": "2026-10-25T07:30+07:00", "window_close": None},
                                           "evidence": {}, "flags": [], "year_inferred": []}}
    out = merge(rules, decision, {"window_open": "llm", "window_close": "llm_if_rules_null"})
    assert out["layer_a"]["record"]["window_close"] is None
    assert out["field_methods"]["window_close"] == "llm_consistency"
    # Same day: the rules closing is kept.
    decision["values"]["record"]["window_open"] = "2026-10-05T08:00+07:00"
    out = merge(rules, decision, {"window_open": "llm", "window_close": "llm_if_rules_null"})
    assert out["layer_a"]["record"]["window_close"] == "2026-10-08"
