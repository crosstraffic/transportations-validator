"""Parameter and parameter alias models."""

from enum import Enum
from typing import Optional

from sqlalchemy import String, Text, Float, ForeignKey, Enum as SQLEnum
from sqlalchemy.orm import Mapped, mapped_column, relationship

from transportations_validator.models.base import Base, TimestampMixin


class FacilityType(str, Enum):
    """Transportation facility types."""

    BASIC_FREEWAY = "BasicFreeway"
    TWO_LANE_HIGHWAY = "TwoLaneHighway"
    MULTILANE_HIGHWAY = "MultilaneHighway"
    URBAN_STREET = "UrbanStreet"


class DataType(str, Enum):
    """Parameter data types."""

    FLOAT = "float"
    INTEGER = "integer"
    PERCENTAGE = "percentage"
    ENUM = "enum"


class Parameter(Base, TimestampMixin):
    """Design parameter definition."""

    __tablename__ = "parameter"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    rust_field: Mapped[str] = mapped_column(String(100), nullable=False)
    facility_type: Mapped[FacilityType] = mapped_column(
        SQLEnum(FacilityType, values_callable=lambda x: [e.value for e in x]),
        nullable=False
    )
    unit: Mapped[Optional[str]] = mapped_column(String(50))
    data_type: Mapped[DataType] = mapped_column(
        SQLEnum(DataType, values_callable=lambda x: [e.value for e in x]),
        default=DataType.FLOAT
    )
    description: Mapped[Optional[str]] = mapped_column(Text)

    # Typical value range (for display/reference only)
    typical_min: Mapped[Optional[float]] = mapped_column(Float)
    typical_max: Mapped[Optional[float]] = mapped_column(Float)

    # Allowed enum values (if data_type is ENUM)
    allowed_values: Mapped[Optional[str]] = mapped_column(Text)

    # Relationships
    aliases: Mapped[list["ParameterAlias"]] = relationship(
        back_populates="parameter", cascade="all, delete-orphan"
    )

    def __repr__(self) -> str:
        return f"<Parameter(id={self.id}, name='{self.name}', facility='{self.facility_type}')>"


class ParameterAlias(Base, TimestampMixin):
    """Alternative names for parameters (for LLM response matching)."""

    __tablename__ = "parameter_alias"

    id: Mapped[int] = mapped_column(primary_key=True)
    parameter_id: Mapped[int] = mapped_column(ForeignKey("parameter.id"), nullable=False)
    alias: Mapped[str] = mapped_column(String(100), nullable=False)
    source: Mapped[str] = mapped_column(String(50), default="manual")
    confidence: Mapped[float] = mapped_column(Float, default=1.0)

    # Relationships
    parameter: Mapped[Parameter] = relationship(back_populates="aliases")

    def __repr__(self) -> str:
        return f"<ParameterAlias(id={self.id}, alias='{self.alias}')>"
