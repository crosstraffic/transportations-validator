"""Automatic debounced sync from PostgreSQL to Neo4j."""

import asyncio
import logging
from typing import Any

from sqlalchemy import event
from sqlalchemy.orm import Session

from transportations_validator.models.parameter import Parameter, ParameterAlias
from transportations_validator.models.rule import DesignRule, RuleCondition, RuleSource
from transportations_validator.models.condition import ConditionType, ConditionValue
from transportations_validator.models.source import SourceDoc, SourceRef

logger = logging.getLogger(__name__)


class SyncManager:
    """Manages debounced Neo4j synchronization."""

    def __init__(self, delay_seconds: float = 5.0):
        self.delay_seconds = delay_seconds
        self._sync_task: asyncio.Task | None = None
        self._pending = False
        self._sync_callback: Any = None

    def set_sync_callback(self, callback: Any) -> None:
        """Set the async function to call for syncing."""
        self._sync_callback = callback

    def trigger(self) -> None:
        """Trigger a debounced sync."""
        if self._sync_callback is None:
            logger.warning("Sync callback not set, skipping sync trigger")
            return

        self._pending = True

        # Cancel existing scheduled sync
        if self._sync_task and not self._sync_task.done():
            self._sync_task.cancel()

        # Schedule new sync
        try:
            loop = asyncio.get_running_loop()
            self._sync_task = loop.create_task(self._delayed_sync())
        except RuntimeError:
            # No running loop (e.g., during startup)
            logger.debug("No event loop, sync will happen on next trigger")

    async def _delayed_sync(self) -> None:
        """Wait for delay then execute sync."""
        try:
            await asyncio.sleep(self.delay_seconds)

            if self._pending and self._sync_callback:
                self._pending = False
                logger.info("Executing debounced Neo4j sync...")
                try:
                    await self._sync_callback()
                    logger.info("Neo4j sync completed successfully")
                except Exception as e:
                    logger.error(f"Neo4j sync failed: {e}")

        except asyncio.CancelledError:
            # New sync was scheduled, this one is cancelled
            pass


# Global sync manager instance
sync_manager = SyncManager(delay_seconds=5.0)


# Models that trigger sync when changed
SYNCED_MODELS = [
    Parameter,
    ParameterAlias,
    DesignRule,
    RuleCondition,
    RuleSource,
    ConditionType,
    ConditionValue,
    SourceDoc,
    SourceRef,
]


def _on_model_change(mapper: Any, connection: Any, target: Any) -> None:
    """Called when a synced model is inserted, updated, or deleted."""
    model_name = target.__class__.__name__
    logger.debug(f"Change detected in {model_name}, scheduling sync")
    sync_manager.trigger()


def register_sync_events() -> None:
    """Register SQLAlchemy event listeners for auto-sync."""
    for model in SYNCED_MODELS:
        event.listen(model, "after_insert", _on_model_change)
        event.listen(model, "after_update", _on_model_change)
        event.listen(model, "after_delete", _on_model_change)

    logger.info(f"Registered auto-sync events for {len(SYNCED_MODELS)} models")


def unregister_sync_events() -> None:
    """Remove SQLAlchemy event listeners (useful for testing)."""
    for model in SYNCED_MODELS:
        event.remove(model, "after_insert", _on_model_change)
        event.remove(model, "after_update", _on_model_change)
        event.remove(model, "after_delete", _on_model_change)
