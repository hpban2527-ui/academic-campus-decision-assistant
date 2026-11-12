"""Ensure teammates' accepted source/data/test files were not modified during H4/H5.

The manifest stores the git blob hash (including Git's blob header), not a
bare file SHA. Any intentional update must go through review and a manifest
change in the same PR.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MANIFEST = ROOT / "docs" / "TEAM_SOURCE_LOCK_20261029.json"


def main() -> None:
    manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
    failures: list[str] = []
    for item in manifest["files"]:
        relpath = item["path"]
        path = ROOT / relpath
        if not path.is_file():
            failures.append(f"MISSING {relpath}")
            continue
        raw = path.read_bytes()
        digest = hashlib.sha1(b"blob " + str(len(raw)).encode() + b"\0" + raw).hexdigest()
        if digest != item["blob_sha"]:
            failures.append(f"CHANGED {relpath} expected={item['blob_sha']} actual={digest}")
    print(f"Team source integrity: {len(manifest['files'])-len(failures)}/{len(manifest['files'])} unchanged")
    if failures:
        raise SystemExit("\n".join(failures))


if __name__ == "__main__":
    main()
