import datetime
import uuid

from sqlalchemy import create_engine, String, Float, Boolean, DateTime, ForeignKey, Integer
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, sessionmaker

from black_ice_common.config import settings

engine = create_engine(settings.database_url)
SessionLocal = sessionmaker(bind=engine)


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
    identity_id: Mapped[str | None] = mapped_column(ForeignKey("identities.id"), nullable=True)
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


def init_db() -> None:
    Base.metadata.create_all(engine)
