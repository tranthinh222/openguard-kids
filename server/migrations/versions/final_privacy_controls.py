"""Consent, policy audit IP and privacy controls.

Revision ID: f420_privacy
Revises: e31008a1
"""
from alembic import op
import sqlalchemy as sa

revision = 'f420_privacy'
down_revision = 'e31008a1'
branch_labels = depends_on = None


def upgrade():
    from app.core.encrypted import encryption_key
    encryption_key()  # Fail before SQLite DDL if the deployment key is missing.
    op.add_column('users', sa.Column('email_lookup_hash', sa.String(64), nullable=True))
    op.create_index('ix_users_email_lookup_hash', 'users', ['email_lookup_hash'], unique=True)
    op.create_table('control_audits',
                    sa.Column('id', sa.String(36), primary_key=True),
                    sa.Column('child_id', sa.String(36), sa.ForeignKey('children.id', ondelete='CASCADE'), nullable=False),
                    sa.Column('actor_id', sa.String(36), nullable=True),
                    sa.Column('source_ip', sa.String(64), nullable=True),
                    sa.Column('action', sa.String(64), nullable=False),
                    sa.Column('created_at', sa.DateTime(), nullable=False),
                    sa.Column('old_value', sa.JSON(), nullable=False),
                    sa.Column('new_value', sa.JSON(), nullable=False))
    op.create_index('ix_control_audits_child_id', 'control_audits', ['child_id'])
    op.add_column('enrollment_codes', sa.Column('consent_at', sa.DateTime(), nullable=True))
    op.add_column('enrollment_codes', sa.Column('privacy_notice_version', sa.String(32), nullable=True))
    op.add_column('devices', sa.Column('consent_at', sa.DateTime(), nullable=True))
    op.add_column('devices', sa.Column('privacy_notice_version', sa.String(32), nullable=True))
    op.add_column('policy_audits', sa.Column('source_ip', sa.String(64), nullable=True))
    op.add_column('child_requests', sa.Column('subject', sa.String(253), nullable=True))
    op.create_table('erasure_jobs',
                    sa.Column('id', sa.String(36), primary_key=True),
                    sa.Column('token_hash', sa.String(64), nullable=False, unique=True),
                    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
                    sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False))
    _rewrite_sensitive(encrypt=True)


def downgrade():
    from app.core.encrypted import encryption_key
    encryption_key()
    _rewrite_sensitive(encrypt=False)
    op.drop_index('ix_users_email_lookup_hash', table_name='users')
    # SQLite >=3.35 supports DROP COLUMN in place. Rebuilding a referenced
    # parent table with batch_alter_table triggers ON DELETE CASCADE.
    op.drop_column('users', 'email_lookup_hash')
    op.drop_table('control_audits')
    op.drop_table('erasure_jobs')
    for table, column in [('child_requests', 'subject'), ('devices', 'privacy_notice_version'), ('devices', 'consent_at'),
                          ('policy_audits', 'source_ip'), ('enrollment_codes', 'privacy_notice_version'),
                          ('enrollment_codes', 'consent_at')]:
        op.drop_column(table, column)


def _rewrite_sensitive(encrypt):
    # Keep the same DATA_ENCRYPTION_KEY for upgrades, runtime and downgrades.
    # SQLite is the supported deployment backend.
    from app.core.encrypted import EncryptedText, PREFIX, email_lookup
    connection = op.get_bind()
    for table, column, purpose, length in [
        ('users', 'email', 'user.email', 320),
        ('children', 'display_name', 'child.display_name', 100),
        ('devices', 'device_name', 'device.device_name', 255),
        ('child_requests', 'parent_response', 'request.parent_response', 255),
    ]:
        codec = EncryptedText(purpose, length)
        rows = connection.execute(sa.text(f'SELECT id, {column} FROM {table}')).fetchall()
        for identifier, value in rows:
            if value is None:
                continue
            if encrypt and table == 'users':
                plain = codec.process_result_value(value, connection.dialect)
                connection.execute(sa.text('UPDATE users SET email_lookup_hash=:lookup WHERE id=:id'),
                                   {'lookup': email_lookup(plain), 'id': identifier})
            if encrypt and not value.startswith(PREFIX):
                value = codec.process_bind_param(value, connection.dialect)
            elif not encrypt and value.startswith(PREFIX):
                value = codec.process_result_value(value, connection.dialect)
            else:
                continue
            connection.execute(sa.text(f'UPDATE {table} SET {column}=:value WHERE id=:id'),
                               {'value': value, 'id': identifier})
    import json
    from app.core.encrypted import EncryptedJSON
    codec = EncryptedJSON("command.payload")
    for identifier, raw in connection.execute(sa.text('SELECT id,payload FROM device_commands')).fetchall():
        value = json.loads(raw)
        value = (codec.process_bind_param(value, connection.dialect) if encrypt
                 else codec.process_result_value(value, connection.dialect))
        connection.execute(sa.text('UPDATE device_commands SET payload=:value WHERE id=:id'),
                           {'value': json.dumps(value), 'id': identifier})
