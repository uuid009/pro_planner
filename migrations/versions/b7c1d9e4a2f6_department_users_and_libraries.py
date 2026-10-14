"""部门用户与资料库范围

Revision ID: b7c1d9e4a2f6
Revises: a3ddee2e501f
Create Date: 2026-10-13 16:30:00
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "b7c1d9e4a2f6"
down_revision: str | Sequence[str] | None = "a3ddee2e501f"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "users",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("username", sa.String(length=32), nullable=False),
        sa.Column("password_hash", sa.String(length=200), nullable=False),
        sa.Column("department", sa.String(length=32), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "department IN ('algorithm', 'framework', 'testing')",
            name="ck_users_department",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("username"),
    )
    op.create_table(
        "auth_sessions",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("token_hash", sa.String(length=64), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("token_hash"),
    )
    op.add_column(
        "documents",
        sa.Column("library", sa.String(length=32), server_default="public", nullable=False),
    )
    op.create_check_constraint(
        "ck_documents_library",
        "documents",
        "library IN ('public', 'algorithm', 'framework', 'testing')",
    )
    op.add_column("workflow_runs", sa.Column("owner_username", sa.String(length=32), nullable=True))
    op.add_column(
        "workflow_runs", sa.Column("owner_department", sa.String(length=32), nullable=True)
    )


def downgrade() -> None:
    op.drop_column("workflow_runs", "owner_department")
    op.drop_column("workflow_runs", "owner_username")
    op.drop_constraint("ck_documents_library", "documents", type_="check")
    op.drop_column("documents", "library")
    op.drop_table("auth_sessions")
    op.drop_table("users")
