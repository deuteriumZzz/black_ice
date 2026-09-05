import os

import insightface

import black_ice_common.vectorstore as vectorstore


def _sample_image_path() -> str:
    return os.path.join(os.path.dirname(insightface.__file__), "data", "images", "t1.jpg")


def _enroll_and_get_vector(match_client, name: str):
    import black_ice_common.config as config

    img_path = _sample_image_path()
    with open(img_path, "rb") as f:
        r = match_client.post(
            "/enroll",
            data={"name": name, "consent": "true"},
            files={"file": ("t1.jpg", f, "image/jpeg")},
            headers={"X-API-Key": "admin-key"},
        )
    identity_id = r.json()["identity_id"]

    points, _ = vectorstore.client.scroll(
        collection_name=config.settings.collection_name, limit=10, with_vectors=True, with_payload=True
    )
    point = next(p for p in points if p.payload["identity_id"] == identity_id)
    return identity_id, point.vector


def test_stream_consumer_denies_without_a_rule(match_client, monkeypatch):
    import services.match.app.stream_consumer as stream_consumer
    from black_ice_common.schemas import EmbeddingMsg

    identity_id, vector = _enroll_and_get_vector(match_client, "Trinity")

    published = []
    monkeypatch.setattr(stream_consumer.live_feed, "publish_threadsafe", lambda event: published.append(event))

    msg = EmbeddingMsg(frame_id="f1", camera_id="cam-lobby", ts=0.0, track_id=1, bbox=[0, 0, 10, 10], embedding=vector)
    stream_consumer._handle(msg)

    assert published[0]["status"] == "ACCESS DENIED"

    import black_ice_common.db as db_module
    from black_ice_common.db import AuditLog

    with db_module.SessionLocal() as session:
        row = session.query(AuditLog).filter(AuditLog.identity_id == identity_id).one()
    assert row.matched is True
    assert row.access_granted is False


def test_stream_consumer_grants_with_a_matching_rule(match_client, monkeypatch):
    import black_ice_common.db as db_module
    import services.match.app.stream_consumer as stream_consumer
    from black_ice_common.schemas import EmbeddingMsg

    identity_id, vector = _enroll_and_get_vector(match_client, "Morpheus")

    with db_module.SessionLocal() as session:
        session.add(db_module.AccessRule(identity_id=identity_id, camera_id="cam-lobby"))
        session.commit()

    published = []
    monkeypatch.setattr(stream_consumer.live_feed, "publish_threadsafe", lambda event: published.append(event))

    msg = EmbeddingMsg(frame_id="f2", camera_id="cam-lobby", ts=0.0, track_id=2, bbox=[0, 0, 10, 10], embedding=vector)
    stream_consumer._handle(msg)

    assert published[0]["status"] == "ACCESS GRANTED"

    with db_module.SessionLocal() as session:
        row = session.query(db_module.AuditLog).filter(db_module.AuditLog.identity_id == identity_id).one()
    assert row.access_granted is True


def test_stream_consumer_unmatched_face_has_no_access_check(match_client, monkeypatch):
    import black_ice_common.db as db_module
    import services.match.app.stream_consumer as stream_consumer
    from black_ice_common.schemas import EmbeddingMsg

    published = []
    monkeypatch.setattr(stream_consumer.live_feed, "publish_threadsafe", lambda event: published.append(event))

    # a vector with no enrolled identity nearby in the gallery
    msg = EmbeddingMsg(
        frame_id="f3", camera_id="cam-lobby", ts=0.0, track_id=3, bbox=[0, 0, 10, 10], embedding=[0.001] * 512
    )
    stream_consumer._handle(msg)

    assert published[0]["status"] == "IDENTITY UNKNOWN"

    with db_module.SessionLocal() as session:
        row = session.query(db_module.AuditLog).filter(db_module.AuditLog.frame_id == "f3").one()
    assert row.access_granted is None
