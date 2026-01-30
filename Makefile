.PHONY: help db db-stop install install-pip migrate seed serve dev test test-cov lint fmt clean reset pre-commit

# Show available commands
help:
	@echo "Available commands:"
	@echo "  make db          - Start Postgres + Neo4j"
	@echo "  make db-stop     - Stop databases"
	@echo "  make install     - Install with uv"
	@echo "  make install-pip - Install with pip"
	@echo "  make migrate     - Run alembic migrations"
	@echo "  make seed        - Load seed data"
	@echo "  make serve       - Start dev server :8000"
	@echo "  make dev         - Full setup (db + migrate + serve)"
	@echo "  make test        - Run tests"
	@echo "  make test-cov    - Run tests with coverage"
	@echo "  make lint        - Lint code"
	@echo "  make fmt         - Format code"
	@echo "  make typecheck   - Type check with mypy"
	@echo "  make pre-commit  - Install pre-commit hooks"
	@echo "  make clean       - Remove cache files"
	@echo "  make reset       - Reset databases and reseed"
	@echo "  make docker-up   - Run full stack in Docker"
	@echo "  make docker-down - Stop Docker stack"

# Start databases
db:
	docker compose up -d postgres neo4j
	@echo "Waiting for databases..."
	@sleep 5
	@echo "Ready!"

# Stop databases
db-stop:
	docker compose down

# Install with uv (fast)
install:
	uv pip install -e ".[dev]"

# Install with pip (fallback)
install-pip:
	pip install -e ".[dev]"

# Run migrations
migrate:
	alembic upgrade head

# Load seed data
seed:
	python -m scripts.load_seed_data

# Start dev server
serve:
	uvicorn transportations_validator.main:app --reload --port 8000

# Full dev setup
dev: db migrate serve

# Run tests
test:
	pytest tests/ -v

# Run tests with coverage
test-cov:
	pytest tests/ -v --cov=src --cov-report=html

# Lint
lint:
	ruff check src/ tests/

# Format
fmt:
	ruff format src/ tests/

# Type check
typecheck:
	mypy src/

# Install pre-commit hooks
pre-commit:
	uv pip install pre-commit
	pre-commit install

# Clean
clean:
	find . -type d -name __pycache__ -exec rm -rf {} + 2>/dev/null || true
	rm -rf .pytest_cache htmlcov .coverage .mypy_cache

# Reset databases
reset:
	docker compose down -v
	$(MAKE) db migrate seed

# Run full stack in Docker
docker-up:
	docker compose up -d

# Stop full stack
docker-down:
	docker compose down
