"""Week 03 activity, usage snapshots and policy audit."""
from alembic import op
import sqlalchemy as sa

revision = "e31008a1"
down_revision = "c8d1f2a7b901"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table("activity_events",
        sa.Column("event_id", sa.String(36), primary_key=True),
        sa.Column("child_id", sa.String(36), sa.ForeignKey("children.id", ondelete="CASCADE"), nullable=False),
        sa.Column("device_id", sa.String(36), sa.ForeignKey("devices.id", ondelete="CASCADE"), nullable=False),
        sa.Column("type", sa.String(32), nullable=False),
        sa.Column("subject", sa.String(253)),
        sa.Column("duration_sec", sa.Integer(), nullable=False),
        sa.Column("policy_id", sa.String(36), sa.ForeignKey("policies.id", ondelete="SET NULL")),
        sa.Column("occurred_at", sa.DateTime(), nullable=False),
        sa.Column("received_at", sa.DateTime(), nullable=False),
        sa.Column("effective_at", sa.DateTime(), nullable=False),
        sa.Column("clock_trusted", sa.Boolean(), nullable=False),
        sa.Column("payload_hash", sa.String(64), nullable=False))
    op.create_index("ix_activity_child_time", "activity_events", ["child_id", "effective_at"])
    op.create_index("ix_activity_received", "activity_events", ["received_at"])
    op.create_table("screen_usage_daily",
        sa.Column("device_id", sa.String(36), sa.ForeignKey("devices.id", ondelete="CASCADE"), primary_key=True),
        sa.Column("day", sa.Date(), primary_key=True),
        sa.Column("child_id", sa.String(36), sa.ForeignKey("children.id", ondelete="CASCADE"), nullable=False),
        sa.Column("duration_sec", sa.Integer(), nullable=False))
    op.create_index("ix_screen_usage_daily_child_id", "screen_usage_daily", ["child_id"])
    op.create_table("policy_audits",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("child_id", sa.String(36), sa.ForeignKey("children.id", ondelete="CASCADE"), nullable=False),
        sa.Column("actor_id", sa.String(36), sa.ForeignKey("users.id", ondelete="SET NULL")),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("old_version", sa.Integer(), nullable=False),
        sa.Column("new_version", sa.Integer(), nullable=False),
        sa.Column("old_payload", sa.JSON(), nullable=False),
        sa.Column("new_payload", sa.JSON(), nullable=False))
    op.create_index("ix_policy_audits_child_id", "policy_audits", ["child_id"])


def downgrade():
    op.drop_table("policy_audits")
    op.drop_table("screen_usage_daily")
    op.drop_table("activity_events")
