import os

import insightface

import black_ice_common.vectorstore as vectorstore


def _sample_image_path() -> str:
    return os.path.join(os.path.dirname(insightface.__file__), "data", "images", "t1.jpg")


def test_enroll_writes_to_both_primary_and_shadow_galleries(match_client, monkeypatch):
    import black_ice_common.config as config
    import services.match.app.face as face_module

    monkeypatch.setattr(config.settings, "shadow_embedding_enabled", True)
    monkeypatch.setattr(face_module, "_shadow_embedder", None)  # force reload under the new setting

    img_path = _sample_image_path()
    with open(img_path, "rb") as f:
        r = match_client.post(
            "/enroll",
            data={"name": "Neo", "consent": "true"},
            files={"file": ("t1.jpg", f, "image/jpeg")},
            headers={"X-API-Key": "admin-key"},
        )
    assert r.status_code == 200

    primary_count = vectorstore.client.count(collection_name=config.settings.collection_name).count
    shadow_count = vectorstore.client.count(collection_name=config.settings.shadow_collection_name).count
    assert primary_count == 1
    assert shadow_count == 1, "shadow-mode enroll should also write into the shadow gallery"


def test_shadow_consumer_logs_decision_without_touching_primary_flow(match_client, monkeypatch):
    import black_ice_common.config as config
    import black_ice_common.db as db_module
    import services.match.app.face as face_module
    import services.match.app.shadow_consumer as shadow_consumer
    from black_ice_common.db import AuditLog
    from black_ice_common.schemas import EmbeddingMsg

    monkeypatch.setattr(config.settings, "shadow_embedding_enabled", True)
    monkeypatch.setattr(face_module, "_shadow_embedder", None)

    img_path = _sample_image_path()
    with open(img_path, "rb") as f:
        r = match_client.post(
            "/enroll",
            data={"name": "Trinity", "consent": "true"},
            files={"file": ("t1.jpg", f, "image/jpeg")},
            headers={"X-API-Key": "admin-key"},
        )
    identity_id = r.json()["identity_id"]

    # pull the exact vector just written to the shadow gallery so the shadow
    # consumer's search is a guaranteed exact match, not dependent on similarity math
    points, _ = vectorstore.client.scroll(
        collection_name=config.settings.shadow_collection_name, limit=10, with_vectors=True, with_payload=True
    )
    shadow_point = next(p for p in points if p.payload["identity_id"] == identity_id)

    msg = EmbeddingMsg(
        frame_id="frame-1", camera_id="cam-test", ts=0.0, track_id=7, bbox=[0, 0, 10, 10], embedding=shadow_point.vector
    )
    shadow_consumer._handle(msg)

    with db_module.SessionLocal() as session:
        shadow_rows = session.query(AuditLog).filter(AuditLog.model_version == config.settings.shadow_embedding_pack).all()
        primary_rows = session.query(AuditLog).filter(AuditLog.model_version == "primary").all()

    assert len(shadow_rows) == 1
    assert shadow_rows[0].matched is True
    assert shadow_rows[0].identity_id == identity_id
    assert shadow_rows[0].frame_id == "frame-1"
    assert shadow_rows[0].track_id == 7
    assert shadow_rows[0].camera_id == "cam-test"
    assert len(primary_rows) == 0, "a shadow decision must never be logged as a primary one"
