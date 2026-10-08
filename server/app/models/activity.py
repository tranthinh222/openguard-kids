from datetime import date, datetime

from sqlalchemy import Boolean, Date, DateTime, ForeignKey, Index, Integer, String, JSON
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, uuid4_str, utc_now


class ActivityEvent(Base):
    __tablename__ = "activity_events"
    __table_args__ = (Index("ix_activity_child_time", "child_id", "effective_at"),
                      Index("ix_activity_received", "received_at"))
    event_id: Mapped[str] = mapped_column(String(36), primary_key=True)
    child_id: Mapped[str] = mapped_column(ForeignKey("children.id", ondelete="CASCADE"))
    device_id: Mapped[str] = mapped_column(ForeignKey("devices.id", ondelete="CASCADE"))
    type: Mapped[str] = mapped_column(String(32))
    subject: Mapped[str | None] = mapped_column(String(253), nullable=True)
    duration_sec: Mapped[int] = mapped_column(Integer, default=0)
    policy_id: Mapped[str | None] = mapped_column(ForeignKey("policies.id", ondelete="SET NULL"), nullable=True)
    occurred_at: Mapped[datetime] = mapped_column(DateTime)
    received_at: Mapped[datetime] = mapped_column(DateTime)
    effective_at: Mapped[datetime] = mapped_column(DateTime)
    clock_trusted: Mapped[bool] = mapped_column(Boolean)
    payload_hash: Mapped[str] = mapped_column(String(64))


class ScreenUsage(Base):
    __tablename__ = "screen_usage_daily"
    device_id: Mapped[str] = mapped_column(ForeignKey("devices.id", ondelete="CASCADE"), primary_key=True)
    day: Mapped[date] = mapped_column(Date, primary_key=True)
    child_id: Mapped[str] = mapped_column(ForeignKey("children.id", ondelete="CASCADE"), index=True)
    duration_sec: Mapped[int] = mapped_column(Integer)


class PolicyAudit(Base):
    __tablename__ = "policy_audits"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uuid4_str)
    child_id: Mapped[str] = mapped_column(ForeignKey("children.id", ondelete="CASCADE"), index=True)
    actor_id: Mapped[str | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utc_now)
    old_version: Mapped[int] = mapped_column(Integer)
    new_version: Mapped[int] = mapped_column(Integer)
    old_payload: Mapped[dict] = mapped_column(JSON)
    new_payload: Mapped[dict] = mapped_column(JSON)
