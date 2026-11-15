"""Admin endpoints for incremental SP1 ingestion (post 190 onwards). See docs/sp1_live_ingestion.md."""

from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, HTTPException
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from api import live_state
from sp1.live_ingest import IngestError
from sp1.model_client import SP1ModelClient, SP1ModelConfig, SP1ModelError

router = APIRouter(prefix="/api/sp1", tags=["sp1-live-ingestion"])


class SubmitPostRequest(BaseModel):
    raw_content: str = Field(description="Free-form announcement text")
    url: Optional[str] = None
    publisher: Optional[str] = None
    platform: Optional[str] = None
    date_posted: Optional[str] = None
    post_id: Optional[str] = Field(default=None, description="Give it to edit an existing post (new revision)")
    process: bool = Field(default=True, description="false = save the draft only")


class PublishRequest(BaseModel):
    reviewer: str


def _call(function, *args, **kwargs):
    try:
        return function(*args, **kwargs)
    except IngestError as exc:
        raise HTTPException(status_code=exc.http_status, detail={"code": exc.code, "message": exc.message}) from exc


@router.post("/posts")
def submit_post(req: SubmitPostRequest):
    """Save one announcement (always first), then process it unless process=false. Same text + metadata
    resubmitted returns the existing revision; changed text creates the next revision."""
    return _call(live_state.get_service().submit, req.raw_content, url=req.url, publisher=req.publisher,
                 platform=req.platform, date_posted=req.date_posted, post_id=req.post_id, process=req.process)


@router.get("/posts")
def list_posts():
    return {"posts": live_state.get_service().list()}


@router.get("/posts/{post_id}")
def get_post(post_id: str):
    return _call(live_state.get_service().get, post_id)


@router.post("/posts/{post_id}/revisions/{revision}/process")
def process_revision(post_id: str, revision: int):
    """Run extraction for a saved or failed revision (retry). The saved text is reused."""
    return _call(live_state.get_service().retry, post_id, revision)


@router.post("/posts/{post_id}/revisions/{revision}/publish")
def publish_revision(post_id: str, revision: int, req: PublishRequest):
    """Explicit admin action: the reviewed latest revision becomes the operational one. Idempotent."""
    return _call(live_state.get_service().publish, post_id, revision, req.reviewer)


@router.get("/model/health")
def model_health():
    """Which model the SP1 service really serves, and whether the configured one is among them."""
    try:
        return SP1ModelClient(SP1ModelConfig.from_env()).health()
    except SP1ModelError as exc:
        return JSONResponse(status_code=200, content={"available": False, "code": exc.code, "message": exc.message})
