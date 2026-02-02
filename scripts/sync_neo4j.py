"""Sync PostgreSQL data to Neo4j knowledge graph."""

import asyncio

from transportations_validator.db.neo4j.connection import close_neo4j, get_neo4j_session
from transportations_validator.db.neo4j.sync import Neo4jSyncService
from transportations_validator.db.postgres import async_session_maker
from transportations_validator.db.postgres.connection import close_db


async def main() -> None:
    """Sync all data from PostgreSQL to Neo4j."""
    print("Starting PostgreSQL → Neo4j sync...")

    try:
        async with async_session_maker() as pg_session:
            async for neo4j_session in get_neo4j_session():
                sync_service = Neo4jSyncService(pg_session, neo4j_session)
                result = await sync_service.sync_all()

                if result.errors:
                    print(f"Sync completed with errors: {result.errors}")
                else:
                    print("Sync completed successfully!")

                print(f"  Nodes synced: {result.nodes_synced}")
                print(f"  Relationships synced: {result.relationships_synced}")

    finally:
        await close_neo4j()
        await close_db()


if __name__ == "__main__":
    asyncio.run(main())
