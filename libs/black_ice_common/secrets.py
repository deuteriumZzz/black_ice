"""Optional Vault-backed secret resolution (STATUS.md's "секреты в Vault" gap
— DATABASE_URL/BLACK_ICE_API_KEYS previously had to live in plaintext env vars/
Helm values.yaml). VAULT_ADDR unset (the default for docker-compose/local dev)
means every caller here just falls through to the given env var/default —
Vault is an opt-in production path, not a local-dev requirement, so `docker
compose up` needs no Vault server.

Plain `requests` against Vault's KV v2 HTTP API rather than the `hvac` client
library — this project already depends on requests (see alerting.py), and a
KV v2 read is a single GET; a whole client library would be more than a
handful of secret reads need.
"""
import logging
import os

import requests

log = logging.getLogger("black_ice.secrets")


def get_secret(name: str, default: str | None = None) -> str | None:
    """name is both the env-var fallback name and the key looked up inside the
    Vault KV v2 payload at VAULT_KV_PATH (e.g. a `vault kv put secret/black-ice
    DATABASE_URL=... BLACK_ICE_API_KEYS=...` populates both names)."""
    vault_addr = os.environ.get("VAULT_ADDR")
    vault_token = os.environ.get("VAULT_TOKEN")
    if vault_addr and vault_token:
        kv_path = os.environ.get("VAULT_KV_PATH", "secret/data/black-ice")
        try:
            resp = requests.get(f"{vault_addr}/v1/{kv_path}", headers={"X-Vault-Token": vault_token}, timeout=5)
            resp.raise_for_status()
            value = resp.json()["data"]["data"].get(name)
            if value is not None:
                return value
        except requests.RequestException as exc:
            log.warning("Vault read failed for %s, falling back to env var: %s", name, exc)
    return os.environ.get(name, default)
