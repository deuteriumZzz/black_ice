import responses


def test_falls_back_to_env_var_when_vault_not_configured(monkeypatch):
    monkeypatch.delenv("VAULT_ADDR", raising=False)
    monkeypatch.setenv("DATABASE_URL", "postgresql://from-env")

    from black_ice_common.secrets import get_secret

    assert get_secret("DATABASE_URL") == "postgresql://from-env"


def test_falls_back_to_default_when_neither_vault_nor_env_set(monkeypatch):
    monkeypatch.delenv("VAULT_ADDR", raising=False)
    monkeypatch.delenv("SOME_UNSET_SECRET", raising=False)

    from black_ice_common.secrets import get_secret

    assert get_secret("SOME_UNSET_SECRET", default="fallback") == "fallback"


@responses.activate
def test_reads_from_vault_when_configured(monkeypatch):
    monkeypatch.setenv("VAULT_ADDR", "http://vault.test:8200")
    monkeypatch.setenv("VAULT_TOKEN", "test-token")
    monkeypatch.setenv("DATABASE_URL", "postgresql://from-env-should-not-be-used")

    responses.get(
        "http://vault.test:8200/v1/secret/data/black-ice",
        json={"data": {"data": {"DATABASE_URL": "postgresql://from-vault"}}},
        status=200,
    )

    from black_ice_common.secrets import get_secret

    assert get_secret("DATABASE_URL") == "postgresql://from-vault"
    assert responses.calls[0].request.headers["X-Vault-Token"] == "test-token"


@responses.activate
def test_falls_back_to_env_when_vault_unreachable(monkeypatch):
    import requests.exceptions

    monkeypatch.setenv("VAULT_ADDR", "http://vault.test:8200")
    monkeypatch.setenv("VAULT_TOKEN", "test-token")
    monkeypatch.setenv("DATABASE_URL", "postgresql://from-env-fallback")

    responses.get("http://vault.test:8200/v1/secret/data/black-ice", body=requests.exceptions.ConnectionError("refused"))

    from black_ice_common.secrets import get_secret

    assert get_secret("DATABASE_URL") == "postgresql://from-env-fallback"


@responses.activate
def test_falls_back_to_env_when_key_missing_from_vault_payload(monkeypatch):
    monkeypatch.setenv("VAULT_ADDR", "http://vault.test:8200")
    monkeypatch.setenv("VAULT_TOKEN", "test-token")
    monkeypatch.setenv("BLACK_ICE_API_KEYS", "fallback-key:admin")

    responses.get(
        "http://vault.test:8200/v1/secret/data/black-ice",
        json={"data": {"data": {"DATABASE_URL": "postgresql://from-vault"}}},
        status=200,
    )

    from black_ice_common.secrets import get_secret

    assert get_secret("BLACK_ICE_API_KEYS") == "fallback-key:admin"
