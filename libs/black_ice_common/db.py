import datetime
import sqlite3
import uuid

from sqlalchemy import create_engine, event, String, Float, Boolean, DateTime, ForeignKey, Integer
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


def init_db() -> None:
    Base.metadata.create_all(engine)
