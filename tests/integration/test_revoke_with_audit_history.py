"""Regression test for a real bug caught by Phase 1's live verification against
real Postgres: DELETE /identities/{id} raised a ForeignKeyViolation whenever the
identity had any audit_log rows — every prior test passed because sqlite doesn't
enforce foreign keys by default, silently masking it. Fixed by (a) adding
ON DELETE SET NULL to AuditLog.identity_id and (b) enabling FK enforcement on
sqlite test connections too (db.py's engine-connect listener), so this class of
bug can't hide behind sqlite's default leniency again."""
import os

import insightface


def _sample_image_path() -> str:
    return os.path.join(os.path.dirname(insightface.__file__), "data", "images", "t1.jpg")


def test_revoke_succeeds_even_with_prior_audit_history(match_client):
    img_path = _sample_image_path()

    with open(img_path, "rb") as f:
        r = match_client.post(
            "/enroll",
            data={"name": "Neo", "consent": "true"},
            files={"file": ("t1.jpg", f, "image/jpeg")},
            headers={"X-API-Key": "admin-key"},
        )
    identity_id = r.json()["identity_id"]

    # Creates an audit_log row that references identity_id — this is exactly
    # the state that triggered the FK violation against real Postgres.
    with open(img_path, "rb") as f:
        r = match_client.post("/identify", files={"file": ("t1.jpg", f, "image/jpeg")}, headers={"X-API-Key": "op-key"})
    assert r.json()["status"] == "IDENTITY CONFIRMED"

    r = match_client.delete(f"/identities/{identity_id}", headers={"X-API-Key": "admin-key"})
    assert r.status_code == 200, "revoke must succeed even when audit history references the identity"

    r = match_client.get("/audit", headers={"X-API-Key": "admin-key"})
    assert r.status_code == 200
    rows = r.json()
    assert len(rows) == 1
    assert rows[0]["identity_id"] is None, "the audit row must survive with identity_id nulled out, not be deleted or block the revoke"
    assert rows[0]["matched"] is True, "the rest of the audit row is untouched"
