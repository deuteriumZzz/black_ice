"""Points the match app at throwaway backends (sqlite + in-memory Qdrant) instead
of the real Postgres/Qdrant/Kafka from docker-compose, so the API can be exercised
in plain pytest. The Kafka background consumer is left pointed at an unreachable
broker — confluent-kafka's Consumer doesn't raise for that, it just logs and
retries, which is what we want here (the sync HTTP paths don't depend on it)."""

import pytest


@pytest.fixture()
def match_client(tmp_path, monkeypatch):
    monkeypatch.setenv("BLACK_ICE_API_KEYS", "admin-key:admin,op-key:operator")
    monkeypatch.setenv("KAFKA_BOOTSTRAP_SERVERS", "localhost:19092")

    import black_ice_common.config as config

    config.settings.database_url = f"sqlite:///{tmp_path}/match_test.db"

    import black_ice_common.db as db

    db.engine = db.create_engine(config.settings.database_url)
    db.SessionLocal = db.sessionmaker(bind=db.engine)

    import black_ice_common.vectorstore as vectorstore

    vectorstore.client = vectorstore.QdrantClient(location=":memory:")

    from fastapi.testclient import TestClient

    from services.match.app.main import app as match_app

    with TestClient(match_app) as client:
        yield client
