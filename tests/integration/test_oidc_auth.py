"""Exercises rbac.py's auth_backend="oidc" switch through the real API
surface (Depends(require(...)) and /auth/login) — oidc.py's own token
validation correctness (signature/issuer/expiry/role-extraction) is unit-
tested in tests/unit/test_oidc.py against a real RSA-signed JWT; this layer
only needs to confirm main.py wires the Authorization header through
correctly and that role -> permission checks still apply.
"""
import black_ice_common.oidc as oidc


def test_login_with_bearer_token_returns_role(match_client, monkeypatch):
    import black_ice_common.config as config

    monkeypatch.setattr(config.settings, "auth_backend", "oidc")
    monkeypatch.setattr(oidc, "validate_token", lambda token: ("alice", "admin"))

    r = match_client.post("/auth/login", headers={"Authorization": "Bearer whatever"})

    assert r.status_code == 200
    assert r.json() == {"role": "admin", "label": "alice"}


def test_protected_endpoint_honors_oidc_role(match_client, monkeypatch):
    import black_ice_common.config as config

    monkeypatch.setattr(config.settings, "auth_backend", "oidc")
    monkeypatch.setattr(oidc, "validate_token", lambda token: ("bob", "operator"))

    r = match_client.get("/identities", headers={"Authorization": "Bearer whatever"})
    assert r.status_code == 403  # operator lacks the "enroll" permission /identities requires

    monkeypatch.setattr(oidc, "validate_token", lambda token: ("carol", "admin"))
    r = match_client.get("/identities", headers={"Authorization": "Bearer whatever"})
    assert r.status_code == 200


def test_oidc_mode_rejects_missing_bearer_token(match_client, monkeypatch):
    import black_ice_common.config as config

    monkeypatch.setattr(config.settings, "auth_backend", "oidc")

    r = match_client.get("/identities")
    assert r.status_code == 401

    # An X-API-Key header must not work as a fallback once oidc mode is on —
    # otherwise "switch to oidc" wouldn't actually retire the old credential.
    r = match_client.get("/identities", headers={"X-API-Key": "admin-key"})
    assert r.status_code == 401


def test_oidc_mode_rejects_invalid_token(match_client, monkeypatch):
    import black_ice_common.config as config

    monkeypatch.setattr(config.settings, "auth_backend", "oidc")

    def _raise(token):
        raise ValueError("token has no recognized realm role")

    monkeypatch.setattr(oidc, "validate_token", _raise)

    r = match_client.get("/identities", headers={"Authorization": "Bearer garbage"})
    assert r.status_code == 401
