"""API-key -> role, backed by the ApiKey table (spec: "Role-based access к
результатам"). Keys are looked up by SHA-256 hash — these are high-entropy
generated secrets, not user passwords, so a fast hash is correct (see
db.ApiKey's docstring).

References `black_ice_common.db` as a module and calls through it dynamically
(`db.SessionLocal()`) rather than importing `SessionLocal` by name — tests
patch `db.SessionLocal` directly, and a name-import binds to the pre-patch
object at import time instead of picking up the patch (see decisioning.py for
the same pattern, and the bugs it was introduced to avoid).

ponytail: no real IdP — swap for OIDC/JWT once there's an actual identity
provider; ApiKey keeps room for an `external_sub` column to grow into that
without a rewrite.
"""
import hashlib
import os

from fastapi import Header, HTTPException

import black_ice_common.db as db

ROLES = {"admin": {"enroll", "identify", "audit"}, "operator": {"identify"}, "viewer": set()}


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
        raw = os.environ.get("BLACK_ICE_API_KEYS", "dev-admin-key:admin,dev-operator-key:operator")
        for pair in raw.split(","):
            key, role = pair.split(":")
            session.add(db.ApiKey(key_hash=hash_key(key.strip()), role=role.strip(), label="seeded-from-env"))
        session.commit()


def require(permission: str):
    def dependency(x_api_key: str | None = Header(default=None)) -> str:
        if x_api_key is None:
            raise HTTPException(401, "missing X-API-Key header")
        found = lookup_key(x_api_key)
        if found is None:
            raise HTTPException(401, "invalid API key")
        if permission not in ROLES.get(found.role, set()):
            raise HTTPException(403, f"role '{found.role}' lacks permission '{permission}'")
        return found.role

    return dependency
