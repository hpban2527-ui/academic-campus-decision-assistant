import json
from pathlib import Path

import pytest

from scripts.export_llm_inputs import export, export_rows
from sp1.devdata import TestSetAccessError as AccessError, dev_ids, non_test_ids


@pytest.mark.parametrize("split", ["test", "all"])
def test_refuse_held_out_before_writing(split, tmp_path):
    target = tmp_path / "refused.jsonl"
    with pytest.raises(AccessError, match="final-run"):
        export(split, target)
    assert not target.exists()


def test_final_flag_without_reason_is_refused(tmp_path):
    with pytest.raises(AccessError, match="reason"):
        export("all", tmp_path / "all.jsonl", True)
    assert not (tmp_path / "all.jsonl").exists()


def test_final_run_exports_every_post_and_logs_the_access(tmp_path):
    log = tmp_path / "access.jsonl"
    rows = export("all", tmp_path / "all.jsonl", True, "final batch run for the activity store", log)
    split = json.loads((Path(__file__).resolve().parents[2] / "data/gold/split_v2.json").read_bytes())
    assert [r["post_id"] for r in rows] == [p["post_id"] for p in split["posts"]]
    entries = [json.loads(line) for line in log.read_text(encoding="utf-8").splitlines()]
    assert len(entries) == 1 and entries[0]["n_posts"] == len(rows) and "test" in entries[0]["splits"]
    for row in rows:
        assert row["classify_prompt"].count("<announcement>") == 1


def test_dev_reader_still_refuses_test_posts():
    from sp1 import devdata
    test_id = next(p["post_id"] for p in devdata.load_split()["posts"] if p["split"] == "test")
    with pytest.raises(AccessError):
        devdata.get_post(test_id)


def test_deterministic_export(tmp_path):
    path = tmp_path / "dev.jsonl"
    rows = export("dev", path)
    first = path.read_bytes()
    export("dev", path)
    assert path.read_bytes() == first
    assert [r["post_id"] for r in rows] == dev_ids()
    assert [r["post_id"] for r in export_rows("non_test")] == non_test_ids()
    for row in rows:
        assert row["classify_prompt"].count("<announcement>") == 1
        assert row["roles_prompt"].count("</announcement>") == 1


def test_notebook_helpers_and_dry_run(tmp_path):
    root = Path(__file__).resolve().parents[2]
    notebook = json.loads((root / "notebooks/sp1_llm_v2_kaggle.ipynb").read_bytes())
    assert notebook["nbformat"] == 4
    cells = ["".join(cell["source"]) for cell in notebook["cells"]]
    assert "DRY_RUN = False" in cells[0]
    for cell in cells:
        compile(cell, "notebook", "exec")
    namespace = {}
    exec(cells[0], namespace)
    inp = tmp_path / "dev.jsonl"
    row = next(export_rows("dev"))
    inp.write_text(json.dumps(row) + "\n", encoding="utf-8")
    namespace.update(DRY_RUN=True, INPUT_FILE=str(inp), OUTPUT_DIR=str(tmp_path / "outputs"), MODELS=["fake/a"])
    for cell in cells[1:]:
        exec(cell, namespace)
    output = tmp_path / "outputs/dry_run/FAKE__fake__a.jsonl"
    before = output.read_bytes()
    exec(cells[-1], namespace)
    assert output.read_bytes() == before
    assert namespace["clean_reply"](" <think>{bad}</think> {}") == ("{}", 1)
    with output.open("ab") as stream:
        stream.write(b'{"partial":')
    namespace["read_completed"](output, "FAKE/fake/a", {row["post_id"]: namespace["input_digest"](row)})
    assert output.read_bytes() == before
    with pytest.raises(ValueError, match="Resume"):
        namespace["read_completed"](output, "another-model", {})
