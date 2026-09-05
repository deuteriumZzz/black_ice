"""Real IdP support (STATUS.md gap: static API keys, no real identity
provider). Validates a Bearer JWT against Keycloak — issuer/audience/expiry/
signature checks are standard OIDC via PyJWT, but the JWKS endpoint is
Keycloak's own stable path convention (`/protocol/openid-connect/certs`)
rather than derived from the `.well-known/openid-configuration` discovery
document. That's deliberate, not laziness: the SPA (browser) and match reach
Keycloak via genuinely different hostnames in local compose (match through
the compose-internal service name, the browser only through Keycloak's
published port), but Keycloak's discovery document self-reports ONE fixed
hostname (KC_HOSTNAME) for every URL it advertises — including jwks_uri —
so trusting that document's jwks_uri verbatim would hand match a URL it
can't necessarily reach. Building the JWKS URL from oidc_discovery_url
directly sidesteps that; oidc_issuer_url (what tokens actually carry as
`iss`, fixed by the same KC_HOSTNAME) is still what's cryptographically
verified, so a forged issuer is still rejected exactly as with full
discovery. Role comes straight from the token's `realm_access.roles` claim,
matched against rbac.ROLES — no separate IdP-role -> app-role mapping table,
so a Keycloak realm role must be literally named "admin"/"operator"/"viewer"
to be recognized. ROLES stays the single source of truth for what each role
can do, IdP or not.

JWKS caching/rotation handling is PyJWKClient's own (refetches on an unknown
kid) — not reimplemented here.
"""
import jwt
from jwt import PyJWKClient

from black_ice_common.config import settings

_jwks_client: PyJWKClient | None = None
_jwks_client_issuer: str | None = None


def _get_jwks_client() -> PyJWKClient:
    global _jwks_client, _jwks_client_issuer
    if _jwks_client is None or _jwks_client_issuer != settings.oidc_issuer_url:
        base = settings.oidc_discovery_url or settings.oidc_issuer_url
        _jwks_client = PyJWKClient(f"{base}/protocol/openid-connect/certs")
        _jwks_client_issuer = settings.oidc_issuer_url
    return _jwks_client


def validate_token(token: str) -> tuple[str, str]:
    """Returns (subject, role) from a verified token. Raises on anything
    invalid — expired, bad signature, wrong issuer, or no recognized role."""
    from black_ice_common.rbac import ROLES  # avoids a rbac<->oidc import cycle at module load

    signing_key = _get_jwks_client().get_signing_key_from_jwt(token)
    claims = jwt.decode(
        token,
        signing_key.key,
        algorithms=["RS256"],
        issuer=settings.oidc_issuer_url,
        audience=settings.oidc_audience,
        options={"verify_aud": settings.oidc_audience is not None},
    )
    roles = claims.get("realm_access", {}).get("roles", [])
    role = next((r for r in roles if r in ROLES), None)
    if role is None:
        raise ValueError(f"token has no recognized realm role (has {roles!r}, need one of {sorted(ROLES)})")
    return claims["sub"], role
