import asyncio
import datetime
import uuid

import cv2
import numpy as np
from fastapi import Depends, FastAPI, File, Form, HTTPException, UploadFile, WebSocket, WebSocketDisconnect
from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor
from prometheus_client import make_asgi_app
from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded
from slowapi.util import get_remote_address
from starlette.requests import Request

from black_ice_common.config import settings
from black_ice_common.db import AuditLog, Identity, SessionLocal, init_db
from black_ice_common.decision import is_match
from black_ice_common.liveness import assess_liveness
from black_ice_common.rbac import require
from black_ice_common.tracing import init_tracing
from black_ice_common.vectorstore import delete_identity_vectors, ensure_collection, search_face, upsert_face
from services.match.app.face import largest_face, liveness_engine, shadow_embedder
from services.match.app.stream_consumer import start_background_consumer
from services.match.app.shadow_consumer import start_background_consumer as start_shadow_consumer
from services.match.app.ws import live_feed

limiter = Limiter(key_func=get_remote_address)
app = FastAPI(title="BLACK ICE — match")
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)
app.mount("/metrics", make_asgi_app())
init_tracing("black-ice-match")
FastAPIInstrumentor.instrument_app(app)


@app.on_event("startup")
def startup() -> None:
    init_db()
    ensure_collection()
    if settings.shadow_embedding_enabled:
        ensure_collection(settings.shadow_collection_name)
    live_feed.bind_loop(asyncio.get_event_loop())
    start_background_consumer()
    start_shadow_consumer()


def _read_image(file: UploadFile) -> np.ndarray:
    data = np.frombuffer(file.file.read(), dtype=np.uint8)
    image = cv2.imdecode(data, cv2.IMREAD_COLOR)
    if image is None:
        raise HTTPException(400, "unreadable image")
    return image


def _hex_bbox(bbox) -> str:
    return " ".join(f"0x{int(v):04X}" for v in bbox)


@app.get("/health")
def health():
    return {"status": "BLACK ICE ACTIVE"}


@app.post("/enroll")
@limiter.limit(settings.rate_limit)
def enroll(
    request: Request,
    name: str = Form(...),
    consent: bool = Form(...),
    file: UploadFile = File(...),
    identity_id: str | None = Form(default=None),
    _role: str = Depends(require("enroll")),
):
    """`identity_id` is optional: pass an existing identity's id to add another
    embedding sample to it (spec: "multi-embedding per identity" — a cluster of
    photos per person beats a single one) instead of enrolling a new identity."""
    if not consent:
        raise HTTPException(422, "CONSENT REQUIRED // cannot enroll without explicit consent")

    image = _read_image(file)
    found = largest_face(image)
    if found is None:
        raise HTTPException(422, "NO TARGET ACQUIRED // no face detected")
    bbox, kps, det_score, embedding = found

    with SessionLocal() as session:
        if identity_id:
            identity = session.get(Identity, identity_id)
            if identity is None:
                raise HTTPException(404, "identity not found")
        else:
            identity = Identity(
                name=name,
                consent_given=True,
                retention_expires_at=datetime.datetime.utcnow() + datetime.timedelta(days=settings.retention_days),
            )
            session.add(identity)
            session.commit()
            session.refresh(identity)

    upsert_face(str(uuid.uuid4()), embedding, identity.id, name)

    shadow_engine = shadow_embedder()
    if shadow_engine is not None:
        # Same image/landmarks, candidate model's own embedding space+gallery —
        # keeps the shadow gallery in sync with every real enrollment. Ensured
        # here too (not just at startup) so flipping the flag without a restart
        # still works — ensure_collection() is a cheap no-op once it exists.
        ensure_collection(settings.shadow_collection_name)
        shadow_vector = shadow_engine.embed(image, kps)
        upsert_face(str(uuid.uuid4()), shadow_vector, identity.id, name, collection=settings.shadow_collection_name)

    return {
        "status": "IDENTITY ENROLLED",
        "identity_id": identity.id,
        "name": name,
        "bbox": _hex_bbox(bbox),
        "det_score": round(det_score, 4),
        "retention_expires_at": identity.retention_expires_at.isoformat(),
    }


@app.post("/identify")
@limiter.limit(settings.rate_limit)
def identify(request: Request, file: UploadFile = File(...), role: str = Depends(require("identify"))):
    image = _read_image(file)
    found = largest_face(image)
    if found is None:
        return {"status": "NO TARGET ACQUIRED"}
    bbox, kps, det_score, embedding = found

    if settings.liveness_check_enabled:
        x1, y1, x2, y2 = (int(v) for v in bbox)
        crop = image[max(0, y1):y2, max(0, x1):x2]
        liveness = None if crop.size == 0 else assess_liveness(
            crop,
            onnx_engine=liveness_engine(),
            onnx_threshold=settings.liveness_onnx_threshold,
            min_sharpness=settings.liveness_min_sharpness,
            min_chroma_std=settings.liveness_min_chroma_std,
        )
        if liveness is None or not liveness.is_live:
            return {"status": "LIVENESS CHECK FAILED", "bbox": _hex_bbox(bbox), "liveness_method": liveness.method if liveness else "n/a"}

    hits = search_face(embedding, limit=1)
    score = float(hits[0].score) if hits else -1.0
    matched = bool(hits) and is_match(score, settings.match_threshold)
    identity_id = hits[0].payload["identity_id"] if matched else None

    with SessionLocal() as session:
        session.add(AuditLog(identity_id=identity_id, matched=matched, score=score, requested_by=role))
        session.commit()

    if matched:
        return {
            "status": "IDENTITY CONFIRMED",
            "match": f"{score * 100:.1f}%",
            "identity_id": identity_id,
            "name": hits[0].payload["name"],
            "bbox": _hex_bbox(bbox),
        }
    return {"status": "IDENTITY UNKNOWN", "match": f"{max(score, 0) * 100:.1f}%", "bbox": _hex_bbox(bbox)}


@app.get("/audit")
def audit(limit: int = 50, _role: str = Depends(require("audit"))):
    with SessionLocal() as session:
        rows = session.query(AuditLog).order_by(AuditLog.ts.desc()).limit(min(limit, 500)).all()
        return [
            {
                "ts": r.ts.isoformat(),
                "identity_id": r.identity_id,
                "matched": r.matched,
                "score": r.score,
                "requested_by": r.requested_by,
                "camera_id": r.camera_id,
            }
            for r in rows
        ]


@app.delete("/identities/{identity_id}")
def revoke_identity(identity_id: str, _role: str = Depends(require("enroll"))):
    """Consent revocation / right to erasure: removes the identity row and every
    embedding enrolled under it. Audit log rows are untouched — they only carry an
    identity_id foreign key, not biometric data, and stay meaningful for compliance
    review after the identity itself is gone."""
    with SessionLocal() as session:
        identity = session.get(Identity, identity_id)
        if identity is None:
            raise HTTPException(404, "identity not found")
        session.delete(identity)
        session.commit()
    delete_identity_vectors(identity_id)
    return {"status": "IDENTITY REVOKED", "identity_id": identity_id}


@app.websocket("/ws/live")
async def ws_live(ws: WebSocket):
    await live_feed.connect(ws)
    try:
        while True:
            await ws.receive_text()  # client doesn't send anything meaningful; just keeps the socket open
    except WebSocketDisconnect:
        live_feed.disconnect(ws)
