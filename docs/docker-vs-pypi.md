# Docker vs PyPI: Installation Comparison

This document explains the key differences between installing via Docker and via PyPI (`pip install`).

## Overview

The Docker image and the PyPI package share the same source code and API, but they differ in what is bundled and how the application is initialized.

| Aspect | Docker | PyPI |
|--------|--------|------|
| Install command | `docker compose up` / `make docker-up` | `pip install transportations-validator` |
| PostgreSQL & Neo4j | Included as services | Must be provisioned separately |
| Database migrations | Auto-run on startup | Manual: `alembic upgrade head` |
| Seed data (rules & parameters) | Auto-loaded on startup | **Not included in package** |
| Validation rules available | ~1000+ rules from 18 rule files | **None** (empty database) |
| Semantic Firewall (hardcoded) | 5 constraints | 5 constraints |
| CLI entry point | `entrypoint.sh` | `transportations-validator` |

## Validation Differences

This is the most important distinction. **The two installation methods do not validate the same things out of the box.**

### Docker

The Docker `entrypoint.sh` automatically runs:

```bash
alembic upgrade head              # Create database tables
python -m scripts.load_seed_data  # Load all rules and parameters
```

This loads **1000+ validation rules** from `seed_data/`, covering:

- HCM (Highway Capacity Manual) rules
- AASHTO Green Book design rules
- ADA accessibility rules
- MUTCD signage/marking rules
- OpenDRIVE property rules
- Parameter relationships and traffic flow relationships

After startup, all validation endpoints (`/validate/`, `/validate/text`, `/validate/parameters/{facility}`) work with the full rule set.

### PyPI

The PyPI wheel only includes `src/transportations_validator/`. The `seed_data/` directory and `scripts/` are **not packaged**.

This means:

- `POST /validate/` will pass all input because there are no rules in the database to check against
- `GET /validate/parameters/{facility}` returns empty results
- The knowledge graph (`/graph/`) is empty

**Only the Semantic Firewall endpoint (`POST /validate/firewall`) works fully**, because its 5 constraints are hardcoded in the application code:

| ID | Constraint | Range | Source |
|----|-----------|-------|--------|
| SF-001 | Lane Width | 9-12 ft | HCM Exhibit 15-8 |
| SF-002 | Shoulder Width | 0-8 ft | HCM |
| SF-003 | Horizontal Class | 0-5 | HCM Exhibit 15-22 |
| SF-004 | Passing Type | 0, 1, or 2 | HCM Chapter 15.3 |
| SF-005 | Design Radius vs Speed Limit | Formula-based | Green Book Table 3-7 |

## Making PyPI Feature-Complete

If you install via PyPI and want the full validation rule set, you need to load the seed data manually:

```bash
# Clone the repository to get seed data and scripts
git clone https://github.com/crosstraffic/transportations-validator.git
cd transportations-validator

# Ensure databases are running and configured (see setup.md)

# Run migrations
alembic upgrade head

# Load seed data
python -m scripts.load_seed_data

# Optionally sync to Neo4j for graph features
python -m scripts.sync_neo4j
```

## Configuration

Both versions use the same environment variables for configuration. See [setup.md](setup.md#environment-variables) for the full list.

The Docker version sets defaults in `docker-compose.yaml`. The PyPI version reads from environment variables or a `.env` file.

## When to Use Which

**Use Docker when:**
- You want a turnkey setup with no manual steps
- You are running locally for development or demos
- You don't have existing PostgreSQL/Neo4j instances

**Use PyPI when:**
- You are integrating the validator into an existing Python application
- You want to use managed or cloud-hosted databases
- You need a lighter installation without container overhead
- You only need the Semantic Firewall endpoint
