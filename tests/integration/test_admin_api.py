import os

import insightface


def _sample_image_path() -> str:
    return os.path.join(os.path.dirname(insightface.__file__), "data", "images", "t1.jpg")


def test_login_returns_role_and_label(match_client):
    r = match_client.post("/auth/login", headers={"X-API-Key": "admin-key"})
    assert r.status_code == 200
    assert r.json()["role"] == "admin"
    assert r.json()["label"] == "seeded-from-env"


def test_login_rejects_unknown_key(match_client):
    r = match_client.post("/auth/login", headers={"X-API-Key": "not-a-real-key"})
    assert r.status_code == 401


def test_login_rejects_missing_key(match_client):
    r = match_client.post("/auth/login")
    assert r.status_code == 422  # Header(...) required, FastAPI's own validation


def test_list_identities_requires_enroll_permission(match_client):
    assert match_client.get("/identities", headers={"X-API-Key": "op-key"}).status_code == 403
    r = match_client.get("/identities", headers={"X-API-Key": "admin-key"})
    assert r.status_code == 200
    assert r.json() == []


def test_list_identities_returns_enrolled_identities(match_client):
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

    r = match_client.get("/identities", headers={"X-API-Key": "admin-key"})
    assert r.status_code == 200
    ids = [row["id"] for row in r.json()]
    assert identity_id in ids
    row = next(row for row in r.json() if row["id"] == identity_id)
    assert row["name"] == "Trinity"
    assert row["consent_given"] is True


def test_audit_filters_by_camera_and_time_range(match_client):
    import datetime

    import black_ice_common.db as db_module

    with db_module.SessionLocal() as session:
        session.add(db_module.AuditLog(matched=True, score=0.9, camera_id="cam-a"))
        session.add(db_module.AuditLog(matched=True, score=0.8, camera_id="cam-b"))
        session.commit()

    r = match_client.get("/audit", params={"camera_id": "cam-a"}, headers={"X-API-Key": "admin-key"})
    assert r.status_code == 200
    rows = r.json()
    assert len(rows) == 1
    assert rows[0]["camera_id"] == "cam-a"

    future = (datetime.datetime.utcnow() + datetime.timedelta(days=1)).isoformat()
    r = match_client.get("/audit", params={"from_ts": future}, headers={"X-API-Key": "admin-key"})
    assert r.json() == [], "a from_ts in the future should exclude everything"


def test_audit_pagination_offset(match_client):
    import black_ice_common.db as db_module

    with db_module.SessionLocal() as session:
        for i in range(5):
            session.add(db_module.AuditLog(matched=True, score=0.5 + i * 0.01))
        session.commit()

    page1 = match_client.get("/audit", params={"limit": 2, "offset": 0}, headers={"X-API-Key": "admin-key"}).json()
    page2 = match_client.get("/audit", params={"limit": 2, "offset": 2}, headers={"X-API-Key": "admin-key"}).json()
    assert len(page1) == 2
    assert len(page2) == 2
    assert page1 != page2
