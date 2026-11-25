"""The running app never ingests posts or calls the SP1 model: no /api/sp1 router, no real_live source.

New announcements reach the app only through the admin offline batch (scripts/update_activity_data.py). There is no
SP1_LIVE_INGEST switch: setting it (or any value) must not bring the router back.
"""
import ast
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from api.server import app

ROOT = Path(__file__).resolve().parents[2]
client = TestClient(app)
PLAN = {"scenario": "first_plan", "total_target": 80}
PREFERENCE = {  # synthetic, same shape as tests/personalization/conftest.py
    "topic_preferences": [{"topic_id": "mathematics", "weight": 5}], "category_priorities": [],
    "campus_preferences": [], "mode_preferences": [], "time_preferences": [],
    "limits": {"max_activities": 4, "max_duration_minutes": 600, "max_fee": 200000},
    "hard_exclusions": {"campus_ids": [], "modes": [], "time_slots": []}, "strategy": "BALANCED"}


@pytest.mark.parametrize("method,path", [
    ("get", "/api/sp1/posts"), ("post", "/api/sp1/posts"), ("get", "/api/sp1/posts/post-190"),
    ("post", "/api/sp1/posts/post-190/revisions/1/process"),
    ("post", "/api/sp1/posts/post-190/revisions/1/publish"), ("get", "/api/sp1/model/health"),
])
def test_live_ingestion_endpoints_are_gone(method, path):
    response = getattr(client, method)(path, **({"json": {"raw_content": "x"}} if method == "post" else {}))
    assert response.status_code == 404


@pytest.mark.parametrize("method,path,body", [
    ("get", "/api/sp3/catalog", None),
    ("post", "/api/sp3/demo/plan", PLAN),
    ("post", "/api/sp3/personalized/plan", {"confirmed": True, "preference": PREFERENCE, "total_target": 80}),
])
def test_real_live_source_is_rejected(method, path, body):
    response = getattr(client, method)(f"{path}?source=real_live", **({"json": body} if body else {}))
    assert response.status_code == 422
    assert response.json()["detail"] == "source must be 'synthetic' or 'real'"


def test_synthetic_and_real_sources_still_work():
    assert client.post("/api/sp3/demo/plan", json=PLAN).json()["data_source"] == "SYNTHETIC-DEMO"
    real = client.post("/api/sp3/demo/plan?source=real&term_id=HK1_2026_2027", json=PLAN).json()
    assert real["data_source"] == "OPERATIONAL-DATASET" and real["live_published"] == {}
    catalog = client.get("/api/sp3/catalog?source=real&term_id=HK1_2026_2027").json()
    assert catalog["data_source"] == "OPERATIONAL-DATASET"
    assert all(row["live_revision"] is None for row in catalog["activities"])


PROBE = """
import json, sys
from fastapi.testclient import TestClient
from api.server import app
c = TestClient(app)
print(json.dumps({
    "posts": c.get("/api/sp1/posts").status_code,
    "health": c.get("/api/sp1/model/health").status_code,
    "real_live": c.get("/api/sp3/catalog?source=real_live").status_code,
    "sp1_routes": sorted(r.path for r in app.routes if getattr(r, "path", "").startswith("/api/sp1")),
    "model_modules": sorted(m for m in sys.modules if m in ("sp1.live_ingest", "sp1.model_client", "api.live_posts",
                                                          "api.live_state")),
}))
"""


@pytest.mark.parametrize("flag", [None, "0", "1", "true"])
def test_sp1_live_ingest_flag_does_not_enable_ingestion(flag):
    """A fresh process with SP1_LIVE_INGEST unset/off/on: same answer, and no model client is even imported."""
    env = {k: v for k, v in os.environ.items() if k != "SP1_LIVE_INGEST"}
    env["PYTHONPATH"] = str(ROOT / "src")
    if flag is not None:
        env["SP1_LIVE_INGEST"] = flag
    result = subprocess.run([sys.executable, "-c", PROBE], cwd=ROOT, env=env, capture_output=True, text=True,
                            timeout=120)
    assert result.returncode == 0, result.stderr
    probe = json.loads(result.stdout.strip().splitlines()[-1])
    assert probe == {"posts": 404, "health": 404, "real_live": 422, "sp1_routes": [], "model_modules": []}


def test_nothing_under_src_api_imports_the_model_or_ingestion_modules():
    banned = {"sp1.live_ingest", "sp1.model_client", "api.live_posts", "api.live_state"}
    for path in (ROOT / "src/api").rglob("*.py"):
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
            names = []
            if isinstance(node, ast.Import):
                names = [alias.name for alias in node.names]
            elif isinstance(node, ast.ImportFrom) and node.module:
                names = [node.module] + [f"{node.module}.{alias.name}" for alias in node.names]
            assert not banned & set(names), f"{path.relative_to(ROOT)} imports {banned & set(names)}"
    assert not (ROOT / "src/api/live_posts.py").exists() and not (ROOT / "src/api/live_state.py").exists()


def test_web_page_offers_only_the_synthetic_and_real_sources():
    page = (ROOT / "web/index.html").read_text(encoding="utf-8")
    assert '<option value="real_live">' not in page and "SP1-STORE-V2+LIVE" not in page
    # The data-source selector was removed: the page always plans on the real store (no live source).
    assert page.count('<option value="real"') == 0 and page.count('<option value="synthetic"') == 0
