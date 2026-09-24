from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, String
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, uuid4_str, utc_now

class EnrollmentCode(Base):
    __tablename__  = "enrollment_codes"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uuid4_str)
    parent_id: Mapped[str] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"),
        index=True,
        nullable=False,
    )
    child_id: Mapped[str] = mapped_column(
        ForeignKey("children.id", ondelete="CASCADE"),
        index=True,
        nullable=False
    )
    code_hash: Mapped[str] = mapped_column(String(64), unique=True, index=True, nullable=False)

    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, nullable=False)
