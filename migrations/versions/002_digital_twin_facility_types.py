"""Add digital twin facility types and data types

Revision ID: 002
Revises: 001
Create Date: 2025-01-30

"""

from collections.abc import Sequence

from alembic import op

revision: str = "002"
down_revision: str | None = "001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # Add new facility types for digital twin validation
    op.execute("ALTER TYPE facilitytype ADD VALUE IF NOT EXISTS 'LaneGeometry'")
    op.execute("ALTER TYPE facilitytype ADD VALUE IF NOT EXISTS 'Sidewalk'")
    op.execute("ALTER TYPE facilitytype ADD VALUE IF NOT EXISTS 'Crosswalk'")
    op.execute("ALTER TYPE facilitytype ADD VALUE IF NOT EXISTS 'TrafficSign'")
    op.execute("ALTER TYPE facilitytype ADD VALUE IF NOT EXISTS 'TrafficSignal'")
    op.execute("ALTER TYPE facilitytype ADD VALUE IF NOT EXISTS 'PavementMarking'")

    # Add new data types
    op.execute("ALTER TYPE datatype ADD VALUE IF NOT EXISTS 'boolean'")
    op.execute("ALTER TYPE datatype ADD VALUE IF NOT EXISTS 'string'")


def downgrade() -> None:
    # Note: PostgreSQL does not support removing enum values directly
    # To properly downgrade, you would need to:
    # 1. Create a new enum type without the removed values
    # 2. Update the column to use the new enum
    # 3. Drop the old enum
    # 4. Rename the new enum
    #
    # For simplicity, we just warn that downgrade is not fully supported
    # and leave the enum values in place (they won't cause issues)
    pass
