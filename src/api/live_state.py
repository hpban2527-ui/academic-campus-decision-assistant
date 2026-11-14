"""Process-wide handle on the live-ingestion service (created lazily from the environment).

Tests and deployments can replace it with set_service(); the planner reads published posts through it.
"""

from __future__ import annotations

from sp1.live_ingest import LiveIngestService, service_from_env

_service: LiveIngestService | None = None


def get_service() -> LiveIngestService:
    global _service
    if _service is None:
        _service = service_from_env()
    return _service


def set_service(service: LiveIngestService | None) -> None:
    global _service
    _service = service


def published_records() -> list[dict]:
    """Published live posts (empty when the live store has not been created yet)."""
    from sp1.live_ingest import DEFAULT_DB
    import os
    from pathlib import Path

    if _service is None and not Path(os.environ.get("UNILIFE_LIVE_DB") or DEFAULT_DB).exists():
        return []
    return get_service().store.published()
