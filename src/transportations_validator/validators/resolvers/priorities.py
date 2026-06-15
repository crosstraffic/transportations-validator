"""Jurisdiction priority constants — dependency-free.

Separated from ``jurisdiction.py`` (which pulls the DB-backed resolver stack) so the reasoning layer (``reconcile``) can use the priority ordering without importing sqlalchemy or the Postgres repositories. Keeping this module import-light is what lets the reasoning tools run in-process without a database.
"""

# Jurisdiction hierarchy (higher number = higher authority).
DEFAULT_PRIORITIES = {
    "federal": 100,
    "state": 50,
    "local": 25,
    "project": 10,
}
