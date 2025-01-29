"""add timestamps to token_usage

Revision ID: 76c92fb83936
Revises: c638547ec04f
Create Date: 2025-01-29 23:34:20.505464

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '76c92fb83936'
down_revision = 'c638547ec04f'
branch_labels = None
depends_on = None


def upgrade() -> None:
    # 새로운 컬럼 추가
    op.add_column('token_usage', 
        sa.Column('created_at', sa.DateTime(timezone=True), 
                 server_default=sa.text('now()'), 
                 nullable=False)
    )
    op.add_column('token_usage', 
        sa.Column('updated_at', sa.DateTime(timezone=True),
                 server_default=sa.text('now()'),
                 onupdate=sa.text('now()'),
                 nullable=False)
    )


def downgrade() -> None:
    # 컬럼 제거
    op.drop_column('token_usage', 'updated_at')
    op.drop_column('token_usage', 'created_at') 