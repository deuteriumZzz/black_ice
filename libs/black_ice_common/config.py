from pydantic_settings import BaseSettings

from black_ice_common.secrets import get_secret


class Settings(BaseSettings):
    # Kafka / Redpanda (Kafka-protocol compatible; swap bootstrap_servers for a real
    # Kafka cluster in prod, client code is unchanged)
    kafka_bootstrap_servers: str = "localhost:9092"
    topic_frames: str = "frames.raw"
    topic_detections: str = "faces.detected"
    topic_embeddings: str = "faces.embedded"
    topic_embeddings_shadow: str = "faces.embedded.shadow"
    consumer_group_detect: str = "detect-workers"
    consumer_group_embed: str = "embed-workers"
    consumer_group_match: str = "match-workers"
    consumer_group_shadow: str = "shadow-workers"

    # Vector search / metadata. `collection_name` is a Qdrant *alias* (see
    # vectorstore.py) — the concrete collection behind it can be swapped via
    # scripts/reindex_faces.py with zero downtime.
    qdrant_url: str = "http://localhost:6333"
    collection_name: str = "faces"
    shadow_collection_name: str = "faces_shadow"  # shadow-mode gallery, see embedding_shadow.py
    embedding_dim: int = 512
    hnsw_m: int = 16  # Qdrant default; bump for higher recall at the cost of index build time/memory
    hnsw_ef_construct: int = 100  # Qdrant default; higher = better recall, slower indexing
    hnsw_ef_search: int = 128  # search-time candidate list size; higher = better recall, slower query
    qdrant_shard_number: int = 1  # >1 shards the collection across Qdrant's storage, for horizontal scale
    database_url: str = "postgresql+psycopg2://black_ice:black_ice@localhost:5432/black_ice"

    # Decisioning
    match_threshold: float = 0.45  # cosine similarity; below this = "unknown"

    # Shadow-mode model deploy (spec: evaluate a candidate embedding model against
    # live traffic before promoting it — never affects the real access decision).
    # Requires its own gallery (shadow_collection_name): a different model's
    # embedding space isn't comparable to the primary model's, so /enroll embeds
    # into both galleries when this is on. Off by default — zero overhead.
    shadow_embedding_enabled: bool = False
    shadow_embedding_pack: str = "buffalo_s"  # smaller/faster candidate vs. primary's buffalo_l

    # Ingest
    camera_id: str = "cam-0"
    source: str = "demo"  # "demo" | webcam index (e.g. "0") | rtsp:// url | file path
    ingest_fps: float = 5.0
    # Where ingest fetches its own camera config from (skipped entirely in
    # SOURCE=demo mode, which stays fully env-driven — see services/ingest/main.py).
    match_api_url: str = "http://localhost:8000"
    heartbeat_interval_s: float = 5.0

    # Tracking / frame sampling (see services/tracking) — avoids re-embedding a
    # static face on every frame
    embed_interval_frames: int = 15
    track_max_age_frames: int = 30
    track_iou_distance_threshold: float = 0.7

    # Liveness (see libs/black_ice_common/liveness.py). Heuristic is off by
    # default; set liveness_onnx_model_path to a converted anti-spoofing
    # checkpoint to use a real trained classifier instead.
    liveness_check_enabled: bool = False
    liveness_min_sharpness: float = 40.0
    liveness_min_chroma_std: float = 5.0
    liveness_onnx_model_path: str | None = None
    liveness_onnx_threshold: float = 0.5

    # Rate limiting / circuit breaker on the match API
    rate_limit: str = "30/minute"
    breaker_fail_max: int = 5
    breaker_reset_timeout_s: int = 30

    # CORS — the admin-ui SPA (services/match serves the API only, not the
    # frontend) runs on its own origin. Comma-separated list. 5173 = vite dev
    # server, 5174 = the admin-ui container's published port in compose.
    cors_allowed_origins: str = "http://localhost:5173,http://localhost:5174"

    # Compliance
    retention_days: int = 90

    metrics_port: int = 9100

    # Alerting (see libs/black_ice_common/alerting.py, Phase 1 Milestone 4).
    # A camera silent longer than this (no heartbeat — see Milestone 2) is
    # "offline" for scripts/camera_offline_check.py. Bigger than admin-ui's
    # own 30s staleness badge threshold on purpose: this fires a real webhook,
    # not just a UI dot, so it should tolerate a couple of missed heartbeats
    # before alerting, not the first one.
    camera_offline_threshold_s: float = 60.0
    alert_webhook_timeout_s: float = 5.0

    # Ingest orchestration (see ingest_orchestrator.py) — Milestone 2's known
    # gap: registering a camera configured it but never deployed a process
    # for it. "none" keeps that manual workflow; "docker"/"kubernetes"
    # auto-deploy one ingest process per camera on create/enable and tear it
    # down on delete/disable.
    orchestrator_backend: str = "none"  # "none" | "docker" | "kubernetes"
    ingest_image: str = "infra-ingest:latest"
    orchestrator_docker_network: str | None = None  # None = auto-detect match's own network
    k8s_namespace: str = "default"

    # Real IdP (see libs/black_ice_common/oidc.py) — replaces static API keys
    # when set to "oidc". Built and verified against Keycloak; any standards-
    # compliant OpenID Connect provider works since discovery/JWKS are fetched
    # dynamically, not hardcoded to Keycloak's URL shape.
    auth_backend: str = "api_key"  # "api_key" | "oidc"
    oidc_issuer_url: str | None = None  # the `iss` claim every token must carry, e.g. http://localhost:8180/realms/black-ice
    # Where match itself fetches discovery/JWKS from — defaults to oidc_issuer_url
    # (the normal case: one real public hostname reachable by both the SPA and
    # match). Only needs overriding in local compose, where the browser can
    # reach Keycloak solely via its published port (oidc_issuer_url) while match
    # reaches it via the compose-internal service name instead — Keycloak's
    # fixed KC_HOSTNAME makes every token's `iss` the same either way.
    oidc_discovery_url: str | None = None
    oidc_audience: str | None = None  # verified only when set — Keycloak's default access token has no aud claim

    class Config:
        env_file = ".env"


settings = Settings()
# Vault override, opt-in (see secrets.py) — a no-op when VAULT_ADDR isn't set,
# so plain env vars/`.env` keep working unchanged for local dev/compose.
settings.database_url = get_secret("DATABASE_URL", default=settings.database_url)
