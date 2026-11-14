"""CLI for incremental SP1 ingestion: exercise single-post extraction without the web UI.

  python scripts/ingest_post.py health
  python scripts/ingest_post.py submit post.json [--post-id live-190] [--no-process]
  python scripts/ingest_post.py show live-190
  python scripts/ingest_post.py retry live-190 1
  python scripts/ingest_post.py publish live-190 1 --reviewer admin

post.json: {"raw_content": "...", "url": "...", "publisher": "...", "platform": "...", "date_posted": "YYYY-MM-DD..."}
(a fixture with a "post" key, such as tests/sp1/fixtures/live/post_190_seminar.json, is accepted).
Model: SP1_LLM_PROVIDER / SP1_LLM_BASE_URL / SP1_LLM_MODEL / SP1_LLM_TIMEOUT_SECONDS; store: UNILIFE_LIVE_DB.
"""

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from sp1.live_ingest import IngestError, service_from_env
from sp1.model_client import SP1ModelClient, SP1ModelConfig, SP1ModelError


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("health")
    submit = sub.add_parser("submit")
    submit.add_argument("file", type=Path)
    submit.add_argument("--post-id")
    submit.add_argument("--no-process", action="store_true")
    for name in ("show",):
        sub.add_parser(name).add_argument("post_id")
    for name in ("retry", "publish"):
        item = sub.add_parser(name)
        item.add_argument("post_id")
        item.add_argument("revision", type=int)
        if name == "publish":
            item.add_argument("--reviewer", required=True)
    args = parser.parse_args(argv)
    try:
        if args.command == "health":
            result = SP1ModelClient(SP1ModelConfig.from_env()).health()
        else:
            service = service_from_env()
            if args.command == "submit":
                data = json.loads(args.file.read_text(encoding="utf-8"))
                data = data.get("post", data)
                result = service.submit(data["raw_content"], url=data.get("url"), publisher=data.get("publisher"),
                                        platform=data.get("platform"), date_posted=data.get("date_posted"),
                                        post_id=args.post_id or data.get("post_id"), process=not args.no_process)
            elif args.command == "show":
                result = service.get(args.post_id)
            elif args.command == "retry":
                result = service.retry(args.post_id, args.revision)
            else:
                result = service.publish(args.post_id, args.revision, args.reviewer)
    except (IngestError, SP1ModelError) as exc:
        print(json.dumps({"error": exc.code, "message": exc.message}, ensure_ascii=False))
        return 1
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
