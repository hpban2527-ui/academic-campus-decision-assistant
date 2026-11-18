"""Review drafts cannot silently become approved runtime or evaluation data."""
import json
from pathlib import Path
import sys

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
from validate_ai_review_export import validate_export


def test_ai_drafts_are_rejected_as_human_approved(tmp_path):
    path = tmp_path / "drafts.json"
    path.write_text(json.dumps({"schema": "unilife-ai-assisted-review/1.0", "kind": "review_progress", "items": []}), encoding="utf-8")
    with pytest.raises(ValueError, match="not AI drafts or progress"):
        validate_export(path)


def test_empty_human_export_is_rejected(tmp_path):
    path = tmp_path / "empty.json"
    path.write_text(json.dumps({"schema": "unilife-ai-assisted-review/1.0", "kind": "human_reviewed_records",
                               "label": "HUMAN_REVIEWED_AI_ASSISTED_NOT_BLIND_GOLD", "items": []}), encoding="utf-8")
    with pytest.raises(ValueError, match="No approved records"):
        validate_export(path)
