"""Wires template_protection.py's math (already unit-tested in
tests/unit/test_template_protection.py) through the real enroll/identify API
path against a real (in-memory) Qdrant — proving the transform is actually
applied on the write and read paths, not just correct in isolation."""
import os

import insightface


def _sample_image_path() -> str:
    return os.path.join(os.path.dirname(insightface.__file__), "data", "images", "t1.jpg")


def test_identify_matches_with_template_protection_enabled(match_client, monkeypatch):
    import black_ice_common.config as config
    import black_ice_common.template_protection as tp

    monkeypatch.setattr(config.settings, "template_protection_enabled", True)
    monkeypatch.setattr(config.settings, "template_protection_seed", "integration-test-seed")
    monkeypatch.setattr(tp, "_matrix", None)
    monkeypatch.setattr(tp, "_matrix_seed", None)

    img_path = _sample_image_path()
    with open(img_path, "rb") as f:
        r = match_client.post(
            "/enroll", data={"name": "Neo", "consent": "true"}, files={"file": ("t1.jpg", f, "image/jpeg")},
            headers={"X-API-Key": "admin-key"},
        )
    assert r.status_code == 200
    identity_id = r.json()["identity_id"]

    with open(img_path, "rb") as f:
        r = match_client.post("/identify", files={"file": ("t1.jpg", f, "image/jpeg")}, headers={"X-API-Key": "op-key"})
    assert r.status_code == 200
    assert r.json()["status"] == "IDENTITY CONFIRMED"
    assert r.json()["identity_id"] == identity_id


def test_rotating_the_seed_invalidates_old_templates(match_client, monkeypatch):
    """The "cancelable" property end to end: an identity enrolled under one
    seed must stop matching once the seed rotates — proving a leaked seed can
    actually be revoked by rotation + re-enroll, not just in the abstract."""
    import black_ice_common.config as config
    import black_ice_common.template_protection as tp

    monkeypatch.setattr(config.settings, "template_protection_enabled", True)
    monkeypatch.setattr(config.settings, "template_protection_seed", "seed-before-leak")
    monkeypatch.setattr(tp, "_matrix", None)
    monkeypatch.setattr(tp, "_matrix_seed", None)

    img_path = _sample_image_path()
    with open(img_path, "rb") as f:
        match_client.post(
            "/enroll", data={"name": "Neo", "consent": "true"}, files={"file": ("t1.jpg", f, "image/jpeg")},
            headers={"X-API-Key": "admin-key"},
        )

    monkeypatch.setattr(config.settings, "template_protection_seed", "seed-after-rotation")
    tp._matrix, tp._matrix_seed = None, None

    with open(img_path, "rb") as f:
        r = match_client.post("/identify", files={"file": ("t1.jpg", f, "image/jpeg")}, headers={"X-API-Key": "op-key"})
    assert r.status_code == 200
    assert r.json()["status"] == "IDENTITY UNKNOWN", "a rotated seed must not still match the old template"
