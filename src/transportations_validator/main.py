"""FastAPI application entry point."""

from contextlib import asynccontextmanager
from typing import AsyncGenerator

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from transportations_validator.config import get_settings
from transportations_validator.db.postgres.connection import engine, close_db
from transportations_validator.db.postgres import async_session_maker
from transportations_validator.db.neo4j.connection import neo4j_driver, close_neo4j, get_neo4j_session
from transportations_validator.db.neo4j.auto_sync import sync_manager, register_sync_events
from transportations_validator.db.neo4j.sync import Neo4jSyncService
from transportations_validator.api.v1 import validation, parameters, rules


settings = get_settings()


async def do_neo4j_sync() -> None:
    """Execute Neo4j sync (called by sync_manager)."""
    async with async_session_maker() as pg_session:
        async for neo4j_session in get_neo4j_session():
            sync_service = Neo4jSyncService(pg_session, neo4j_session)
            result = await sync_service.sync_all()
            if result.errors:
                import logging
                logging.getLogger(__name__).error(f"Sync errors: {result.errors}")


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    """Application lifespan manager for startup/shutdown events."""
    # Startup
    sync_manager.delay_seconds = settings.neo4j_sync_delay
    register_sync_events()
    sync_manager.set_sync_callback(do_neo4j_sync)

    yield

    # Shutdown
    await close_db()
    await close_neo4j()


app = FastAPI(
    title=settings.app_name,
    version=settings.app_version,
    description="Validates ML-generated roads, LLM responses, and software outputs against a knowledge graph of transportation design rules.",
    lifespan=lifespan,
    docs_url="/docs",
    redoc_url="/redoc",
)

# CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Include routers
app.include_router(validation.router, prefix=settings.api_prefix, tags=["validation"])
app.include_router(parameters.router, prefix=settings.api_prefix, tags=["parameters"])
app.include_router(rules.router, prefix=settings.api_prefix, tags=["rules"])


@app.get("/health")
async def health_check() -> dict[str, str]:
    """Health check endpoint."""
    return {"status": "healthy", "version": settings.app_version}


@app.get("/")
async def root() -> dict[str, str]:
    """Root endpoint."""
    return {
        "name": settings.app_name,
        "version": settings.app_version,
        "docs": "/docs",
    }


def run() -> None:
    """Run the application using uvicorn."""
    import uvicorn

    uvicorn.run(
        "transportations_validator.main:app",
        host="0.0.0.0",
        port=8000,
        reload=settings.debug,
    )


if __name__ == "__main__":
    run()
