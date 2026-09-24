from typing import Any

from sqlalchemy import ForeignKey, Integer, JSON, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, TimestampMixin, uuid4_str

class Policy(TimestampMixin, Base):
    __tablename__ = "policies"
    __table_args__ = (
        UniqueConstraint("child_id", "version", name="uq_policy_child_version")
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uuid4_str)
    child_id: Mapped[str] = mapped_column(
        ForeignKey("children.id", ondelete="CASCADE"),
        index=True,
        nullable=False,
    )
    version: Mapped[int] = mapped_column(Integer, nullable=False)
    payload: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    signature: Mapped[str] = mapped_column(String(64), nullable=False)

    child = relationship("Child", back_populates="policies")