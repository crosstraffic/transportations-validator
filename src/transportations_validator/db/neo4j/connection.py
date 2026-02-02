"""Neo4j connection management."""

from collections.abc import AsyncGenerator

from neo4j import AsyncDriver, AsyncGraphDatabase, AsyncSession

from transportations_validator.config import get_settings

settings = get_settings()

neo4j_driver: AsyncDriver | None = None


async def get_neo4j_driver() -> AsyncDriver:
    """Get or create Neo4j driver."""
    global neo4j_driver
    if neo4j_driver is None:
        neo4j_driver = AsyncGraphDatabase.driver(
            settings.neo4j_uri,
            auth=(settings.neo4j_user, settings.neo4j_password),
        )
    return neo4j_driver


async def get_neo4j_session() -> AsyncGenerator[AsyncSession, None]:
    """Dependency for getting Neo4j session."""
    driver = await get_neo4j_driver()
    async with driver.session() as session:
        yield session


async def close_neo4j() -> None:
    """Close Neo4j driver."""
    global neo4j_driver
    if neo4j_driver is not None:
        await neo4j_driver.close()
        neo4j_driver = None
