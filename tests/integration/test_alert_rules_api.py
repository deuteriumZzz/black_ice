def test_alert_rule_crud_and_rbac(match_client):
    r = match_client.get("/alert-rules", headers={"X-API-Key": "op-key"})
    assert r.status_code == 403

    r = match_client.post(
        "/alert-rules",
        json={"event_type": "access_denied", "camera_id": "cam-lobby", "webhook_url": "http://hook.test/a"},
        headers={"X-API-Key": "admin-key"},
    )
    assert r.status_code == 200
    body = r.json()
    assert body["event_type"] == "access_denied"
    assert body["enabled"] is True
    rule_id = body["id"]

    r = match_client.post(
        "/alert-rules",
        json={"event_type": "not_a_real_event", "webhook_url": "http://hook.test/b"},
        headers={"X-API-Key": "admin-key"},
    )
    assert r.status_code == 400

    r = match_client.get("/alert-rules", headers={"X-API-Key": "admin-key"})
    assert len(r.json()) == 1

    r = match_client.patch(f"/alert-rules/{rule_id}", json={"enabled": False}, headers={"X-API-Key": "admin-key"})
    assert r.status_code == 200
    assert r.json()["enabled"] is False
    assert r.json()["webhook_url"] == "http://hook.test/a", "fields not included in the PATCH body must be untouched"

    r = match_client.delete(f"/alert-rules/{rule_id}", headers={"X-API-Key": "admin-key"})
    assert r.status_code == 200
    assert match_client.get("/alert-rules", headers={"X-API-Key": "admin-key"}).json() == []
