"""scripts/admin_rebuild.py: step order, stop on the first failure, summary read from the files, handover diff,
and two runs on the same inputs giving the same data files apart from timestamps. Real runs go to a temp
--out-dir with a temp access log; the committed data/ is never written."""
import csv
import hashlib
import importlib.util
import json
import shutil
import socket
from collections import Counter
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
REASON = "pytest: admin rebuild into a temp directory"
_SPEC = importlib.util.spec_from_file_location("admin_rebuild_under_test", ROOT / "scripts/admin_rebuild.py")
admin = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(admin)

DATA_FILES = ["data/activity_store_v2.json", "data/handover/activities_sp3.json", "data/handover/sidecar.json",
              "data/handover/blocked.json", "data/handover/bindings.json",
              "data/handover/activity_features_sp1.json", "data/handover/features_provenance.json",
              "data/review/queue.csv", "reports/sp1_final_readiness.md", "reports/sp1_handover_readiness.md",
              "reports/sp2_binding_readiness.md"]
TIMESTAMPS = {"data/activity_store_v2.json": ("generated_at",), "data/handover/sidecar.json": ("store_generated_at",)}
# Files whose content does not depend on the MinHash estimate (see the reproducibility note in the report).
SAME_AS_COMMITTED = ["data/handover/activities_sp3.json", "data/handover/blocked.json", "data/handover/bindings.json",
                     "data/handover/activity_features_sp1.json", "data/handover/features_provenance.json",
                     "data/review/queue.csv"]


def _digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _content(root, name):
    path = root / name
    if not name.endswith(".json"):
        return path.read_bytes()
    value = json.loads(path.read_text(encoding="utf-8"))
    for key in TIMESTAMPS.get(name, ()):
        value.pop(key)
    return value


# -- fast tests with a recording runner ----------------------------------------------------------------

def test_steps_run_in_order_with_their_arguments(tmp_path, monkeypatch):
    calls = []
    llm = [tmp_path / "a.jsonl", tmp_path / "b.jsonl"]
    argv = ["--reason", REASON, "--out-dir", str(tmp_path), "--access-log", str(tmp_path / "log.jsonl"),
            "--decisions", str(tmp_path / "decisions.csv"), "--llm", str(llm[0]), "--llm", str(llm[1])]
    # The recording runner writes no files, so the report (read from the files) is stubbed out.
    for name in ("summary", "diff", "print_report"):
        monkeypatch.setattr(admin, name, lambda *args: None)
    code = admin.main(argv, runner=lambda name, step_argv: calls.append((name, step_argv)))
    assert code == 0
    assert [name for name, _ in calls] == list(admin.STEPS) == [
        "build_activity_store", "build_handover", "build_bindings", "build_features", "export_review_queue"]
    steps = dict(calls)
    out = ["--out-dir", str(tmp_path)]
    log = ["--access-log", str(tmp_path / "log.jsonl")]
    assert steps["build_activity_store"] == [*out, "--reason", REASON, *log, "--llm", str(llm[0]), "--llm", str(llm[1]),
                                             "--decisions", str(tmp_path / "decisions.csv")]
    assert steps["build_bindings"] == [*out, "--reason", REASON, *log]
    assert steps["build_handover"] == steps["build_features"] == steps["export_review_queue"] == out


@pytest.mark.parametrize("failure", [ValueError("3 posts have no LLM output"), SystemExit(2)])
def test_stops_at_the_first_failing_step(tmp_path, capsys, failure):
    calls = []

    def runner(name, step_argv):
        calls.append(name)
        if name == "build_bindings":
            raise failure

    code = admin.main(["--reason", REASON, "--out-dir", str(tmp_path)], runner=runner)
    assert code == 1
    assert calls == ["build_activity_store", "build_handover", "build_bindings"]
    err = capsys.readouterr().err
    assert "FAILED at step 3/5 (build_bindings)" in err


def test_a_step_returning_non_zero_is_a_failure(monkeypatch):
    class Fake:
        @staticmethod
        def main(argv):
            return 3

    monkeypatch.setitem(admin._modules, "build_handover", Fake)
    with pytest.raises(admin.StepFailed, match="returned 3"):
        admin.run_step("build_handover", [])


def test_diff_reports_added_removed_and_changed_fields():
    before = {"activities": {"A": {"activity_id": "A", "title": "x"}, "B": {"activity_id": "B", "title": "y"}},
              "positions": {"A": 1, "B": 2}, "n_posts": 2}
    after = {"activities": {"A": {"activity_id": "A", "title": "x2", "mode": "online"}, "C": {"activity_id": "C"}},
             "positions": {"A": 1, "B": 2, "C": 3}, "n_posts": 3}
    changes = admin.diff(before, after)
    assert changes["added"] == ["C"] and changes["removed"] == ["B"]
    assert changes["changed"] == {"A": ["mode", "title"]} and changes["n_posts"] == (2, 3)
    assert admin.diff(None, after)["added"] == ["A", "C"] and admin.diff(None, after)["previous"] is False


