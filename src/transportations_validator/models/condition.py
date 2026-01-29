"""Condition type and value models."""

from typing import Optional

from sqlalchemy import String, Text, ForeignKey
from sqlalchemy.orm import Mapped, mapped_column, relationship

from transportations_validator.models.base import Base, TimestampMixin


class ConditionType(Base, TimestampMixin):
    """Type of condition (e.g., facility_type, terrain_type, city_type)."""

    __tablename__ = "condition_type"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(100), nullable=False, unique=True)
    description: Mapped[Optional[str]] = mapped_column(Text)
    rust_enum: Mapped[Optional[str]] = mapped_column(String(100))

    # Relationships
    values: Mapped[list["ConditionValue"]] = relationship(
        back_populates="condition_type", cascade="all, delete-orphan"
    )

    def __repr__(self) -> str:
        return f"<ConditionType(id={self.id}, name='{self.name}')>"


class ConditionValue(Base, TimestampMixin):
    """Specific value for a condition type (e.g., 'Level' for terrain_type)."""

    __tablename__ = "condition_value"

    id: Mapped[int] = mapped_column(primary_key=True)
    condition_type_id: Mapped[int] = mapped_column(
        ForeignKey("condition_type.id"), nullable=False
    )
    value: Mapped[str] = mapped_column(String(100), nullable=False)
    display_name: Mapped[Optional[str]] = mapped_column(String(100))
    rust_variant: Mapped[Optional[str]] = mapped_column(String(100))
    description: Mapped[Optional[str]] = mapped_column(Text)
    sort_order: Mapped[int] = mapped_column(default=0)

    # Relationships
    condition_type: Mapped[ConditionType] = relationship(back_populates="values")

    def __repr__(self) -> str:
        return f"<ConditionValue(id={self.id}, value='{self.value}')>"
