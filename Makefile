.PHONY: help db db-stop install install-pip migrate seed sync setup-data serve dev test test-cov test-firewall lint fmt clean reset pre-commit demo-firewall demo-firewall-api demo-opendrive

# Show available commands
help:
	@echo "Available commands:"
	@echo ""
	@echo "Database:"
	@echo "  make db          - Start Postgres + Neo4j"
	@echo "  make db-stop     - Stop databases"
	@echo "  make reset       - Reset databases and reseed"
	@echo ""
	@echo "Setup:"
	@echo "  make install     - Install with uv"
	@echo "  make install-pip - Install with pip"
	@echo "  make migrate     - Run alembic migrations"
	@echo "  make seed        - Load seed data into PostgreSQL"
	@echo "  make sync        - Sync PostgreSQL to Neo4j"
	@echo "  make setup-data  - Full data setup (migrate + seed + sync)"
	@echo ""
	@echo "Development:"
	@echo "  make serve       - Start dev server :8000"
	@echo "  make dev         - Full setup (db + migrate + serve)"
	@echo ""
	@echo "Testing:"
	@echo "  make test        - Run all tests"
	@echo "  make test-cov    - Run tests with coverage"
	@echo "  make test-firewall - Run semantic firewall tests only"
	@echo ""
	@echo "Demos (Paper Section 2.2 & 4.2):"
	@echo "  make demo-firewall     - Run semantic firewall Python demo"
	@echo "  make demo-firewall-api - Run API demo (requires server running)"
	@echo "  make demo-opendrive    - Run detection-to-OpenDRIVE pipeline demo"
	@echo ""
	@echo "Code Quality:"
	@echo "  make lint        - Lint code"
	@echo "  make fmt         - Format code"
	@echo "  make typecheck   - Type check with mypy"
	@echo "  make pre-commit  - Install pre-commit hooks"
	@echo "  make clean       - Remove cache files"
	@echo ""
	@echo "Docker:"
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

# Load seed data into PostgreSQL
seed:
	python -m scripts.load_seed_data

# Sync PostgreSQL to Neo4j
sync:
	python -m scripts.sync_neo4j

# Full data setup: migrate + seed + sync
setup-data: migrate seed sync
	@echo "Data setup complete! PostgreSQL and Neo4j are ready."

# Start dev server
serve:
	uvicorn transportations_validator.main:app --reload --port 8000

# Full dev setup
dev: db migrate serve

# Run tests
test:
	uv run python -m pytest tests/ -v

# Run tests with coverage
test-cov:
	uv run python -m pytest tests/ -v --cov=src --cov-report=html

# Run semantic firewall tests only
test-firewall:
	uv run python -m pytest tests/test_semantic_firewall_api.py -v

# ═══════════════════════════════════════════════════════════════════════════════
# Semantic Firewall Demos (Paper Section 2.2 & 4.2)
# ═══════════════════════════════════════════════════════════════════════════════

# Run semantic firewall Python demo
demo-firewall:
	@echo "═══════════════════════════════════════════════════════════════════════════════"
	@echo "Running Semantic Firewall Demo (Paper Section 2.2)"
	@echo "═══════════════════════════════════════════════════════════════════════════════"
	uv run python examples/semantic_firewall_demo.py

# Run detection-to-OpenDRIVE pipeline demo
demo-opendrive:
	@echo "═══════════════════════════════════════════════════════════════════════════════"
	@echo "Running Detection to OpenDRIVE Pipeline Demo (Paper Section 4.3)"
	@echo "═══════════════════════════════════════════════════════════════════════════════"
	uv run python examples/detection_to_opendrive_demo.py

# Run API demo (requires server running: make serve)
demo-firewall-api:
	@echo "═══════════════════════════════════════════════════════════════════════════════"
	@echo "Running Semantic Firewall API Demo"
	@echo "NOTE: Requires server running on localhost:8000 (use 'make serve' first)"
	@echo "═══════════════════════════════════════════════════════════════════════════════"
	@if command -v jq >/dev/null 2>&1; then \
		./examples/semantic_firewall_api_demo.sh; \
	else \
		echo "Error: jq is required. Install with: sudo apt install jq"; \
		exit 1; \
	fi

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

# Reset databases (full reset with Neo4j sync)
reset:
	docker compose down -v
	$(MAKE) db setup-data

# Run full stack in Docker
docker-up:
	docker compose up -d --build

# Stop full stack
docker-down:
	docker compose down
