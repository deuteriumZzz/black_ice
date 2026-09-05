def _enroll_identity(match_client, name="Neo") -> str:
    import os

    import insightface

    img_path = os.path.join(os.path.dirname(insightface.__file__), "data", "images", "t1.jpg")
    with open(img_path, "rb") as f:
        r = match_client.post(
            "/enroll",
            data={"name": name, "consent": "true"},
            files={"file": ("t1.jpg", f, "image/jpeg")},
            headers={"X-API-Key": "admin-key"},
        )
    return r.json()["identity_id"]


def test_access_rule_crud_and_rbac(match_client):
    identity_id = _enroll_identity(match_client)

    r = match_client.get("/access-rules", headers={"X-API-Key": "op-key"})
    assert r.status_code == 403

    r = match_client.post(
        "/access-rules",
        json={"identity_id": identity_id, "camera_id": "cam-lobby"},
        headers={"X-API-Key": "admin-key"},
    )
    assert r.status_code == 200
    body = r.json()
    assert body["identity_id"] == identity_id
    assert body["enabled"] is True
    rule_id = body["id"]

    r = match_client.post(
        "/access-rules",
        json={"identity_id": "does-not-exist", "camera_id": "cam-lobby"},
        headers={"X-API-Key": "admin-key"},
    )
    assert r.status_code == 404

    r = match_client.get(f"/access-rules?identity_id={identity_id}", headers={"X-API-Key": "admin-key"})
    assert len(r.json()) == 1

    r = match_client.patch(f"/access-rules/{rule_id}", json={"enabled": False}, headers={"X-API-Key": "admin-key"})
    assert r.status_code == 200
    assert r.json()["enabled"] is False
    assert r.json()["camera_id"] == "cam-lobby", "fields not included in the PATCH body must be untouched"

    r = match_client.delete(f"/access-rules/{rule_id}", headers={"X-API-Key": "admin-key"})
    assert r.status_code == 200
    assert match_client.get("/access-rules", headers={"X-API-Key": "admin-key"}).json() == []
