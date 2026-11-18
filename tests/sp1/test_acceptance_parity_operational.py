"""The offline viewer's JavaScript policy (scripts/activity_acceptance.js) must route every operational
input exactly like the backend policy (src/sp1/acceptance.py): one policy, a tested mirror."""
from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

import pytest

from sp1.acceptance import assess_activity, load_policy
from sp1.devdata import get_post
from sp1.preprocess import preprocess

ROOT = Path(__file__).resolve().parents[2]


@pytest.mark.skipif(shutil.which("node") is None, reason="node is not installed")
def test_javascript_mirror_matches_backend_policy_on_all_annotations(tmp_path):
    policy = load_policy()
    annotations = json.loads((ROOT / "data/sp1_annotations/ai_annotations_20261118.json").read_text(encoding="utf-8"))
    items = []
    for item in annotations["items"]:
        row = {"record": item["record"], "unsure": item["unsure"], "review": {},
               "source_text": preprocess(get_post(item["post_id"])["raw_content"]).text}
        items.append({"position": item["position"], **row, "data_policy": assess_activity(row, policy)})
    path = tmp_path / "parity.json"
    path.write_text(json.dumps({"acceptance_policy": policy, "items": items}, ensure_ascii=False), encoding="utf-8")
    result = subprocess.run(["node", str(ROOT / "scripts/check_acceptance_parity.cjs"), str(path)],
                            capture_output=True, text=True, timeout=120)
    assert result.returncode == 0, result.stderr[-2000:]
    assert f"all {len(items)} records" in result.stdout
