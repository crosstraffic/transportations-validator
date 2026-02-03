# Transportation Validator

[![Tests](https://github.com/crosstraffic/transportations-validator/actions/workflows/test.yml/badge.svg)](https://github.com/crosstraffic/transportations-validator/actions/workflows/test.yml)
[![Docker Build](https://github.com/crosstraffic/transportations-validator/actions/workflows/docker.yml/badge.svg)](https://github.com/crosstraffic/transportations-validator/actions/workflows/docker.yml)
[![License](https://img.shields.io/badge/License-Apache_2.0-blue.svg)](https://opensource.org/licenses/Apache-2.0)

A Python project that validates ML-generated roads, LLM responses, and software outputs against a knowledge graph of transportation design rules.

## Architecture

```
PostgreSQL (source of truth) → Neo4j (graph queries) → Validation Engine → REST API
```

## Prerequisites

- Python 3.11+
- Docker and Docker Compose
- [uv](https://github.com/astral-sh/uv) (recommended) or pip

## Quick Start

```bash
# Clone and setup
git clone <repo>
cd transportations-validator
cp .env.example .env

# Create virtual environment and install
uv venv
source .venv/bin/activate   # Linux/macOS/WSL
# .venv\Scripts\activate    # Windows PowerShell

# Install dependencies
make install                # uses uv (fast)
# make install-pip          # fallback: uses pip

# Start databases (PostgreSQL + Neo4j)
make db

# Run migrations and seed data
make migrate
make seed

# Sync data to Neo4j (required for graph visualization)
make sync

# Start the server
make serve
```

**URLs available after startup:**

| URL | Description |
|-----|-------------|
| http://localhost:8000 | API root |
| http://localhost:8000/docs | Swagger UI (interactive API docs) |
| http://localhost:8000/static/graph.html | **Knowledge Graph Visualization** |
| http://localhost:7474 | Neo4j Browser (Cypher queries) |

## Full Setup (First Time)

Run these commands in order:

```bash
# 1. Start Docker containers (PostgreSQL + Neo4j)
make db

# 2. Wait for databases to be ready, then run migrations
make migrate

# 3. Load seed data into PostgreSQL
make seed

# 4. Sync data from PostgreSQL to Neo4j
make sync

# 5. Start the FastAPI server
make serve

# 6. Open the graph visualization
xdg-open http://localhost:8000/static/graph.html
```

**Important:** The graph visualization (`/static/graph.html`) requires Neo4j to be running. If you see a 500 error, make sure you ran `make db` first.

## Make Commands

### Database & Setup

| Command | Description |
|---------|-------------|
| `make db` | Start Postgres + Neo4j containers |
| `make db-stop` | Stop database containers |
| `make install` | Install project + dev deps with uv |
| `make install-pip` | Install with pip (fallback) |
| `make migrate` | Run alembic migrations |
| `make seed` | Load seed data |
| `make sync` | Sync PostgreSQL to Neo4j |
| `make setup-data` | Full data setup (migrate + seed + sync) |
| `make serve` | Start dev server on :8000 |
| `make dev` | Full setup: db + migrate + serve |
| `make reset` | Reset databases and reseed |

### Testing & Demos

| Command | Description |
|---------|-------------|
| `make test` | Run all tests |
| `make test-cov` | Run tests with coverage report |
| `make test-firewall` | Run semantic firewall tests only |
| `make demo-firewall` | Run semantic firewall Python demo |
| `make demo-firewall-api` | Run API demo (requires server running) |
| `make demo-opendrive` | Run detection-to-OpenDRIVE pipeline demo |

### Code Quality & Docker

| Command | Description |
|---------|-------------|
| `make lint` | Lint code with ruff |
| `make fmt` | Format code with ruff |
| `make typecheck` | Type check with mypy |
| `make pre-commit` | Install pre-commit hooks |
| `make clean` | Remove cache files |
| `make docker-up` | Run full stack in Docker |
| `make docker-down` | Stop full Docker stack |

## Daily Workflow

```bash
# Activate virtual environment
source .venv/bin/activate

# Start databases (if not running)
make db

# Start the server
make serve

# Access the visualization
# http://localhost:8000/static/graph.html
```

**Troubleshooting:**

| Error | Solution |
|-------|----------|
| `ServiceUnavailable: Couldn't connect to localhost:7687` | Run `make db` to start Neo4j |
| `500 Internal Server Error` on graph page | Neo4j not running or not synced - run `make db && make sync` |
| Graph shows "No nodes found" | Run `make sync` to sync data to Neo4j |
| `Connection refused` on port 5432 | Run `make db` to start PostgreSQL |

## Running in Docker (Full Stack)

```bash
# Start everything (API + Postgres + Neo4j)
make docker-up

# Stop everything
make docker-down
```

## API Endpoints

### Validation

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/api/v1/validate/` | POST | Validate structured data (auto-detect source) |
| `/api/v1/validate/text` | POST | Validate LLM text output |
| `/api/v1/validate/firewall` | POST | **Semantic Firewall** - Validate against 5 HCM constraints |
| `/api/v1/validate/parameters/{facility}` | GET | Get validatable parameters |
| `/api/v1/sync/trigger` | POST | Trigger PG→Neo4j sync |

### Parameters & Rules

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/api/v1/parameters/` | GET | List all parameters |
| `/api/v1/rules/` | GET | List all rules |

### Knowledge Graph

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/api/v1/graph/visualize/full` | GET | **Full graph** - All nodes and relationships |
| `/api/v1/graph/visualize?center={field}&depth=2` | GET | Centered graph view |
| `/api/v1/graph/parameters/{field}/related` | GET | Find related parameters |
| `/api/v1/graph/rules/{id}/citations` | GET | Get rule citations |
| `/api/v1/graph/conflicts` | GET | Find conflicting rules |
| `/api/v1/graph/impact?parameter={field}` | GET | Analyze parameter change impact |
| `/api/v1/graph/suggest?params=lw,ffs` | GET | Suggest related checks |

## Usage Examples

### Validate BasicFreeways Output

```bash
curl -X POST http://localhost:8000/api/v1/validate/ \
  -H "Content-Type: application/json" \
  -d '{
    "data": {
      "bffs": 65.0,
      "lw": 12.0,
      "lc_r": 6,
      "lc_l": 4,
      "phf": 0.92,
      "speed_limit": 65
    }
  }'
```

### Validate LLM Response

```bash
curl -X POST http://localhost:8000/api/v1/validate/text \
  -H "Content-Type: application/json" \
  -d '{
    "text": "The lane width should be 11 feet with a speed limit of 55 mph and a 3% grade."
  }'
```

### Semantic Firewall (Two-Lane Highway)

The Semantic Firewall validates inputs against 5 HCM/AASHTO constraints before they reach the computational core:

| ID | Parameter | Constraint | Source |
|----|-----------|------------|--------|
| SF-001 | lane_width | 9-12 ft | HCM Exhibit 15-8 |
| SF-002 | shoulder_width | 0-8 ft | HCM Exhibit 15-8 |
| SF-003 | hor_class | 0-5 | HCM Exhibit 15-22 |
| SF-004 | passing_type | 0, 1, 2 | HCM Chapter 15.3 |
| SF-005 | design_rad + speed_limit | Radius ≥ min for speed | Green Book Table 3-7 |

```bash
# Valid input - all constraints pass
curl -X POST http://localhost:8000/api/v1/validate/firewall \
  -H "Content-Type: application/json" \
  -d '{
    "lane_width": 11.0,
    "shoulder_width": 6.0,
    "hor_class": 2,
    "passing_type": 1,
    "design_rad": 1000.0,
    "speed_limit": 55
  }'

# Invalid input - catches violations
curl -X POST http://localhost:8000/api/v1/validate/firewall \
  -H "Content-Type: application/json" \
  -d '{
    "lane_width": 14.0,
    "design_rad": 500.0,
    "speed_limit": 55
  }'
```

Run the demos:
```bash
make demo-firewall       # Python demo (no server needed)
make demo-firewall-api   # API demo (requires: make serve)
```

## Viewing the Knowledge Graph

### Option 1: Neo4j Browser (Interactive)

Access the Neo4j browser directly for Cypher queries and visual exploration:

```bash
# Start databases
make db

# Open browser
open http://localhost:7474    # macOS
xdg-open http://localhost:7474  # Linux
```

**Login credentials** (from `.env`):
- Username: `neo4j`
- Password: `password` (or your configured password)

**Useful Cypher queries:**

```cypher
-- View all nodes and relationships
MATCH (n)-[r]->(m) RETURN n, r, m LIMIT 100

-- View all parameters
MATCH (p:Parameter) RETURN p

-- View all design rules
MATCH (r:DesignRule) RETURN r

-- View parameter with its rules
MATCH (p:Parameter {rust_field: 'lane_width'})<-[:VALIDATES]-(r:DesignRule)
RETURN p, r

-- View full graph structure
CALL db.schema.visualization()
```

### Option 2: REST API (Programmatic)

```bash
# Get full graph (D3-compatible JSON)
curl http://localhost:8000/api/v1/graph/visualize/full | jq .

# Get graph centered on a parameter
curl "http://localhost:8000/api/v1/graph/visualize?center=lane_width&depth=2" | jq .

# Find related parameters
curl http://localhost:8000/api/v1/graph/parameters/lane_width/related | jq .

# Analyze parameter impact
curl "http://localhost:8000/api/v1/graph/impact?parameter=lane_width" | jq .

# Find conflicting rules
curl http://localhost:8000/api/v1/graph/conflicts | jq .

# Get suggestions based on checked parameters
curl "http://localhost:8000/api/v1/graph/suggest?params=lane_width,ffs" | jq .
```

### Option 3: Sync Data to Neo4j

If Neo4j is empty, sync from PostgreSQL:

```bash
# Via API
curl -X POST http://localhost:8000/api/v1/sync/trigger

# Via make
make sync
```

## Project Structure

```
transportations-validator/
├── pyproject.toml              # Project config and dependencies
├── Makefile                    # Development commands
├── docker-compose.yaml         # Database services
├── .env.example                # Environment template
├── alembic.ini                 # Migration config
├── src/transportations_validator/
│   ├── main.py                 # FastAPI entry
│   ├── config.py               # Settings
│   ├── models/                 # Pydantic + SQLAlchemy models
│   ├── db/
│   │   ├── postgres/           # PostgreSQL connection and repos
│   │   └── neo4j/              # Neo4j connection and sync
│   ├── extractors/             # Parameter extractors
│   ├── validators/             # Validation engine
│   └── api/v1/                 # API endpoints
├── migrations/                 # Alembic migrations
├── scripts/                    # Utility scripts
├── seed_data/                  # Seed data files
└── tests/                      # Test suite
```

## Supported Facility Types

- **BasicFreeway**: Basic freeway segments (HCM Chapter 12)
- **TwoLaneHighway**: Two-lane highway analysis (HCM Chapter 15)
- **MultilaneHighway**: Multilane highway analysis
- **UrbanStreet**: Urban street segments

## Testing

```bash
make test                       # Run all tests
make test-cov                   # Run with coverage report

# Run specific test suites
pytest tests/unit/ -v           # Unit tests
pytest tests/integration/ -v    # Integration tests (requires Docker)
pytest tests/api/ -v            # API tests
```

## Development

### Code Quality

```bash
make lint       # Check for issues
make fmt        # Auto-format code
make typecheck  # Run type checker
```

### Adding New Parameters

1. Add parameter definition to `seed_data/parameters/{facility}.json`
2. Add corresponding rules to `seed_data/rules/hcm_rules.json`
3. Run seed data loader: `make seed`
4. Trigger Neo4j sync: `curl -X POST http://localhost:8000/api/v1/sync/trigger`

### Adding New Extractors

1. Create new extractor class in `src/transportations_validator/extractors/`
2. Inherit from `BaseExtractor`
3. Implement `can_extract()` and `extract()` methods
4. Register in `ValidationEngine.__init__`

## uv Cheatsheet

| Command | Description |
|---------|-------------|
| `uv venv` | Create virtual environment |
| `uv pip install -e ".[dev]"` | Install project + dev deps |
| `uv pip install <package>` | Add a package |
| `uv pip freeze > requirements.txt` | Export deps |
| `uv pip sync requirements.txt` | Sync from lockfile |

## Documentation

| Document | Description |
|----------|-------------|
| [docs/setup.md](docs/setup.md) | Detailed setup instructions |
| [docs/api.md](docs/api.md) | Full API reference |
| [docs/architecture.md](docs/architecture.md) | System architecture overview |

## License

Apache-2.0 - See [LICENSE](LICENSE) for details.
