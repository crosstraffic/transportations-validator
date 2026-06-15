"""Resolve the seed-data directory in both editable and installed layouts.

In an editable / source checkout the corpus lives at the repository root (``<repo>/seed_data``). In a built wheel it is force-included inside the package (``transportations_validator/seed_data`` — see ``[tool.hatch.build.targets.wheel.force-include]`` in pyproject). The reasoning loaders call :func:`seed_root` so they work in both cases without a running validator service.
"""

from __future__ import annotations

from pathlib import Path


def seed_root() -> Path:
    """Return the ``seed_data`` directory, preferring the dev tree, then the installed package copy."""
    here = Path(__file__).resolve()
    # this file is .../transportations_validator/seed_paths.py:
    #   parents[2] -> repo root (editable: <repo>/seed_data)
    #   parents[0] -> the package dir (installed wheel: transportations_validator/seed_data)
    for candidate in (here.parents[2] / "seed_data", here.parents[0] / "seed_data"):
        if candidate.exists():
            return candidate
    return here.parents[2] / "seed_data"
