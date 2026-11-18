"""Regression: the dataset writer must not mask digits inside hashes or identifiers."""
from sp1.operational import redact

# A real digest whose middle "0010671451..." looks like a phone number.
DIGEST = "33b00055d71d2c2b6c6097428c9784bec3b001067145cf256e518eff303b69fc"


def test_hash_and_ids_are_not_redacted():
    out = redact({"text_sha256": DIGEST, "source": {"post_id": "0901234567"}})
    assert out["text_sha256"] == DIGEST
    assert out["source"]["post_id"] == "0901234567"


def test_text_is_still_redacted():
    out = redact({"location": "Liên hệ 0901234567"})
    assert "0901234567" not in out["location"]
