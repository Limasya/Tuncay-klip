"""add critic_score and critique columns to clips

AI Critic (closed-loop QC) sonucunu klip satırında kalıcılaştırır.

Not: Bu depoda şema tarihsel olarak `Base.metadata.create_all` ile
kuruluyor; bu ilk alembic sürümü. Fresh bir DB'de create_all kolonları
zaten ekleyebileceği için migration idempotent yazıldı (kolon varsa atlar).

Revision ID: 0001_add_clip_critic
Revises:
Create Date: 2026-07-18
"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "0001_add_clip_critic"
down_revision = None
branch_labels = None
depends_on = None


def _existing_columns(table: str) -> set[str]:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    try:
        return {col["name"] for col in inspector.get_columns(table)}
    except Exception:
        return set()


def upgrade() -> None:
    existing = _existing_columns("clips")
    to_add = []
    if "critic_score" not in existing:
        to_add.append(sa.Column("critic_score", sa.Float(), nullable=True))
    if "critique" not in existing:
        to_add.append(sa.Column("critique", sa.JSON(), nullable=True))
    if not to_add:
        return
    with op.batch_alter_table("clips") as batch_op:
        for col in to_add:
            batch_op.add_column(col)


def downgrade() -> None:
    existing = _existing_columns("clips")
    with op.batch_alter_table("clips") as batch_op:
        if "critique" in existing:
            batch_op.drop_column("critique")
        if "critic_score" in existing:
            batch_op.drop_column("critic_score")
