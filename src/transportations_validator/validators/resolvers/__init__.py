"""Validation resolvers.

The resolver classes are imported lazily (PEP 562) so that importing this package — or the dependency-free ``priorities`` module — does not pull in the DB-backed resolvers (and sqlalchemy) at import time. This keeps the in-process reasoning layer (which only needs ``priorities.DEFAULT_PRIORITIES``) database-free.
"""

__all__ = ["ConditionResolver", "JurisdictionResolver"]


def __getattr__(name: str):
    if name == "ConditionResolver":
        from transportations_validator.validators.resolvers.condition import (
            ConditionResolver,
        )

        return ConditionResolver
    if name == "JurisdictionResolver":
        from transportations_validator.validators.resolvers.jurisdiction import (
            JurisdictionResolver,
        )

        return JurisdictionResolver
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
