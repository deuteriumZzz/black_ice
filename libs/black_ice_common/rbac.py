"""Static API-key -> role mapping (spec: "Role-based access к результатам").
ponytail: no real IdP, just a header check — swap for OIDC/JWT once there's an
actual identity provider to federate against."""
import os

from fastapi import Header, HTTPException

ROLES = {"admin": {"enroll", "identify", "audit"}, "operator": {"identify"}, "viewer": set()}


def _load_keys() -> dict[str, str]:
    """BLACK_ICE_API_KEYS="key1:admin,key2:operator" """
    raw = os.environ.get("BLACK_ICE_API_KEYS", "dev-admin-key:admin,dev-operator-key:operator")
    keys = {}
    for pair in raw.split(","):
        key, role = pair.split(":")
        keys[key.strip()] = role.strip()
    return keys


_API_KEYS = _load_keys()


def require(permission: str):
    def dependency(x_api_key: str | None = Header(default=None)) -> str:
        if x_api_key is None:
            raise HTTPException(401, "missing X-API-Key header")
        role = _API_KEYS.get(x_api_key)
        if role is None:
            raise HTTPException(401, "invalid API key")
        if permission not in ROLES.get(role, set()):
            raise HTTPException(403, f"role '{role}' lacks permission '{permission}'")
        return role

    return dependency
