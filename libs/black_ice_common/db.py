import datetime
import sqlite3
import uuid

from sqlalchemy import create_engine, event, String, Float, Boolean, DateTime, ForeignKey, Integer, Time
from sqlalchemy.engine import Engine
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, sessionmaker

from black_ice_common.config import settings

engine = create_engine(settings.database_url)
SessionLocal = sessionmaker(bind=engine)


@event.listens_for(Engine, "connect")
def _enforce_sqlite_foreign_keys(dbapi_connection, _connection_record) -> None:
    """SQLite ignores FK constraints (including ON DELETE actions) unless told
    otherwise per-connection — Postgres always enforces them. Without this,
    tests against the project's sqlite test fixtures can pass while the same
    schema breaks against real Postgres (this happened: DELETE /identities
    worked in every test but raised a ForeignKeyViolation for real, because
    audit_log.identity_id had no ON DELETE behavior — fixed alongside this).
    No-ops for non-sqlite connections (e.g. psycopg2 in prod)."""
    if isinstance(dbapi_connection, sqlite3.Connection):
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()


class Base(DeclarativeBase):
    pass


class Identity(Base):
    __tablename__ = "identities"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    name: Mapped[str] = mapped_column(String, nullable=False)
    created_at: Mapped[datetime.datetime] = mapped_column(DateTime, default=datetime.datetime.utcnow)
    # Compliance: consent + retention (spec section 4, "Compliance")
    consent_given: Mapped[bool] = mapped_column(Boolean, default=False)
    retention_expires_at: Mapped[datetime.datetime | None] = mapped_column(DateTime, nullable=True)


class AuditLog(Base):
    """Who/when/what was queried and the outcome — not who a match *is*, so the log
    itself stays useful even after the matched identity is purged."""
    __tablename__ = "audit_log"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    ts: Mapped[datetime.datetime] = mapped_column(DateTime, default=datetime.datetime.utcnow)
    # ON DELETE SET NULL — the docstring above promises audit rows survive a
    # revoke; without this, Postgres enforces the FK and the DELETE on
    # identities just fails. sqlite (every test in this repo) doesn't enforce
    # FKs by default, so this was silently broken until tested against a real
    # Postgres server.
    identity_id: Mapped[str | None] = mapped_column(ForeignKey("identities.id", ondelete="SET NULL"), nullable=True)
    matched: Mapped[bool] = mapped_column(Boolean, nullable=False)
    score: Mapped[float] = mapped_column(Float, nullable=False)
    requested_by: Mapped[str] = mapped_column(String, default="unknown")  # API key / role that triggered the query
    camera_id: Mapped[str | None] = mapped_column(String, nullable=True)
    # Shadow-mode deploy (spec: "Shadow-mode деплой новой модели эмбеддингов перед
    # переключением"): frame_id/track_id correlate a primary decision with the
    # shadow-model decision computed from the exact same detected face, so
    # scripts/shadow_report.py can measure agreement before promoting a candidate
    # model. model_version is "primary" for the real access-control decision, or
    # the candidate model's pack name for a shadow decision (which never affects
    # the real outcome — see services/match/app/shadow_consumer.py).
    frame_id: Mapped[str | None] = mapped_column(String, nullable=True)
    track_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    model_version: Mapped[str] = mapped_column(String, default="primary")
    # NULL = no access-rule check ran for this row (POST /identify, or a shadow
    # decision) — distinct from False ("checked and denied"). Milestone 3.
    access_granted: Mapped[bool | None] = mapped_column(Boolean, nullable=True)


class ApiKey(Base):
    """API-key -> role, stored as a SHA-256 hash (see rbac.py). These are
    high-entropy generated secrets, not user-chosen passwords, so a fast hash
    is the right tool — same posture as GitHub/Stripe token storage, not a
    password KDF like bcrypt/argon2."""
    __tablename__ = "api_keys"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    key_hash: Mapped[str] = mapped_column(String, unique=True, nullable=False)
    role: Mapped[str] = mapped_column(String, nullable=False)
    label: Mapped[str] = mapped_column(String, default="")
    created_at: Mapped[datetime.datetime] = mapped_column(DateTime, default=datetime.datetime.utcnow)
    revoked_at: Mapped[datetime.datetime | None] = mapped_column(DateTime, nullable=True)


