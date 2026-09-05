import datetime
from unittest.mock import MagicMock

import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import rsa


@pytest.fixture(scope="module")
def keypair():
    private_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    return private_key, private_key.public_key()


def _make_token(private_key, *, issuer="http://keycloak.test/realms/black-ice", roles=("admin",), sub="user-1", exp_delta=3600):
    now = datetime.datetime.now(datetime.timezone.utc)
    claims = {
        "iss": issuer,
        "sub": sub,
        "iat": now,
        "exp": now + datetime.timedelta(seconds=exp_delta),
        "realm_access": {"roles": list(roles)},
    }
    return jwt.encode(claims, private_key, algorithm="RS256", headers={"kid": "test-key"})


@pytest.fixture()
def oidc_module(monkeypatch, keypair):
    private_key, public_key = keypair
    monkeypatch.setenv("KAFKA_BOOTSTRAP_SERVERS", "localhost:19092")

    import black_ice_common.config as config
    import black_ice_common.oidc as oidc

    monkeypatch.setattr(config.settings, "auth_backend", "oidc")
    monkeypatch.setattr(config.settings, "oidc_issuer_url", "http://keycloak.test/realms/black-ice")
    monkeypatch.setattr(config.settings, "oidc_audience", None)

    fake_signing_key = MagicMock()
    fake_signing_key.key = public_key
    fake_jwks_client = MagicMock()
    fake_jwks_client.get_signing_key_from_jwt.return_value = fake_signing_key
    monkeypatch.setattr(oidc, "_get_jwks_client", lambda: fake_jwks_client)

    return config, oidc, private_key


def test_validate_token_extracts_recognized_role(oidc_module):
    config, oidc, private_key = oidc_module
    token = _make_token(private_key, roles=("admin", "some-other-realm-role"))

    subject, role = oidc.validate_token(token)

    assert subject == "user-1"
    assert role == "admin"


def test_validate_token_rejects_token_with_no_recognized_role(oidc_module):
    config, oidc, private_key = oidc_module
    token = _make_token(private_key, roles=("some-unrelated-role",))

    with pytest.raises(ValueError):
        oidc.validate_token(token)


def test_validate_token_rejects_expired_token(oidc_module):
    config, oidc, private_key = oidc_module
    token = _make_token(private_key, exp_delta=-3600)

    with pytest.raises(jwt.ExpiredSignatureError):
        oidc.validate_token(token)


def test_validate_token_rejects_wrong_issuer(oidc_module):
    config, oidc, private_key = oidc_module
    token = _make_token(private_key, issuer="http://not-the-configured-issuer")

    with pytest.raises(jwt.InvalidIssuerError):
        oidc.validate_token(token)


def test_jwks_client_fetches_from_discovery_url_not_issuer_url(monkeypatch):
    """oidc_discovery_url exists so match can reach Keycloak via the
    compose-internal hostname while oidc_issuer_url stays the externally-
    reachable one tokens actually carry as `iss` (see the module docstring
    and infra/docker-compose.yml's keycloak service) — this pins that the
    JWKS fetch actually goes to discovery_url, not issuer_url, when they
    differ."""
    import black_ice_common.config as config
    import black_ice_common.oidc as oidc

    monkeypatch.setattr(config.settings, "oidc_issuer_url", "http://localhost:8180/realms/black-ice")
    monkeypatch.setattr(config.settings, "oidc_discovery_url", "http://keycloak:8080/realms/black-ice")
    monkeypatch.setattr(oidc, "_jwks_client", None)
    monkeypatch.setattr(oidc, "_jwks_client_issuer", None)

    captured_urls = []
    monkeypatch.setattr(oidc, "PyJWKClient", lambda url: captured_urls.append(url))

    oidc._get_jwks_client()

    assert captured_urls == ["http://keycloak:8080/realms/black-ice/protocol/openid-connect/certs"]


def test_validate_token_rejects_token_signed_by_a_different_key(oidc_module):
    config, oidc, private_key = oidc_module
    other_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    token = _make_token(other_key)  # signed by a key that isn't the one _get_jwks_client() returns

    with pytest.raises(jwt.InvalidSignatureError):
        oidc.validate_token(token)
