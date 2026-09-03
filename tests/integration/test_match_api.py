import os

import cv2
import insightface


def _sample_image_path() -> str:
    return os.path.join(os.path.dirname(insightface.__file__), "data", "images", "t1.jpg")


def test_full_enroll_identify_revoke_flow(match_client):
    img_path = _sample_image_path()

    r = match_client.get("/health")
    assert r.status_code == 200

    with open(img_path, "rb") as f:
        r = match_client.post("/enroll", data={"name": "Neo", "consent": "true"}, files={"file": ("t1.jpg", f, "image/jpeg")})
    assert r.status_code == 401, "missing API key must be 401, not FastAPI's default 422"

    with open(img_path, "rb") as f:
        r = match_client.post(
            "/enroll",
            data={"name": "Neo", "consent": "true"},
            files={"file": ("t1.jpg", f, "image/jpeg")},
            headers={"X-API-Key": "op-key"},
        )
    assert r.status_code == 403, "operator role must not be able to enroll"

    with open(img_path, "rb") as f:
        r = match_client.post(
            "/enroll",
            data={"name": "Neo", "consent": "false"},
            files={"file": ("t1.jpg", f, "image/jpeg")},
            headers={"X-API-Key": "admin-key"},
        )
    assert r.status_code == 422, "enrollment without consent must be rejected"

    with open(img_path, "rb") as f:
        r = match_client.post(
            "/enroll",
            data={"name": "Neo", "consent": "true"},
            files={"file": ("t1.jpg", f, "image/jpeg")},
            headers={"X-API-Key": "admin-key"},
        )
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "IDENTITY ENROLLED"
    identity_id = body["identity_id"]

    with open(img_path, "rb") as f:
        r = match_client.post("/identify", files={"file": ("t1.jpg", f, "image/jpeg")}, headers={"X-API-Key": "op-key"})
    assert r.status_code == 200
    assert r.json()["status"] == "IDENTITY CONFIRMED"
    assert r.json()["identity_id"] == identity_id

    assert match_client.get("/audit", headers={"X-API-Key": "op-key"}).status_code == 403
    r = match_client.get("/audit", headers={"X-API-Key": "admin-key"})
    assert r.status_code == 200
    assert len(r.json()) >= 1

    r = match_client.delete(f"/identities/{identity_id}", headers={"X-API-Key": "admin-key"})
    assert r.status_code == 200

    with open(img_path, "rb") as f:
        r = match_client.post("/identify", files={"file": ("t1.jpg", f, "image/jpeg")}, headers={"X-API-Key": "op-key"})
    assert r.json()["status"] == "IDENTITY UNKNOWN", "identify must not match a revoked identity"


def test_metrics_endpoint_served(match_client):
    r = match_client.get("/metrics")
    assert r.status_code == 200


def test_multi_embedding_enrollment_adds_to_existing_identity(match_client):
    """spec: cluster of embeddings per identity, not one photo. A second /enroll
    call with the same identity_id should add a sample, not create a new identity."""
    img_path = _sample_image_path()

    with open(img_path, "rb") as f:
        r = match_client.post(
            "/enroll",
            data={"name": "Trinity", "consent": "true"},
            files={"file": ("t1.jpg", f, "image/jpeg")},
            headers={"X-API-Key": "admin-key"},
        )
    assert r.status_code == 200
    identity_id = r.json()["identity_id"]

    with open(img_path, "rb") as f:
        r = match_client.post(
            "/enroll",
            data={"name": "Trinity", "consent": "true", "identity_id": identity_id},
            files={"file": ("t1.jpg", f, "image/jpeg")},
            headers={"X-API-Key": "admin-key"},
        )
    assert r.status_code == 200
    assert r.json()["identity_id"] == identity_id, "second sample should attach to the same identity, not create a new one"

    with open(img_path, "rb") as f:
        r = match_client.post(
            "/enroll",
            data={"name": "x", "consent": "true", "identity_id": "00000000-0000-0000-0000-000000000000"},
            files={"file": ("t1.jpg", f, "image/jpeg")},
            headers={"X-API-Key": "admin-key"},
        )
    assert r.status_code == 404, "a bogus identity_id must not silently create a new identity"


def test_liveness_check_off_by_default_on_by_flag(match_client, monkeypatch, tmp_path):
    """The heuristic in libs/black_ice_common/liveness.py is disabled by default —
    confirm identify ignores it normally, and actually rejects a blurred image
    once the operator opts in via config."""
    import black_ice_common.config as config

    img_path = _sample_image_path()
    blurred_path = str(tmp_path / "blurred.jpg")
    cv2.imwrite(blurred_path, cv2.GaussianBlur(cv2.imread(img_path), (51, 51), 0))

    with open(blurred_path, "rb") as f:
        r = match_client.post("/identify", files={"file": ("blurred.jpg", f, "image/jpeg")}, headers={"X-API-Key": "op-key"})
    assert r.json()["status"] != "LIVENESS CHECK FAILED", "liveness check must be off by default"

    monkeypatch.setattr(config.settings, "liveness_check_enabled", True)
    with open(blurred_path, "rb") as f:
        r = match_client.post("/identify", files={"file": ("blurred.jpg", f, "image/jpeg")}, headers={"X-API-Key": "op-key"})
    assert r.json()["status"] == "LIVENESS CHECK FAILED"
