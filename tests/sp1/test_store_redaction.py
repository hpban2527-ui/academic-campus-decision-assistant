"""Regression: the store writer must not mask digits inside hashes or identifiers."""
import importlib.util
from pathlib import Path

_SPEC = importlib.util.spec_from_file_location(
    "build_activity_store", Path(__file__).resolve().parents[2] / "scripts" / "build_activity_store.py")
store = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(store)

# A real digest whose middle "0010671451..." looks like a phone number.
DIGEST = "33b00055d71d2c2b6c6097428c9784bec3b001067145cf256e518eff303b69fc"


def test_hash_and_ids_are_not_redacted():
    out = store.redact({"text_sha256": DIGEST, "source": {"post_id": "0901234567"}})
    assert out["text_sha256"] == DIGEST
    assert out["source"]["post_id"] == "0901234567"


def test_text_is_still_redacted():
    out = store.redact({"location": "Liên hệ 0901234567"})
    assert "0901234567" not in out["location"]
