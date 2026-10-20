from sqlalchemy import ForeignKey, Integer, String, DateTime
from datetime import datetime
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, TimestampMixin, uuid4_str
from app.core.encrypted import EncryptedText

class Child(TimestampMixin, Base):
    __tablename__="children"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uuid4_str)
    parent_id: Mapped[str] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"),
        index=True,
        nullable=False,
    )
    display_name: Mapped[str] = mapped_column(EncryptedText("child.display_name", 100), nullable=False)
    birth_year: Mapped[int | None] = mapped_column(Integer, nullable=True)

    parent = relationship("User", back_populates="children")
    devices = relationship("Device", back_populates="child", cascade="all, delete-orphan")
    policies = relationship("Policy", back_populates="child", cascade="all, delete-orphan")
