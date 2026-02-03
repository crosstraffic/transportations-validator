"""Initial schema

Revision ID: 001
Revises:
Create Date: 2025-01-28

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "001"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # Source documents
    op.create_table(
        "source_doc",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("title", sa.String(255), nullable=False),
        sa.Column("abbreviation", sa.String(50), nullable=False),
        sa.Column("edition", sa.String(50), nullable=True),
        sa.Column("publisher", sa.String(255), nullable=True),
        sa.Column("publication_year", sa.Integer(), nullable=True),
        sa.Column("jurisdiction", sa.String(100), nullable=False, server_default="federal"),
        sa.Column("priority", sa.Integer(), nullable=False, server_default="100"),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("abbreviation"),
    )

    # Source references
    op.create_table(
        "source_ref",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("source_doc_id", sa.Integer(), nullable=False),
        sa.Column("chapter", sa.String(50), nullable=True),
        sa.Column("section", sa.String(100), nullable=True),
        sa.Column("page_start", sa.Integer(), nullable=True),
        sa.Column("page_end", sa.Integer(), nullable=True),
        sa.Column("exhibit", sa.String(50), nullable=True),
        sa.Column("equation", sa.String(50), nullable=True),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(["source_doc_id"], ["source_doc.id"], ondelete="CASCADE"),
    )

    # Condition types
    op.create_table(
        "condition_type",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(100), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("rust_enum", sa.String(100), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("name"),
    )

    # Condition values
    op.create_table(
        "condition_value",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("condition_type_id", sa.Integer(), nullable=False),
        sa.Column("value", sa.String(100), nullable=False),
        sa.Column("display_name", sa.String(100), nullable=True),
        sa.Column("rust_variant", sa.String(100), nullable=True),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("sort_order", sa.Integer(), nullable=False, server_default="0"),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(["condition_type_id"], ["condition_type.id"], ondelete="CASCADE"),
    )

    # Parameters
    op.create_table(
        "parameter",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(100), nullable=False),
        sa.Column("rust_field", sa.String(100), nullable=False),
        sa.Column(
            "facility_type",
            sa.Enum(
                "BasicFreeway",
                "TwoLaneHighway",
                "MultilaneHighway",
                "UrbanStreet",
                name="facilitytype",
            ),
            nullable=False,
        ),
        sa.Column("unit", sa.String(50), nullable=True),
        sa.Column(
            "data_type",
            sa.Enum("float", "integer", "percentage", "enum", name="datatype"),
            nullable=False,
            server_default="float",
        ),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("typical_min", sa.Float(), nullable=True),
        sa.Column("typical_max", sa.Float(), nullable=True),
        sa.Column("allowed_values", sa.Text(), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.PrimaryKeyConstraint("id"),
    )

    # Parameter aliases
    op.create_table(
        "parameter_alias",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("parameter_id", sa.Integer(), nullable=False),
        sa.Column("alias", sa.String(100), nullable=False),
        sa.Column("source", sa.String(50), nullable=False, server_default="manual"),
        sa.Column("confidence", sa.Float(), nullable=False, server_default="1.0"),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(["parameter_id"], ["parameter.id"], ondelete="CASCADE"),
    )

    # Design rules
    op.create_table(
        "design_rule",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("parameter_id", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column(
            "rule_type",
            sa.Enum("range", "min", "max", "enum", "formula", "relationship", name="ruletype"),
            nullable=False,
        ),
        sa.Column(
            "severity",
            sa.Enum("error", "warning", "info", name="severity"),
            nullable=False,
            server_default="error",
        ),
        sa.Column("min_value", sa.Float(), nullable=True),
        sa.Column("max_value", sa.Float(), nullable=True),
        sa.Column("allowed_values", sa.Text(), nullable=True),
        sa.Column("formula", sa.Text(), nullable=True),
        sa.Column("min_inclusive", sa.Boolean(), nullable=False, server_default="true"),
        sa.Column("max_inclusive", sa.Boolean(), nullable=False, server_default="true"),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default="true"),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(["parameter_id"], ["parameter.id"], ondelete="CASCADE"),
    )

    # Rule conditions
    op.create_table(
        "rule_condition",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("rule_id", sa.Integer(), nullable=False),
        sa.Column("condition_value_id", sa.Integer(), nullable=False),
        sa.Column("is_required", sa.Boolean(), nullable=False, server_default="true"),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(["rule_id"], ["design_rule.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["condition_value_id"], ["condition_value.id"], ondelete="CASCADE"),
    )

    # Rule sources
    op.create_table(
        "rule_source",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("rule_id", sa.Integer(), nullable=False),
        sa.Column("source_ref_id", sa.Integer(), nullable=False),
        sa.Column("is_primary", sa.Boolean(), nullable=False, server_default="false"),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(["rule_id"], ["design_rule.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["source_ref_id"], ["source_ref.id"], ondelete="CASCADE"),
    )

    # Create indexes
    op.create_index("ix_parameter_facility_type", "parameter", ["facility_type"])
    op.create_index("ix_parameter_rust_field", "parameter", ["rust_field"])
    op.create_index("ix_parameter_alias_alias", "parameter_alias", ["alias"])
    op.create_index("ix_design_rule_parameter_id", "design_rule", ["parameter_id"])
    op.create_index(
        "ix_condition_value_condition_type_id", "condition_value", ["condition_type_id"]
    )


def downgrade() -> None:
    op.drop_table("rule_source")
    op.drop_table("rule_condition")
    op.drop_table("design_rule")
    op.drop_table("parameter_alias")
    op.drop_table("parameter")
    op.drop_table("condition_value")
    op.drop_table("condition_type")
    op.drop_table("source_ref")
    op.drop_table("source_doc")

    op.execute("DROP TYPE IF EXISTS facilitytype")
    op.execute("DROP TYPE IF EXISTS datatype")
    op.execute("DROP TYPE IF EXISTS ruletype")
    op.execute("DROP TYPE IF EXISTS severity")
