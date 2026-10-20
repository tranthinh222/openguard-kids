"""screen time requests commands

Revision ID: c8d1f2a7b901
Revises: f8422d83f693
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "c8d1f2a7b901"
down_revision: Union[str, None] = "f8422d83f693"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table("devices") as batch_op:
        batch_op.add_column(sa.Column("quota_used_sec", sa.Integer(), nullable=False, server_default="0"))
        batch_op.add_column(sa.Column("clock_drift_sec", sa.Float(), nullable=True))

    op.create_table(
        "child_requests",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("child_id", sa.String(length=36), nullable=False),
        sa.Column("device_id", sa.String(length=36), nullable=False),
        sa.Column("type", sa.String(length=32), nullable=False),
        sa.Column("requested_minutes", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("parent_response", sa.String(length=255), nullable=True),
        sa.Column("responded_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("responded_by", sa.String(length=36), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["child_id"], ["children.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["device_id"], ["devices.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["responded_by"], ["users.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_child_requests_child_id", "child_requests", ["child_id"])
    op.create_index("ix_child_requests_device_id", "child_requests", ["device_id"])
    op.create_index("ix_child_requests_status", "child_requests", ["status"])

    op.create_table(
        "device_commands",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("device_id", sa.String(length=36), nullable=False),
        sa.Column("type", sa.String(length=32), nullable=False),
        sa.Column("payload", sa.JSON(), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("sent_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("ack_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("error", sa.String(length=255), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["device_id"], ["devices.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_device_commands_device_id", "device_commands", ["device_id"])
    op.create_index("ix_device_commands_status", "device_commands", ["status"])


def downgrade() -> None:
    op.drop_index("ix_device_commands_status", table_name="device_commands")
    op.drop_index("ix_device_commands_device_id", table_name="device_commands")
    op.drop_table("device_commands")
    op.drop_index("ix_child_requests_status", table_name="child_requests")
    op.drop_index("ix_child_requests_device_id", table_name="child_requests")
    op.drop_index("ix_child_requests_child_id", table_name="child_requests")
    op.drop_table("child_requests")
    with op.batch_alter_table("devices") as batch_op:
        batch_op.drop_column("clock_drift_sec")
        batch_op.drop_column("quota_used_sec")
