def test_camera_crud_and_rbac(match_client):
    # operator lacks the "cameras" permission
    r = match_client.get("/cameras", headers={"X-API-Key": "op-key"})
    assert r.status_code == 403

    r = match_client.post(
        "/cameras",
        json={"camera_id": "cam-lobby", "name": "Lobby", "source": "rtsp://lobby", "site": "HQ", "ingest_fps": 10},
        headers={"X-API-Key": "admin-key"},
    )
    assert r.status_code == 200
    body = r.json()
    assert body["camera_id"] == "cam-lobby"
    assert body["enabled"] is True
    assert body["last_seen_at"] is None
    camera_row_id = body["id"]

    # duplicate camera_id is rejected
    r = match_client.post(
        "/cameras",
        json={"camera_id": "cam-lobby", "name": "Lobby 2", "source": "rtsp://lobby2"},
        headers={"X-API-Key": "admin-key"},
    )
    assert r.status_code == 409

    r = match_client.get("/cameras", headers={"X-API-Key": "admin-key"})
    assert r.status_code == 200
    assert len(r.json()) == 1

    r = match_client.patch(
        f"/cameras/{camera_row_id}", json={"enabled": False}, headers={"X-API-Key": "admin-key"}
    )
    assert r.status_code == 200
    assert r.json()["enabled"] is False
    assert r.json()["name"] == "Lobby", "fields not included in the PATCH body must be untouched"

    r = match_client.delete(f"/cameras/{camera_row_id}", headers={"X-API-Key": "admin-key"})
    assert r.status_code == 200
    assert match_client.get("/cameras", headers={"X-API-Key": "admin-key"}).json() == []


def test_camera_config_endpoint_is_unauthenticated_but_scoped(match_client):
    match_client.post(
        "/cameras",
        json={"camera_id": "cam-0", "name": "Front door", "source": "rtsp://front", "ingest_fps": 7.5},
        headers={"X-API-Key": "admin-key"},
    )

    # no X-API-Key at all — this is the point, ingest has none
    r = match_client.get("/cameras/cam-0/config")
    assert r.status_code == 200
    assert r.json() == {"source": "rtsp://front", "ingest_fps": 7.5}
    assert "name" not in r.json(), "config endpoint must not leak fields beyond capture config"

    r = match_client.get("/cameras/does-not-exist/config")
    assert r.status_code == 404


def test_disabled_camera_config_is_rejected(match_client):
    r = match_client.post(
        "/cameras",
        json={"camera_id": "cam-1", "name": "Back door", "source": "rtsp://back"},
        headers={"X-API-Key": "admin-key"},
    )
    camera_row_id = r.json()["id"]
    match_client.patch(f"/cameras/{camera_row_id}", json={"enabled": False}, headers={"X-API-Key": "admin-key"})

    r = match_client.get("/cameras/cam-1/config")
    assert r.status_code == 403


def test_heartbeat_updates_last_seen(match_client):
    match_client.post(
        "/cameras", json={"camera_id": "cam-2", "name": "Side", "source": "0"}, headers={"X-API-Key": "admin-key"}
    )

    r = match_client.post("/cameras/cam-2/heartbeat")
    assert r.status_code == 200

    r = match_client.get("/cameras", headers={"X-API-Key": "admin-key"})
    row = next(c for c in r.json() if c["camera_id"] == "cam-2")
    assert row["last_seen_at"] is not None

    r = match_client.post("/cameras/does-not-exist/heartbeat")
    assert r.status_code == 404
