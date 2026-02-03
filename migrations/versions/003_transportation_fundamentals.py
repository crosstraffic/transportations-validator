"""Add core transportation fundamentals facility types

Revision ID: 003
Revises: 002
Create Date: 2025-02-03

Adds facility types for:
- NetworkTopology: OpenDRIVE network interoperability
- TrafficFlow: Fundamental traffic flow analysis
- GeometricDesign: Safety stress testing
"""

from collections.abc import Sequence

from alembic import op

revision: str = "003"
down_revision: str | None = "002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # Add new facility types for core transportation fundamentals
    op.execute("ALTER TYPE facilitytype ADD VALUE IF NOT EXISTS 'NetworkTopology'")
    op.execute("ALTER TYPE facilitytype ADD VALUE IF NOT EXISTS 'TrafficFlow'")
    op.execute("ALTER TYPE facilitytype ADD VALUE IF NOT EXISTS 'GeometricDesign'")


def downgrade() -> None:
    # Note: PostgreSQL does not support removing enum values directly
    # The enum values are left in place (they won't cause issues)
    pass
