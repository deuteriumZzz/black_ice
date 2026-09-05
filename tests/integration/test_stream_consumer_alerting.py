import os
import time

import insightface
import responses

import black_ice_common.vectorstore as vectorstore


def _sample_image_path() -> str:
    return os.path.join(os.path.dirname(insightface.__file__), "data", "images", "t1.jpg")


def _wait_for(predicate, timeout=2.0):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return True
        time.sleep(0.02)
    return False


@responses.activate
def test_access_denied_fires_configured_webhook(match_client, monkeypatch):
    import black_ice_common.config as config
    import black_ice_common.db as db_module
    import services.match.app.stream_consumer as stream_consumer
    from black_ice_common.schemas import EmbeddingMsg

    img_path = _sample_image_path()
    with open(img_path, "rb") as f:
        r = match_client.post(
            "/enroll",
            data={"name": "Trinity", "consent": "true"},
            files={"file": ("t1.jpg", f, "image/jpeg")},
            headers={"X-API-Key": "admin-key"},
        )
    identity_id = r.json()["identity_id"]

    match_client.post(
        "/alert-rules",
        json={"event_type": "access_denied", "camera_id": "cam-lobby", "webhook_url": "http://hook.test/denied"},
        headers={"X-API-Key": "admin-key"},
    )
    responses.post("http://hook.test/denied", json={"ok": True}, status=200)

    monkeypatch.setattr(stream_consumer.live_feed, "publish_threadsafe", lambda event: None)

    points, _ = vectorstore.client.scroll(
        collection_name=config.settings.collection_name, limit=10, with_vectors=True, with_payload=True
    )
    point = next(p for p in points if p.payload["identity_id"] == identity_id)

    msg = EmbeddingMsg(frame_id="f1", camera_id="cam-lobby", ts=0.0, track_id=1, bbox=[0, 0, 10, 10], embedding=point.vector)
    stream_consumer._handle(msg)

    assert _wait_for(lambda: len(responses.calls) == 1)

    with db_module.SessionLocal() as session:
        row = session.query(db_module.AuditLog).filter(db_module.AuditLog.identity_id == identity_id).one()
    assert row.access_granted is False