class Camera(Base):
    """Camera registry (spec Phase 1 Milestone 2). `camera_id` is the stable
    key an ingest process is given via its CAMERA_ID env var — it looks its
    own row up by this, not by `id`. Creating a row here also deploys a
    running ingest process for it when settings.orchestrator_backend is set
    (see ingest_orchestrator.py) — with the default "none" backend, it's
    still a manual deploy-time step, same as before."""
    __tablename__ = "cameras"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    camera_id: Mapped[str] = mapped_column(String, unique=True, nullable=False)
    name: Mapped[str] = mapped_column(String, nullable=False)
    source: Mapped[str] = mapped_column(String, nullable=False)
    site: Mapped[str | None] = mapped_column(String, nullable=True)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    ingest_fps: Mapped[float] = mapped_column(Float, default=5.0)
    created_at: Mapped[datetime.datetime] = mapped_column(DateTime, default=datetime.datetime.utcnow)
    # Written by ingest's own heartbeat call, not derived from Prometheus —
    # match doesn't query Prometheus anywhere else, and adding that dependency
    # just to answer "is this camera alive" would be a heavier coupling than
    # the heartbeat call ingest already has an HTTP client for.
    last_seen_at: Mapped[datetime.datetime | None] = mapped_column(DateTime, nullable=True)


class AccessRule(Base):
    """Access-control rule (spec Phase 1 Milestone 3): identity X may enter at
    camera Y during window Z. Default-deny/allow-list: an identity with zero
    matching enabled rules is denied everywhere — see
    black_ice_common.access_rules.is_access_allowed for the evaluation. Deleting
    the identity deletes its rules too (CASCADE, unlike AuditLog's SET NULL) —
    a rule for a purged identity is meaningless, not audit history worth keeping."""
    __tablename__ = "access_rules"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    identity_id: Mapped[str] = mapped_column(ForeignKey("identities.id", ondelete="CASCADE"), nullable=False)
    # NULL = all cameras. Plain string like AuditLog.camera_id, not a FK to
    # cameras.camera_id — a rule can predate or outlive a camera's registry row.
    camera_id: Mapped[str | None] = mapped_column(String, nullable=True)
    # NULL = every day. CSV of "mon".."sun", e.g. "mon,tue,wed,thu,fri".
    weekdays: Mapped[str | None] = mapped_column(String, nullable=True)
    # NULL = all day. ponytail: same-day windows only (start < end) — an
    # overnight window like 22:00-06:00 isn't supported; add wraparound
    # handling in is_access_allowed if a real schedule needs it.
    start_time: Mapped[datetime.time | None] = mapped_column(Time, nullable=True)
    end_time: Mapped[datetime.time | None] = mapped_column(Time, nullable=True)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime.datetime] = mapped_column(DateTime, default=datetime.datetime.utcnow)


class AlertRule(Base):
    """Notification config (spec Phase 1 Milestone 4): fire a webhook when a
    security-relevant event happens. Distinct from observability/prometheus/
    alerts.yml, which alerts ops on infra health (latency, error rate) — this
    is business/security events (access denied, camera offline), configured by
    an operator through admin-ui, not baked into a PromQL file.

    identity_id/camera_id are optional filters: NULL means "any". A rule with
    both NULL for event_type="access_denied" fires on every denial anywhere —
    likely too noisy for real use, but not invalid, so not rejected."""
    __tablename__ = "alert_rules"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    event_type: Mapped[str] = mapped_column(String, nullable=False)  # "access_denied" | "camera_offline"
    identity_id: Mapped[str | None] = mapped_column(String, nullable=True)
    camera_id: Mapped[str | None] = mapped_column(String, nullable=True)
    webhook_url: Mapped[str] = mapped_column(String, nullable=False)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime.datetime] = mapped_column(DateTime, default=datetime.datetime.utcnow)


def init_db() -> None:
    Base.metadata.create_all(engine)
