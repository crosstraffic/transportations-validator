"""Source document and reference repository."""

from typing import Sequence

from sqlalchemy import select
from sqlalchemy.orm import selectinload

from transportations_validator.db.postgres.repositories.base import BaseRepository
from transportations_validator.models.source import SourceDoc, SourceRef


class SourceRepository(BaseRepository[SourceDoc]):
    """Repository for SourceDoc operations."""

    model = SourceDoc

    async def get_by_abbreviation(self, abbreviation: str) -> SourceDoc | None:
        """Get source document by abbreviation."""
        result = await self.session.execute(
            select(SourceDoc)
            .where(SourceDoc.abbreviation == abbreviation)
            .options(selectinload(SourceDoc.references))
        )
        return result.scalar_one_or_none()

    async def get_by_jurisdiction(
        self, jurisdiction: str
    ) -> Sequence[SourceDoc]:
        """Get all source documents for a jurisdiction."""
        result = await self.session.execute(
            select(SourceDoc)
            .where(SourceDoc.jurisdiction == jurisdiction)
            .order_by(SourceDoc.priority)
        )
        return result.scalars().all()

    async def get_with_references(self, id: int) -> SourceDoc | None:
        """Get source document with references loaded."""
        result = await self.session.execute(
            select(SourceDoc)
            .where(SourceDoc.id == id)
            .options(selectinload(SourceDoc.references))
        )
        return result.scalar_one_or_none()

    async def create_reference(
        self,
        source_doc_id: int,
        chapter: str | None = None,
        section: str | None = None,
        page_start: int | None = None,
        page_end: int | None = None,
        exhibit: str | None = None,
        equation: str | None = None,
        notes: str | None = None,
    ) -> SourceRef:
        """Create a source reference."""
        ref = SourceRef(
            source_doc_id=source_doc_id,
            chapter=chapter,
            section=section,
            page_start=page_start,
            page_end=page_end,
            exhibit=exhibit,
            equation=equation,
            notes=notes,
        )
        self.session.add(ref)
        await self.session.flush()
        await self.session.refresh(ref)
        return ref

    async def get_reference_by_location(
        self,
        abbreviation: str,
        chapter: str | None = None,
        section: str | None = None,
    ) -> SourceRef | None:
        """Find a reference by document abbreviation and location."""
        query = (
            select(SourceRef)
            .join(SourceDoc)
            .where(SourceDoc.abbreviation == abbreviation)
        )

        if chapter:
            query = query.where(SourceRef.chapter == chapter)
        if section:
            query = query.where(SourceRef.section == section)

        result = await self.session.execute(query)
        return result.scalar_one_or_none()
