"""Design rule and related models."""

from enum import Enum
from typing import Optional

from sqlalchemy import String, Text, Float, Boolean, ForeignKey, Enum as SQLEnum
from sqlalchemy.orm import Mapped, mapped_column, relationship

from transportations_validator.models.base import Base, TimestampMixin


class RuleType(str, Enum):
    """Types of validation rules."""

    RANGE = "range"
    MIN = "min"
    MAX = "max"
    ENUM = "enum"
    FORMULA = "formula"
    RELATIONSHIP = "relationship"


class Severity(str, Enum):
    """Violation severity levels."""

    ERROR = "error"
    WARNING = "warning"
    INFO = "info"


class DesignRule(Base, TimestampMixin):
    """Design rule for validating parameters."""

    __tablename__ = "design_rule"

    id: Mapped[int] = mapped_column(primary_key=True)
    parameter_id: Mapped[int] = mapped_column(ForeignKey("parameter.id"), nullable=False)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    rule_type: Mapped[RuleType] = mapped_column(
        SQLEnum(RuleType, values_callable=lambda x: [e.value for e in x]),
        nullable=False
    )
    severity: Mapped[Severity] = mapped_column(
        SQLEnum(Severity, values_callable=lambda x: [e.value for e in x]),
        default=Severity.ERROR
    )

    # Value constraints
    min_value: Mapped[Optional[float]] = mapped_column(Float)
    max_value: Mapped[Optional[float]] = mapped_column(Float)
    allowed_values: Mapped[Optional[str]] = mapped_column(Text)
    formula: Mapped[Optional[str]] = mapped_column(Text)

    # Boundary behavior
    min_inclusive: Mapped[bool] = mapped_column(Boolean, default=True)
    max_inclusive: Mapped[bool] = mapped_column(Boolean, default=True)

    # Description and error message
    description: Mapped[Optional[str]] = mapped_column(Text)
    error_message: Mapped[Optional[str]] = mapped_column(Text)

    # Active flag
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)

    # Relationships
    conditions: Mapped[list["RuleCondition"]] = relationship(
        back_populates="rule", cascade="all, delete-orphan"
    )
    sources: Mapped[list["RuleSource"]] = relationship(
        back_populates="rule", cascade="all, delete-orphan"
    )

    def __repr__(self) -> str:
        return f"<DesignRule(id={self.id}, name='{self.name}')>"


class RuleCondition(Base, TimestampMixin):
    """Condition that must be met for a rule to apply."""

    __tablename__ = "rule_condition"

    id: Mapped[int] = mapped_column(primary_key=True)
    rule_id: Mapped[int] = mapped_column(ForeignKey("design_rule.id"), nullable=False)
    condition_value_id: Mapped[int] = mapped_column(
        ForeignKey("condition_value.id"), nullable=False
    )
    is_required: Mapped[bool] = mapped_column(Boolean, default=True)

    # Relationships
    rule: Mapped[DesignRule] = relationship(back_populates="conditions")
    condition_value: Mapped["ConditionValue"] = relationship()

    def __repr__(self) -> str:
        return f"<RuleCondition(id={self.id}, rule_id={self.rule_id})>"


class RuleSource(Base, TimestampMixin):
    """Link between a rule and its source reference."""

    __tablename__ = "rule_source"

    id: Mapped[int] = mapped_column(primary_key=True)
    rule_id: Mapped[int] = mapped_column(ForeignKey("design_rule.id"), nullable=False)
    source_ref_id: Mapped[int] = mapped_column(ForeignKey("source_ref.id"), nullable=False)
    is_primary: Mapped[bool] = mapped_column(Boolean, default=False)

    # Relationships
    rule: Mapped[DesignRule] = relationship(back_populates="sources")
    source_ref: Mapped["SourceRef"] = relationship()

    def __repr__(self) -> str:
        return f"<RuleSource(id={self.id}, rule_id={self.rule_id})>"


# Import for type hints
from transportations_validator.models.condition import ConditionValue
from transportations_validator.models.source import SourceRef
