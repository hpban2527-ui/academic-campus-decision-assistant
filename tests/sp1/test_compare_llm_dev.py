import json
from pathlib import Path

import pytest

from scripts.compare_llm_dev import (choose_model, choose_policy, evaluate_models, load_gold,
                                     load_outputs, main, render_report)
from sp1.devdata import dev_ids
from sp1.hybrid import DECIDABLE_FIELDS
from scripts import compare_llm_dev as comparison

FIXTURES = Path(__file__).parent / "fixtures/llm_v2"


def test_model_choice_ties():
    scores = {"a": {"correct": 10, "fabricated": 2, "seconds": 1},
              "b": {"correct": 11, "fabricated": 3, "seconds": 5},
              "c": {"correct": 11, "fabricated": 2, "seconds": 5},
              "d": {"correct": 11, "fabricated": 2, "seconds": 3}}
    assert choose_model(scores) == ["d", "c", "b", "a"]


@pytest.mark.parametrize("field,rc,lc,rf,lf,wins,null_wins,null_losses,expected", [
    ("title", 2, 4, 1, 1, 2, 0, 0, "llm"),
    ("title", 2, 5, 0, 1, 3, 0, 0, "rules"),
    ("title", 3, 4, 0, 0, 1, 1, 0, "llm_if_rules_null"),
    ("title", 3, 4, 0, 0, 1, 1, 1, "rules"),
    ("mode", 3, 4, 0, 0, 1, 0, 0, "agree_else_review"),
    ("mode", 3, 4, 0, 0, 1, 1, 0, "agree_else_review"),
    ("post_type", 3, 3, 0, 0, 0, 0, 0, "agree_else_review"),
    ("mode", 5, 3, 0, 0, 0, 0, 0, "rules"),
])
def test_policy_thresholds(field, rc, lc, rf, lf, wins, null_wins, null_losses, expected):
    evidence = {field: {"rules": {"correct": rc, "fabricated": rf},
                       "llm": {"correct": lc, "fabricated": lf},
                       "wins": wins, "null_wins": null_wins, "null_losses": null_losses}}
    policy = choose_policy(evidence)
    assert policy[field] == expected
    assert policy["activity_type"] == "rules" and policy["_evidence"]["activity_type"]["n"] == 0


def test_recorded_two_models_end_to_end(tmp_path):
    models = load_outputs(FIXTURES, dev_ids())
    assert len(models) == 2
    result = evaluate_models(models, load_gold())
    assert result["ranked"] == ["fake/rules-fallback", "fake/closed-labels"]
    assert result["diagnostics"]["fake/rules-fallback"]["validity"]["roles"] == 0
    assert result["diagnostics"]["fake/closed-labels"]["validity"]["roles"] == 21
    report, policy = tmp_path / "compare.md", tmp_path / "policy.json"
    main(["--outputs", str(FIXTURES), "--report", str(report), "--write-policy", str(policy)])
    assert "not a held-out test evaluation" in report.read_text()
    assert json.loads(policy.read_text())["_model_id"] == result["ranked"][0]
    assert set(DECIDABLE_FIELDS) <= json.loads(policy.read_text()).keys()
    assert render_report(result) == render_report(evaluate_models(models, load_gold()))


def test_incomplete_coverage_rejected():
    models = load_outputs(FIXTURES, dev_ids())
    models["fake/closed-labels"].pop(next(iter(models["fake/closed-labels"])))
    with pytest.raises(ValueError, match="Incomplete gold coverage"):
        evaluate_models(models, load_gold())


def test_foreign_id_rejected_without_loading_post(tmp_path):
    path = tmp_path / "foreign.jsonl"
    path.write_text(json.dumps({"post_id": "not-a-dev-id"}) + "\n")
    with pytest.raises(ValueError, match="Disallowed"):
        load_outputs(tmp_path, dev_ids())


def test_readiness_replay_and_coverage(monkeypatch):
    models = load_outputs(FIXTURES, dev_ids())
    model = "fake/rules-fallback"
    ids = list(models[model])[:2]
    monkeypatch.setattr(comparison, "non_test_ids", lambda: ids)
    rows = {pid: models[model][pid] for pid in ids}
    policy = {**dict.fromkeys(DECIDABLE_FIELDS, "rules"), "_model_id": model}
    report = comparison.readiness({model: rows}, policy)
    assert "Posts: 2" in report and "| plannable |" in report
    rows.pop(ids[0])
    with pytest.raises(ValueError, match="every non-test"):
        comparison.readiness({model: rows}, policy)
