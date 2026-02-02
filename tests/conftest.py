"""Pytest fixtures for testing."""

from collections.abc import AsyncGenerator

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool
from transportations_validator.models.base import Base

# Use in-memory SQLite for testing
TEST_DATABASE_URL = "sqlite+aiosqlite:///:memory:"


@pytest.fixture
async def engine():
    """Create test database engine."""
    engine = create_async_engine(
        TEST_DATABASE_URL,
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    yield engine

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)

    await engine.dispose()


@pytest.fixture
async def session(engine) -> AsyncGenerator[AsyncSession, None]:
    """Create test database session."""
    async_session = async_sessionmaker(
        engine,
        class_=AsyncSession,
        expire_on_commit=False,
    )

    async with async_session() as session:
        yield session


@pytest.fixture
def basicfreeway_data() -> dict:
    """Sample BasicFreeways data."""
    return {
        "apd": 10,
        "trd": 2,
        "bffs": 65.0,
        "ffs": 62.5,
        "ffs_adj": 61.0,
        "capacity": 2200.0,
        "lane_count": 3,
        "density": 18.5,
        "length": 2.5,
        "lw": 12.0,
        "lc_r": 6,
        "lc_l": 2,
        "p_t": 0.08,
        "demand_flow_i": 4500.0,
        "v_p": 4800.0,
        "phf": 0.92,
        "grade": 2.0,
        "terrain_type": "Level",
        "sut_percentage": 50,
        "city_type": "Urban",
        "highway_type": "basic",
        "median_type": "divided",
        "speed_limit": 65,
        "phv": 1.0,
        "los": "C",
    }


@pytest.fixture
def twolane_data() -> dict:
    """Sample TwoLaneHighways data."""
    return {
        "segments": [
            {
                "passing_type": 0,
                "length": 1.5,
                "grade": 3.0,
                "spl": 55.0,
                "volume": 800,
                "phf": 0.90,
                "phv": 10.0,
                "vertical_class": 3,
            }
        ],
        "lane_width": 11.0,
        "shoulder_width": 4.0,
        "apd": 5.0,
    }


@pytest.fixture
def llm_response_text() -> str:
    """Sample LLM response text for extraction testing."""
    return """
    Based on my analysis, the two-lane highway segment should have the following characteristics:

    - Lane width: 11 feet
    - Shoulder width: 4 feet
    - Speed limit: 55 mph
    - Grade: 3.0%
    - Design radius: 1200 ft for the horizontal curve
    - Superelevation: 4%
    - Expected traffic volume: 850 veh/hr

    The terrain is classified as rolling terrain, which affects the heavy vehicle adjustment factors.
    """
