"""Add topology schema for road segments and curves

Revision ID: 004
Revises: 003
Create Date: 2025-02-03

Adds tables for road network topology to support the Knowledge Graph extension:
- road_segments: Road segment entities
- horizontal_curves: Horizontal curve geometry
- vertical_curves: Vertical curve geometry
- topology_nodes: Network nodes (intersections, endpoints)
- segment_connections: Segment-to-segment relationships

Paper Section: 2.2 (Knowledge Graph Schema Extension)
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "004"
down_revision: str | None = "003"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # Create node_type enum
    op.execute(
        """
        DO $$ BEGIN
            CREATE TYPE nodetype AS ENUM (
                'intersection', 'endpoint', 'merge', 'diverge', 'crossing'
            );
        EXCEPTION
            WHEN duplicate_object THEN null;
        END $$;
    """
    )

    # Create vertical_curve_type enum
    op.execute(
        """
        DO $$ BEGIN
            CREATE TYPE verticalcurvetype AS ENUM ('crest', 'sag');
        EXCEPTION
            WHEN duplicate_object THEN null;
        END $$;
    """
    )

    # Create topology_nodes table
    op.create_table(
        "topology_nodes",
        sa.Column("id", sa.Integer(), nullable=False, primary_key=True),
        sa.Column("external_id", sa.String(255), nullable=False, unique=True),
        sa.Column("name", sa.String(255), nullable=True),
        sa.Column("x", sa.Float(), nullable=False),
        sa.Column("y", sa.Float(), nullable=False),
        sa.Column("z", sa.Float(), nullable=True),
        sa.Column(
            "node_type",
            sa.Enum(
                "intersection",
                "endpoint",
                "merge",
                "diverge",
                "crossing",
                name="nodetype",
            ),
            nullable=False,
            server_default="endpoint",
        ),
        sa.Column("created_at", sa.DateTime(), server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.text("now()")),
    )

    # Create road_segments table
    op.create_table(
        "road_segments",
        sa.Column("id", sa.Integer(), nullable=False, primary_key=True),
        sa.Column("external_id", sa.String(255), nullable=False, unique=True),
        sa.Column("name", sa.String(255), nullable=True),
        sa.Column("length", sa.Float(), nullable=False),
        sa.Column("grade", sa.Float(), nullable=True),
        sa.Column("lane_count", sa.Integer(), nullable=True),
        sa.Column("passing_type", sa.Integer(), nullable=True),
        sa.Column("start_node_id", sa.Integer(), sa.ForeignKey("topology_nodes.id"), nullable=True),
        sa.Column("end_node_id", sa.Integer(), sa.ForeignKey("topology_nodes.id"), nullable=True),
        sa.Column("road_id", sa.String(255), nullable=True),
        sa.Column("opendrive_road_id", sa.String(255), nullable=True),
        sa.Column("created_at", sa.DateTime(), server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.text("now()")),
    )

    # Create horizontal_curves table
    op.create_table(
        "horizontal_curves",
        sa.Column("id", sa.Integer(), nullable=False, primary_key=True),
        sa.Column("external_id", sa.String(255), nullable=False, unique=True),
        sa.Column("segment_id", sa.Integer(), sa.ForeignKey("road_segments.id"), nullable=False),
        sa.Column("radius", sa.Float(), nullable=False),
        sa.Column("central_angle", sa.Float(), nullable=True),
        sa.Column("arc_length", sa.Float(), nullable=True),
        sa.Column("superelevation", sa.Float(), nullable=True),
        sa.Column("hor_class", sa.Integer(), nullable=True),
        sa.Column("s_start", sa.Float(), nullable=True),
        sa.Column("s_end", sa.Float(), nullable=True),
        sa.Column("created_at", sa.DateTime(), server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.text("now()")),
    )

    # Create vertical_curves table
    op.create_table(
        "vertical_curves",
        sa.Column("id", sa.Integer(), nullable=False, primary_key=True),
        sa.Column("external_id", sa.String(255), nullable=False, unique=True),
        sa.Column("segment_id", sa.Integer(), sa.ForeignKey("road_segments.id"), nullable=False),
        sa.Column("grade_in", sa.Float(), nullable=False),
        sa.Column("grade_out", sa.Float(), nullable=False),
        sa.Column("length", sa.Float(), nullable=False),
        sa.Column("k_value", sa.Float(), nullable=True),
        sa.Column("vertical_class", sa.Integer(), nullable=True),
        sa.Column(
            "curve_type",
            sa.Enum("crest", "sag", name="verticalcurvetype"),
            nullable=True,
        ),
        sa.Column("s_start", sa.Float(), nullable=True),
        sa.Column("created_at", sa.DateTime(), server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.text("now()")),
    )

    # Create segment_connections table for CONNECTED_TO relationships
    op.create_table(
        "segment_connections",
        sa.Column("id", sa.Integer(), nullable=False, primary_key=True),
        sa.Column(
            "from_segment_id",
            sa.Integer(),
            sa.ForeignKey("road_segments.id"),
            nullable=False,
        ),
        sa.Column(
            "to_segment_id",
            sa.Integer(),
            sa.ForeignKey("road_segments.id"),
            nullable=False,
        ),
        sa.Column(
            "connection_node_id",
            sa.Integer(),
            sa.ForeignKey("topology_nodes.id"),
            nullable=True,
        ),
        sa.Column("connection_type", sa.String(50), nullable=True),
        sa.Column("created_at", sa.DateTime(), server_default=sa.text("now()")),
    )

    # Create indexes for efficient queries
    op.create_index(
        "ix_road_segments_road_id",
        "road_segments",
        ["road_id"],
    )
    op.create_index(
        "ix_road_segments_opendrive_id",
        "road_segments",
        ["opendrive_road_id"],
    )
    op.create_index(
        "ix_horizontal_curves_segment",
        "horizontal_curves",
        ["segment_id"],
    )
    op.create_index(
        "ix_vertical_curves_segment",
        "vertical_curves",
        ["segment_id"],
    )
    op.create_index(
        "ix_segment_connections_from",
        "segment_connections",
        ["from_segment_id"],
    )
    op.create_index(
        "ix_segment_connections_to",
        "segment_connections",
        ["to_segment_id"],
    )


def downgrade() -> None:
    # Drop indexes
    op.drop_index("ix_segment_connections_to", table_name="segment_connections")
    op.drop_index("ix_segment_connections_from", table_name="segment_connections")
    op.drop_index("ix_vertical_curves_segment", table_name="vertical_curves")
    op.drop_index("ix_horizontal_curves_segment", table_name="horizontal_curves")
    op.drop_index("ix_road_segments_opendrive_id", table_name="road_segments")
    op.drop_index("ix_road_segments_road_id", table_name="road_segments")

    # Drop tables
    op.drop_table("segment_connections")
    op.drop_table("vertical_curves")
    op.drop_table("horizontal_curves")
    op.drop_table("road_segments")
    op.drop_table("topology_nodes")

    # Drop enums
    op.execute("DROP TYPE IF EXISTS verticalcurvetype")
    op.execute("DROP TYPE IF EXISTS nodetype")
