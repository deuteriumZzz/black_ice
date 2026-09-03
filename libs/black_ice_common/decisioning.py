"""Shared core of "search this embedding, decide match/unknown, log it" — used by
both the primary stream consumer and the shadow-mode consumer (services/match/app/
{stream_consumer,shadow_consumer}.py), each wrapping it in their own CircuitBreaker
so a broken shadow model can never trip the breaker guarding real access decisions.

References `black_ice_common.db`/`vectorstore` as modules and calls through them
dynamically (`db.SessionLocal()`, `vectorstore.search_face(...)`) rather than
importing `SessionLocal`/`search_face` by name — tests patch `db.SessionLocal` and
`vectorstore.client` directly, and a name-import would bind to the pre-patch
object at import time instead of picking up the patch.
"""
import black_ice_common.db as db
import black_ice_common.vectorstore as vectorstore
from black_ice_common.config import settings
from black_ice_common.decision import is_match


def evaluate_embedding(
    embedding,
    camera_id: str,
    frame_id: str | None = None,
    track_id: int | None = None,
    model_version: str = "primary",
    collection: str | None = None,
    threshold: float | None = None,
    requested_by: str = "stream",
) -> dict:
    threshold = settings.match_threshold if threshold is None else threshold
    hits = vectorstore.search_face(embedding, limit=1, collection=collection)
    score = float(hits[0].score) if hits else -1.0
    matched = bool(hits) and is_match(score, threshold)
    identity_id = hits[0].payload["identity_id"] if matched else None
    name = hits[0].payload["name"] if matched else None

    with db.SessionLocal() as session:
        session.add(
            db.AuditLog(
                identity_id=identity_id,
                matched=matched,
                score=score,
                requested_by=requested_by,
                camera_id=camera_id,
                frame_id=frame_id,
                track_id=track_id,
                model_version=model_version,
            )
        )
        session.commit()

    return {"matched": matched, "score": score, "identity_id": identity_id, "name": name}
