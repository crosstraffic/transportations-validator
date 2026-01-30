"""Source document and reference models."""


from sqlalchemy import ForeignKey, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from transportations_validator.models.base import Base, TimestampMixin


class SourceDoc(Base, TimestampMixin):
    """Source document (e.g., HCM 7th Edition, AASHTO Green Book)."""

    __tablename__ = "source_doc"

    id: Mapped[int] = mapped_column(primary_key=True)
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    abbreviation: Mapped[str] = mapped_column(String(50), nullable=False, unique=True)
    edition: Mapped[str | None] = mapped_column(String(50))
    publisher: Mapped[str | None] = mapped_column(String(255))
    publication_year: Mapped[int | None] = mapped_column()
    jurisdiction: Mapped[str] = mapped_column(String(100), default="federal")
    priority: Mapped[int] = mapped_column(default=100)
    description: Mapped[str | None] = mapped_column(Text)

    # Relationships
    references: Mapped[list["SourceRef"]] = relationship(
        back_populates="document", cascade="all, delete-orphan"
    )

    def __repr__(self) -> str:
        return f"<SourceDoc(id={self.id}, abbreviation='{self.abbreviation}')>"


class SourceRef(Base, TimestampMixin):
    """Reference to a specific location within a source document."""

    __tablename__ = "source_ref"

    id: Mapped[int] = mapped_column(primary_key=True)
    source_doc_id: Mapped[int] = mapped_column(ForeignKey("source_doc.id"), nullable=False)
    chapter: Mapped[str | None] = mapped_column(String(50))
    section: Mapped[str | None] = mapped_column(String(100))
    page_start: Mapped[int | None] = mapped_column()
    page_end: Mapped[int | None] = mapped_column()
    exhibit: Mapped[str | None] = mapped_column(String(50))
    equation: Mapped[str | None] = mapped_column(String(50))
    notes: Mapped[str | None] = mapped_column(Text)

    # Relationships
    document: Mapped[SourceDoc] = relationship(back_populates="references")

    def __repr__(self) -> str:
        return f"<SourceRef(id={self.id}, chapter='{self.chapter}', section='{self.section}')>"

    @property
    def citation(self) -> str:
        """Generate citation string."""
        parts = [self.document.abbreviation]
        if self.chapter:
            parts.append(f"Ch. {self.chapter}")
        if self.section:
            parts.append(f"§{self.section}")
        if self.exhibit:
            parts.append(f"Ex. {self.exhibit}")
        if self.equation:
            parts.append(f"Eq. {self.equation}")
        if self.page_start:
            if self.page_end and self.page_end != self.page_start:
                parts.append(f"pp. {self.page_start}-{self.page_end}")
            else:
                parts.append(f"p. {self.page_start}")
        return ", ".join(parts)
