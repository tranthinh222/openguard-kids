from datetime import datetime

from sqlalchemy import DateTime, Float, ForeignKey, Integer, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, TimestampMixin, uuid4_str
from app.core.encrypted import EncryptedText

class Device(TimestampMixin, Base):
    __tablename__ = "devices"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uuid4_str)
    child_id: Mapped[str] = mapped_column(
        ForeignKey("children.id", ondelete="CASCADE"),
        index=True,
        nullable=False
    )

    device_name: Mapped[str] = mapped_column(EncryptedText("device.device_name", 255), nullable=False)
    fingerprint_hash: Mapped[str] = mapped_column(String(64), nullable=False)

    status: Mapped[str] = mapped_column(String(32), default="active", nullable=False)
    consent_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    privacy_notice_version: Mapped[str | None] = mapped_column(String(32), nullable=True)
    last_seen_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    current_policy_version: Mapped[Integer] = mapped_column(Integer, default=0, nullable=False)
    quota_used_sec: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    clock_drift_sec: Mapped[float | None] = mapped_column(Float, nullable=True)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    child = relationship("Child", back_populates="devices")
    refresh_tokens = relationship(
        "DeviceRefreshToken",
        back_populates="device",
        cascade="all, delete-orphan",
    )
