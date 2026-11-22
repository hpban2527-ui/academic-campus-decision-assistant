"""Incremental LLM outputs: several recorded-reply files merge by (post_id, input digest), conflicting replies
fail loudly, and export_llm_inputs --only-missing exports only the posts that still need a model run."""
import importlib.util
import json
from pathlib import Path

import pytest

from sp1.devdata import load_split
from sp1.llm_cache import CacheError, load_replies

ROOT = Path(__file__).resolve().parents[2]
FINAL = ROOT / "data/llm_outputs/final/Qwen__Qwen3.5-4B.jsonl"
REASON = "pytest: incremental LLM output checks"


def _load(name):
    spec = importlib.util.spec_from_file_location(f"test_{name}", ROOT / "scripts" / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


exporter = _load("export_llm_inputs")
LINES = [line for line in FINAL.read_text(encoding="utf-8").splitlines() if line.strip()]
MODEL = json.loads((ROOT / "data/config/merge_policy.json").read_text(encoding="utf-8"))["_model_id"]
SPLIT = {row["post_id"]: row for row in load_split()["posts"]}


def _stale_ids():
    """Posts whose recorded reply answered different prompts (the candidate builder changed after the run)."""
    import sys
    sys.path.insert(0, str(ROOT / "src"))
    from sp1.devdata import final_run_posts
    from sp1.llm_cache import input_digest, prompts_for
    rows = {json.loads(line)["post_id"]: json.loads(line) for line in LINES}
    return [p["post_id"] for p in final_run_posts(REASON, log_path=ROOT / ".pytest_access.jsonl")
            if rows[p["post_id"]]["input_sha256"] != input_digest(prompts_for(p))]


STALE = None


def stale_ids():
    global STALE
    if STALE is None:
        STALE = _stale_ids()
        (ROOT / ".pytest_access.jsonl").unlink(missing_ok=True)
    return STALE


def write(path, lines):
    path.write_bytes(("\n".join(lines) + "\n").encode("utf-8"))
    return path


def _plain(index):
    return {key: {k: v for k, v in row.items() if k != "_file"} for key, row in index.items()}


def test_two_files_merge_to_the_same_replies_as_one(tmp_path):
    first = write(tmp_path / "a.jsonl", LINES[:120])
    second = write(tmp_path / "b.jsonl", LINES[100:])          # 20 posts in both files, same content
    assert _plain(load_replies([first, second], MODEL)) == _plain(load_replies([FINAL], MODEL))


def test_same_post_with_only_different_run_timings_is_not_a_conflict(tmp_path):
    row = json.loads(LINES[0])
    rerun = {**row, "seconds": {"classify": 1.0, "roles": 2.0}, "peak_vram_gb": 9.9}
    merged = load_replies([write(tmp_path / "a.jsonl", [LINES[0]]),
                           write(tmp_path / "b.jsonl", [json.dumps(rerun)])], MODEL)
    kept = merged[(row["post_id"], row["input_sha256"])]
    assert kept["seconds"] == row["seconds"] and kept["_file"] == "a.jsonl"     # first file kept, nothing overwritten


def test_same_post_with_different_content_is_an_error(tmp_path):
    row = json.loads(LINES[0])
    changed = {**row, "replies": {**row["replies"], "classify": row["replies"]["classify"].replace("activity", "info_only", 1)}}
    with pytest.raises(CacheError) as caught:
        load_replies([write(tmp_path / "old.jsonl", LINES[:3]),
                      write(tmp_path / "new.jsonl", [json.dumps(changed)])], MODEL)
    message = str(caught.value)
    assert row["post_id"] in message and "old.jsonl" in message and "new.jsonl" in message


def _export(tmp_path, *extra):
    out = tmp_path / "new.jsonl"
    code = exporter.main(["--split", "all", "--final-run-include-test", "--reason", REASON, "--out", str(out),
                          "--access-log", str(tmp_path / "access.jsonl"), "--only-missing", *extra])
    return code, out


def test_only_missing_exports_just_the_posts_without_output(tmp_path, capsys):
    missing = [json.loads(line)["post_id"] for line in (LINES[5], LINES[-1])]
    have = [line for i, line in enumerate(LINES) if i not in (5, len(LINES) - 1)]
    code, out = _export(tmp_path, "--llm", str(write(tmp_path / "a.jsonl", have[:50])),
                        "--llm", str(write(tmp_path / "b.jsonl", have[50:])))
    rows = [json.loads(line) for line in out.read_text(encoding="utf-8").splitlines()]
    expected = sorted(set(missing) | set(stale_ids()), key=lambda pid: SPLIT[pid]["position"])
    assert code == 0 and [r["post_id"] for r in rows] == expected
    assert [r["position"] for r in rows] == [SPLIT[pid]["position"] for pid in expected]
    assert rows[0]["classify_prompt"].count("<announcement>") == 1
    assert "Posts without LLM output:" in capsys.readouterr().out


def test_only_missing_with_complete_output_exports_only_stale_prompts(tmp_path, capsys):
    code, out = _export(tmp_path)                                         # default: the committed final run
    rows = [json.loads(line) for line in out.read_text(encoding="utf-8").splitlines()] if out.exists() else []
    assert code == 0 and [r["post_id"] for r in rows] == stale_ids()


def test_only_missing_with_answers_for_current_prompts_writes_nothing(tmp_path, capsys):
    current = tmp_path / "current.jsonl"
    rows = [json.loads(line) for line in LINES]
    exported = tmp_path / "all.jsonl"
    exporter.main(["--split", "all", "--final-run-include-test", "--reason", REASON, "--out", str(exported),
                   "--access-log", str(tmp_path / "access.jsonl")])
    digests = {}
    for line in exported.read_text(encoding="utf-8").splitlines():
        row = json.loads(line)
        digests[row["post_id"]] = exporter._digest(row)
    write(current, [json.dumps({**r, "input_sha256": digests[r["post_id"]]}, ensure_ascii=False) for r in rows])
    code, out = _export(tmp_path, "--llm", str(current))
    assert code == 0 and not out.exists()
    assert "Nothing to export" in capsys.readouterr().out


@pytest.mark.parametrize("argv", [
    ["--posts", "data/redteam/redteam_v1.json", "--only-missing"],
    ["--split", "dev", "--llm", str(FINAL)],
])
def test_only_missing_argument_errors(tmp_path, argv):
    with pytest.raises(SystemExit) as caught:
        exporter.main([*argv, "--out", str(tmp_path / "x.jsonl")])
    assert caught.value.code == 2 and not (tmp_path / "x.jsonl").exists()
