"""Liveness and readiness (section 4.3). They answer different questions."""

from __future__ import annotations

import logging

from fastapi import APIRouter, Request, Response

router = APIRouter()
log = logging.getLogger("rahbar.ready")


@router.get("/healthz")
def healthz() -> dict[str, str]:
    """Is the process alive? Must never touch Chroma, Redis or the LLM."""
    return {"status": "alive"}


@router.get("/readyz")
def readyz(request: Request, response: Response) -> dict[str, object]:
    """Ready only if Chroma answers, the collection is non-empty, the embedding pin
    matches, and Redis answers. Otherwise 503 naming what failed (sections 4.3, 4.4)."""
    s = request.app.state.settings
    if s.retriever != "chroma":
        return {"status": "ready", "checks": {"mode": "stub"}}

    def fail(dep: str, why: str) -> dict[str, object]:
        response.status_code = 503
        log.error("not ready", extra={"failed": dep, "reason": why})
        return {"status": "not ready", "failed": dep, "reason": why}

    try:
        col = request.app.state.retriever.client.get_collection(s.collection)
        count = col.count()
    except Exception as exc:
        return fail("chroma", f"collection unavailable: {exc}")
    if count == 0:
        return fail("chroma", "collection is empty")
    pinned = (col.metadata or {}).get("embed_model")
    if pinned != s.embed_model:
        return fail(
            "embedding-pin",
            f"index was built with {pinned!r} but this API has EMBED_MODEL={s.embed_model!r}",
        )
    try:
        request.app.state.cache.ping()
    except Exception as exc:
        return fail("redis", str(exc))
    return {"status": "ready", "checks": {"chroma": count, "embed_model": pinned, "redis": "ok"}}
