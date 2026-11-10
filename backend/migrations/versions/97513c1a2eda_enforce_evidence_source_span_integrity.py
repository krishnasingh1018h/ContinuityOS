"""enforce evidence source span integrity

Revision ID: 97513c1a2eda
Revises: 1ed076ea49c9
Create Date: 2026-11-10 11:16:50.399306
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = '97513c1a2eda'
down_revision: Union[str, None] = '1ed076ea49c9'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table("source_spans") as batch_op:
        batch_op.create_unique_constraint(
            "uq_source_spans_id_source_id",
            ["id", "source_id"],
        )
    with op.batch_alter_table("claim_evidence") as batch_op:
        batch_op.create_foreign_key(
            "fk_claim_evidence_span_source",
            "source_spans",
            ["source_span_id", "source_id"],
            ["id", "source_id"],
            ondelete="CASCADE",
        )


def downgrade() -> None:
    with op.batch_alter_table("claim_evidence") as batch_op:
        batch_op.drop_constraint("fk_claim_evidence_span_source", type_="foreignkey")
    with op.batch_alter_table("source_spans") as batch_op:
        batch_op.drop_constraint("uq_source_spans_id_source_id", type_="unique")
