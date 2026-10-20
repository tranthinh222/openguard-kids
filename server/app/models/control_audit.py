from datetime import datetime
from sqlalchemy import String, DateTime, ForeignKey, JSON
from sqlalchemy.orm import Mapped, mapped_column
from app.models.base import Base, uuid4_str, utc_now
from app.core.encrypted import EncryptedJSON


class ControlAudit(Base):
    __tablename__ = "control_audits"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uuid4_str)
    child_id: Mapped[str] = mapped_column(ForeignKey("children.id", ondelete="CASCADE"), index=True)
    actor_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    source_ip: Mapped[str | None] = mapped_column(String(64), nullable=True)
    action: Mapped[str] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utc_now)
    old_value: Mapped[dict] = mapped_column(EncryptedJSON("audit.old"))
    new_value: Mapped[dict] = mapped_column(EncryptedJSON("audit.new"))
