"""Reminders, and a mailbox the worker can be seen through

Revision ID: a74cac4ef220
Revises: b2d5a8f31c74
Create Date: 2026-09-17

A reminder stores a wall clock and an IANA zone rather than an instant.
"Every day at nine" means nine in March and nine in July, and an instant
does not - adding twenty-four hours across a daylight-saving change moves
the clock by an hour and nobody can say why. `anchor_date` is kept for the
same reason at a different scale: every occurrence is derived from it, so a
monthly reminder on the 31st returns to the 31st in March instead of
ratcheting down to the 28th and staying there.

`notereminderdelivery` exists to make sending at-most-once. The row is
written and committed before the mail goes out, and its unique key on
(reminder, occurrence) means two workers claiming the same row still produce
one delivery. A crash in between loses an occurrence, which is visible as
`sent_at IS NULL`; the other ordering would risk sending twice, and a
duplicate reminder costs the trust of every later one.

`capturedemailrow` is the dev mailbox. `LoggingEmailSender` keeps messages in
a list belonging to one process, and reminders are sent from the worker, which
is not the process the mailbox endpoint runs in. Nothing had ever emailed from
the worker before, so this has never mattered; without it an end-to-end test
for reminders would poll an empty inbox for ever. Written only when
FASTAPI_ENV is development, and inert everywhere else.
"""

import sqlalchemy as sa
import sqlmodel.sql.sqltypes
from alembic import op

revision: str = "a74cac4ef220"
down_revision: str | None = "b2d5a8f31c74"
branch_labels: str | None = None
depends_on: str | None = None


def upgrade() -> None:
    op.create_table('capturedemailrow',
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('to_email', sqlmodel.sql.sqltypes.AutoString(length=320), nullable=False),
    sa.Column('subject', sqlmodel.sql.sqltypes.AutoString(length=500), nullable=False),
    sa.Column('text', sa.Text(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index('ix_capturedemailrow_to_created', 'capturedemailrow', ['to_email', 'created_at'], unique=False)
    op.create_table('notereminder',
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('note_id', sa.Uuid(), nullable=False),
    sa.Column('user_id', sa.Uuid(), nullable=False),
    sa.Column('local_time', sa.Time(), nullable=False),
    sa.Column('timezone', sqlmodel.sql.sqltypes.AutoString(length=64), nullable=False),
    sa.Column('anchor_date', sa.Date(), nullable=False),
    sa.Column('recurrence', sa.String(length=12), nullable=False),
    sa.Column('ends', sa.String(length=12), nullable=False),
    sa.Column('ends_on', sa.Date(), nullable=True),
    sa.Column('ends_after', sa.Integer(), nullable=True),
    sa.Column('next_run_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('next_local_date', sa.Date(), nullable=False),
    sa.Column('locked_until', sa.DateTime(timezone=True), nullable=True),
    sa.Column('status', sa.String(length=12), nullable=False),
    sa.Column('sent_count', sa.Integer(), nullable=False),
    sa.Column('attempts', sa.Integer(), nullable=False),
    sa.Column('last_sent_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('last_error', sa.Text(), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
    sa.ForeignKeyConstraint(['note_id'], ['note.id'], ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['user_id'], ['user.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('note_id', name='uq_notereminder_note')
    )
    op.create_index('ix_notereminder_due', 'notereminder', ['next_run_at'], unique=False, postgresql_where=sa.text("status = 'active'"))
    op.create_table('notereminderdelivery',
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('reminder_id', sa.Uuid(), nullable=False),
    sa.Column('occurrence_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('skipped', sa.Integer(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('sent_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('error', sa.Text(), nullable=True),
    sa.ForeignKeyConstraint(['reminder_id'], ['notereminder.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('reminder_id', 'occurrence_at', name='uq_reminderdelivery_occurrence')
    )


def downgrade() -> None:
    op.drop_table("notereminderdelivery")
    op.drop_index("ix_notereminder_due", table_name="notereminder")
    op.drop_table("notereminder")
    op.drop_index("ix_capturedemailrow_to_created", table_name="capturedemailrow")
    op.drop_table("capturedemailrow")
