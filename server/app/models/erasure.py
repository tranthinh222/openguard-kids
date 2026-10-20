from sqlalchemy import String
from sqlalchemy.orm import Mapped, mapped_column
from app.models.base import Base, TimestampMixin, uuid4_str


class ErasureJob(TimestampMixin, Base):
    """Minimal delivery receipt, independent of the deleted child's foreign keys."""
    __tablename__ = "erasure_jobs"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uuid4_str)
    token_hash: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
