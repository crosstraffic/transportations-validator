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

# Start databases, run migrations, seed data, and serve
make db
make migrate
make seed
make serve
```

API available at http://localhost:8000

## Make Commands

| Command | Description |
|---------|-------------|
| `make db` | Start Postgres + Neo4j containers |
| `make db-stop` | Stop database containers |
| `make install` | Install project + dev deps with uv |
| `make install-pip` | Install with pip (fallback) |
| `make migrate` | Run alembic migrations |
| `make seed` | Load seed data |
| `make serve` | Start dev server on :8000 |
| `make dev` | Full setup: db + migrate + serve |
| `make test` | Run tests |
| `make test-cov` | Run tests with coverage report |
| `make lint` | Lint code with ruff |
| `make fmt` | Format code with ruff |
| `make typecheck` | Type check with mypy |
| `make pre-commit` | Install pre-commit hooks |
| `make clean` | Remove cache files |
| `make reset` | Reset databases and reseed |
| `make docker-up` | Run full stack in Docker |
| `make docker-down` | Stop full Docker stack |

## Daily Workflow

```bash
source .venv/bin/activate
make db         # if databases stopped
make serve
```

## Running in Docker (Full Stack)

```bash
# Start everything (API + Postgres + Neo4j)
make docker-up

# Stop everything
make docker-down
```

## API Endpoints

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/api/v1/validate/` | POST | Validate structured data (auto-detect source) |
| `/api/v1/validate/text` | POST | Validate LLM text output |
| `/api/v1/validate/parameters/{facility}` | GET | Get validatable parameters |
| `/api/v1/sync/trigger` | POST | Trigger PG→Neo4j sync |
| `/api/v1/parameters/` | GET | List all parameters |
| `/api/v1/rules/` | GET | List all rules |

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
| [docs/plans/llm-integration.md](docs/plans/llm-integration.md) | Future LLM integration plan |

## License

Apache-2.0 - See [LICENSE](LICENSE) for details.
