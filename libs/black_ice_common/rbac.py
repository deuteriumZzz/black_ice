"""API-key -> role, backed by the ApiKey table (spec: "Role-based access к
результатам"). Keys are looked up by SHA-256 hash — these are high-entropy
generated secrets, not user passwords, so a fast hash is correct (see
db.ApiKey's docstring).

References `black_ice_common.db` as a module and calls through it dynamically
(`db.SessionLocal()`) rather than importing `SessionLocal` by name — tests
patch `db.SessionLocal` directly, and a name-import binds to the pre-patch
object at import time instead of picking up the patch (see decisioning.py for
the same pattern, and the bugs it was introduced to avoid).

Real IdP support (see oidc.py): settings.auth_backend picks which credential
`_authenticate` accepts. "api_key" (default) is everything above, unchanged.
"oidc" instead validates a Bearer JWT against a real OpenID Connect provider
(built against Keycloak) — role comes straight from the token's realm-role
claim, checked against this same ROLES dict, so ROLES stays the one place
that defines what each role can do regardless of credential type.
"""
import hashlib

from fastapi import Header, HTTPException

import black_ice_common.db as db
from black_ice_common.config import settings
from black_ice_common.secrets import get_secret

ROLES = {
    "admin": {"enroll", "identify", "audit", "cameras", "access_rules", "alert_rules"},
    "operator": {"identify"},
    "viewer": set(),
}


def hash_key(raw_key: str) -> str:
    return hashlib.sha256(raw_key.encode()).hexdigest()


def lookup_key(raw_key: str) -> "db.ApiKey | None":
    key_hash = hash_key(raw_key)
    with db.SessionLocal() as session:
        return (
            session.query(db.ApiKey)
            .filter(db.ApiKey.key_hash == key_hash, db.ApiKey.revoked_at.is_(None))
            .first()
        )


def seed_from_env() -> None:
    """One-time bootstrap: if api_keys is empty, seed it from
    BLACK_ICE_API_KEYS ("key:role,key:role" — the format this table replaces).
    Lets existing compose/K8s env-var config keep working on first boot;
    from then on keys are managed as real rows, not a redeploy."""
    with db.SessionLocal() as session:
        if session.query(db.ApiKey).first() is not None:
            return
        raw = get_secret("BLACK_ICE_API_KEYS", default="dev-admin-key:admin,dev-operator-key:operator")
        for pair in raw.split(","):
            key, role = pair.split(":")
            session.add(db.ApiKey(key_hash=hash_key(key.strip()), role=role.strip(), label="seeded-from-env"))
        session.commit()


def _authenticate(x_api_key: str | None, authorization: str | None) -> tuple[str, str]:
    """Returns (role, label). label is the ApiKey's own label in api_key mode,
    or the token's `sub` claim in oidc mode — both are just human-readable
    identifiers for whoever's logged in, never used for authorization itself."""
    if settings.auth_backend == "oidc":
        if authorization is None or not authorization.startswith("Bearer "):
            raise HTTPException(401, "missing Authorization: Bearer token")
        from black_ice_common.oidc import validate_token  # lazy: PyJWT stays optional for api_key-only deploys

        try:
            subject, role = validate_token(authorization.removeprefix("Bearer "))
        except Exception as exc:
            raise HTTPException(401, f"invalid token: {exc}") from exc
        return role, subject

    if x_api_key is None:
        raise HTTPException(401, "missing X-API-Key header")
    found = lookup_key(x_api_key)
    if found is None:
        raise HTTPException(401, "invalid API key")
    return found.role, found.label


def authenticate_for_login(x_api_key: str | None, authorization: str | None) -> tuple[str, str]:
    return _authenticate(x_api_key, authorization)


def require(permission: str):
    def dependency(
        x_api_key: str | None = Header(default=None),
        authorization: str | None = Header(default=None),
    ) -> str:
        role, _label = _authenticate(x_api_key, authorization)
        if permission not in ROLES.get(role, set()):
            raise HTTPException(403, f"role '{role}' lacks permission '{permission}'")
        return role

    return dependency