# -- real runs (about 10 s each) -----------------------------------------------------------------------

@pytest.fixture(scope="module")
def runs(tmp_path_factory):
    """Run 1 into a fresh dir A. Copy A to B, edit B's handover (drop one activity, add a fake one, change a
    title), then run 2 into B. Network access is blocked for both runs."""
    base = tmp_path_factory.mktemp("admin_rebuild")
    first, second, log = base / "A", base / "B", base / "access.jsonl"
    committed_log = _digest(ROOT / "data/gold/final_run_access_log.jsonl")
    committed = {name: _digest(ROOT / name) for name in DATA_FILES}
    patch = pytest.MonkeyPatch()

    def no_network(*args, **kwargs):
        raise AssertionError("admin_rebuild tried to open a network connection")

    patch.setattr(socket.socket, "connect", no_network)
    patch.setattr(socket, "create_connection", no_network)
    try:
        argv = ["--reason", REASON, "--access-log", str(log)]
        code_1 = admin.main([*argv, "--out-dir", str(first)])
        shutil.copytree(first, second)
        snapshot_1 = {name: _content(first, name) for name in DATA_FILES}
        path = second / admin.ACTIVITIES
        activities = json.loads(path.read_text(encoding="utf-8"))
        dropped, edited = activities[0]["activity_id"], activities[1]["activity_id"]
        activities = activities[1:] + [{**activities[1], "activity_id": "FAKE-REMOVED"}]
        activities[0] = {**activities[0], "title": "edited by the test"}
        path.write_text(json.dumps(activities, ensure_ascii=False), encoding="utf-8")
        before_2 = admin.snapshot(second)
        code_2 = admin.main([*argv, "--out-dir", str(second)])
        after_2 = admin.snapshot(second)
    finally:
        patch.undo()
    assert _digest(ROOT / "data/gold/final_run_access_log.jsonl") == committed_log
    assert {name: _digest(ROOT / name) for name in DATA_FILES} == committed      # repo data untouched
    return {"first": first, "second": second, "codes": (code_1, code_2), "snapshot_1": snapshot_1,
            "dropped": dropped, "edited": edited, "diff_2": admin.diff(before_2, after_2), "log": log}


def test_real_runs_succeed_and_log_their_corpus_reads(runs):
    assert runs["codes"] == (0, 0)
    entries = [json.loads(line) for line in runs["log"].read_text(encoding="utf-8").splitlines()]
    assert len(entries) == 4 and {e["reason"] for e in entries} == {REASON}    # store + bindings, twice


def test_two_runs_give_identical_data_files_apart_from_timestamps(runs):
    for name in DATA_FILES:
        assert _content(runs["second"], name) == runs["snapshot_1"][name], name


def test_summary_matches_the_output_files(runs):
    out = runs["first"]
    counts = admin.summary(out)
    store = json.loads((out / admin.STORE).read_text(encoding="utf-8"))
    bindings = json.loads((out / admin.BINDINGS).read_text(encoding="utf-8"))["bindings"]
    with open(out / admin.QUEUE, encoding="utf-8-sig", newline="") as handle:
        queue = list(csv.DictReader(handle))
    assert counts == {
        "n_posts": len(store["records"]),
        "n_without_llm": sum(not r["llm_available"] for r in store["records"]),
        "plannable": sum(r["plannable"] for r in store["records"]),
        "handed_over": len(json.loads((out / admin.ACTIVITIES).read_text(encoding="utf-8"))),
        "blocked": len(json.loads((out / admin.BLOCKED).read_text(encoding="utf-8"))),
        "bindings_by_operation": dict(Counter(b["operation"] for b in bindings)),
        "review_queue_rows": len(queue),
        "review_decisions": {"applied": sum(bool(r["review"]) and not r["review"]["stale"] for r in store["records"]),
                             "stale": sum(bool(r["review"]) and r["review"]["stale"] for r in store["records"]),
                             "rejected": len(store["decision_problems"])}}
    assert counts["handed_over"] + counts["blocked"] == counts["n_posts"]


def test_diff_against_the_previous_handover(runs):
    changes = runs["diff_2"]
    assert changes["previous"] is True
    assert changes["added"] == [runs["dropped"]]
    assert changes["removed"] == ["FAKE-REMOVED"]
    assert changes["changed"] == {runs["edited"]: ["title"]}


def test_printed_report(runs, capsys):
    admin.print_report(admin.summary(runs["first"]), runs["diff_2"], None, admin.snapshot(runs["second"]))
    out = capsys.readouterr().out
    assert "review queue rows:" in out and "added 1, removed 1, changed 1" in out
    assert "review decisions:" in out and " applied, 0 stale, 0 rejected rows" in out
    assert "~ position " in out and ": title" in out


def test_rebuild_reproduces_the_committed_handover(runs):
    for name in SAME_AS_COMMITTED:
        assert _content(runs["first"], name) == _content(ROOT, name), name
