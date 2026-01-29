# Setup Guide

## Prerequisites

- Docker & Docker Compose
- Python 3.11+ (for local development)
- Make (optional, for convenience commands)

## Quick Start (Docker)

```bash
# Start all services (PostgreSQL, Neo4j, API)
make docker-up

# Check status
docker ps

# View logs
docker logs -f transportations-api
```

Services will be available at:
- **API**: http://localhost:8000
- **API Docs**: http://localhost:8000/docs
- **Neo4j Browser**: http://localhost:7474 (user: neo4j, password: password)
- **PostgreSQL**: localhost:5432 (user: postgres, password: postgres)

## Stop Services

```bash
# Stop containers (keep data)
make docker-down

# Stop and remove all data
docker-compose down -v
```

## Local Development (Without Docker)

### 1. Create Virtual Environment

```bash
python -m venv .venv
source .venv/bin/activate  # Linux/Mac
# or
.venv\Scripts\activate     # Windows
```

### 2. Install Dependencies

```bash
pip install -e ".[dev]"
```

### 3. Start Databases

```bash
# PostgreSQL
docker run -d --name postgres \
  -e POSTGRES_PASSWORD=postgres \
  -e POSTGRES_DB=transportations \
  -p 5432:5432 \
  postgres:15-alpine

# Neo4j
docker run -d --name neo4j \
  -e NEO4J_AUTH=neo4j/password \
  -p 7474:7474 -p 7687:7687 \
  neo4j:5-community
```

### 4. Configure Environment

```bash
cp .env.example .env
# Edit .env with your settings
```

### 5. Run Migrations

```bash
alembic upgrade head
```

### 6. Load Seed Data

```bash
python -m scripts.load_seed_data
```

### 7. Start Server

```bash
uvicorn transportations_validator.main:app --reload
```

## Environment Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `DATABASE_URL` | `postgresql+asyncpg://postgres:postgres@localhost:5432/transportations` | PostgreSQL connection |
| `NEO4J_URI` | `bolt://localhost:7687` | Neo4j connection |
| `NEO4J_USER` | `neo4j` | Neo4j username |
| `NEO4J_PASSWORD` | `password` | Neo4j password |
| `DEBUG` | `false` | Enable debug mode |

## Makefile Commands

```bash
make docker-up      # Start all services
make docker-down    # Stop services
make docker-logs    # View API logs
make test           # Run tests
make lint           # Run linter
make format         # Format code
```

## Troubleshooting

### Container exits immediately

Check logs:
```bash
docker logs transportations-api
```

Common issues:
- **Line ending issues (Windows)**: The Dockerfile auto-fixes CRLF → LF
- **Database not ready**: Containers have health checks, API waits for DBs

### Connection refused

Ensure containers are running:
```bash
docker ps
```

### Reset everything

```bash
docker-compose down -v
make docker-up
```
