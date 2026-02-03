.PHONY: help db db-stop install install-pip migrate seed sync setup-data serve dev up test test-cov test-firewall lint fmt clean reset pre-commit demo-firewall demo-firewall-api demo-opendrive graph graph-pyvis graph-citespace

# Use uv to run commands in the virtual environment
# Try common uv locations if not in PATH
UV := $(shell which uv 2>/dev/null || echo "$(HOME)/.local/bin/uv")
RUN := $(UV) run

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
	@echo "  make up          - ALL-IN-ONE: db + migrate + seed + sync + serve"
	@echo "  make serve       - Start dev server :8000"
	@echo "  make dev         - Full setup (db + migrate + serve)"
	@echo ""
	@echo "Testing:"
	@echo "  make test        - Run all tests"
	@echo "  make test-cov    - Run tests with coverage"
	@echo "  make test-firewall - Run semantic firewall tests only"
	@echo ""
	@echo "Demos & Visualization:"
	@echo "  make demo-firewall     - Run semantic firewall Python demo"
	@echo "  make demo-firewall-api - Run API demo (requires server running)"
	@echo "  make demo-opendrive    - Run detection-to-OpenDRIVE pipeline demo"
	@echo "  make graph             - Open D3.js graph visualization in browser"
	@echo "  make graph-pyvis       - Generate PyVis interactive graph (requires db)"
	@echo "  make graph-citespace   - Generate CiteSpace-style PNG visualization"
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
	$(RUN) alembic upgrade head

# Load seed data into PostgreSQL
seed:
	$(RUN) python -m scripts.load_seed_data

# Sync PostgreSQL to Neo4j
sync:
	$(RUN) python -m scripts.sync_neo4j

# Full data setup: migrate + seed + sync
setup-data: migrate seed sync
	@echo "Data setup complete! PostgreSQL and Neo4j are ready."

# Start dev server
serve:
	$(RUN) uvicorn transportations_validator.main:app --reload --port 8000

# Full dev setup (legacy)
dev: db migrate serve

# ALL-IN-ONE: Start everything and open graph visualization
up:
	@echo "═══════════════════════════════════════════════════════════════════════════════"
	@echo "Starting CrossTraffic Validator (all-in-one)"
	@echo "═══════════════════════════════════════════════════════════════════════════════"
	@echo ""
	@echo "Step 1/5: Starting databases..."
	docker compose up -d postgres neo4j
	@echo "Waiting for databases to be ready..."
	@sleep 8
	@echo ""
	@echo "Step 2/5: Running migrations..."
	$(RUN) alembic upgrade head
	@echo ""
	@echo "Step 3/5: Loading seed data..."
	$(RUN) python -m scripts.load_seed_data
	@echo ""
	@echo "Step 4/5: Syncing to Neo4j..."
	$(RUN) python -m scripts.sync_neo4j
	@echo ""
	@echo "Step 5/5: Starting server..."
	@echo ""
	@echo "═══════════════════════════════════════════════════════════════════════════════"
	@echo "Ready! Open in browser:"
	@echo "  API Docs:    http://localhost:8000/docs"
	@echo "  Graph:       http://localhost:8000/static/graph.html"
	@echo "  Neo4j:       http://localhost:7474"
	@echo "═══════════════════════════════════════════════════════════════════════════════"
	$(RUN) uvicorn transportations_validator.main:app --reload --port 8000

# Run tests
test:
	$(RUN) pytest tests/ -v

# Run tests with coverage
test-cov:
	$(RUN) pytest tests/ -v --cov=src --cov-report=html

# Run semantic firewall tests only
test-firewall:
	$(RUN) pytest tests/test_semantic_firewall_api.py -v

# ═══════════════════════════════════════════════════════════════════════════════
# Semantic Firewall Demos (Paper Section 2.2 & 4.2)
# ═══════════════════════════════════════════════════════════════════════════════

# Run semantic firewall Python demo
demo-firewall:
	@echo "═══════════════════════════════════════════════════════════════════════════════"
	@echo "Running Semantic Firewall Demo (Paper Section 2.2)"
	@echo "═══════════════════════════════════════════════════════════════════════════════"
	$(RUN) python examples/semantic_firewall_demo.py

# Run detection-to-OpenDRIVE pipeline demo
demo-opendrive:
	@echo "═══════════════════════════════════════════════════════════════════════════════"
	@echo "Running Detection to OpenDRIVE Pipeline Demo (Paper Section 4.3)"
	@echo "═══════════════════════════════════════════════════════════════════════════════"
	$(RUN) python examples/detection_to_opendrive_demo.py

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

# Open D3.js knowledge graph visualization in browser
graph:
	@echo "═══════════════════════════════════════════════════════════════════════════════"
	@echo "Opening D3.js Knowledge Graph Visualization"
	@echo ""
	@echo "Prerequisites:"
	@echo "  1. make db      - Start Neo4j database"
	@echo "  2. make sync    - Sync data to Neo4j"
	@echo "  3. make serve   - Start FastAPI server (in another terminal)"
	@echo "═══════════════════════════════════════════════════════════════════════════════"
	@if command -v xdg-open >/dev/null 2>&1; then \
		xdg-open http://localhost:8000/static/graph.html; \
	elif command -v open >/dev/null 2>&1; then \
		open http://localhost:8000/static/graph.html; \
	else \
		echo "Open in browser: http://localhost:8000/static/graph.html"; \
	fi

# Generate PyVis interactive network graph
graph-pyvis:
	@echo "═══════════════════════════════════════════════════════════════════════════════"
	@echo "Generating PyVis Knowledge Graph Visualization"
	@echo ""
	@echo "Prerequisites: make db (PostgreSQL must be running)"
	@echo "═══════════════════════════════════════════════════════════════════════════════"
	$(RUN) python -m scripts.generate_graph_viz --open

# Generate CiteSpace-style publication-quality visualization
graph-citespace:
	@echo "═══════════════════════════════════════════════════════════════════════════════"
	@echo "Generating CiteSpace-style Knowledge Distribution Visualization"
	@echo ""
	@echo "Prerequisites: make db (PostgreSQL must be running)"
	@echo "Output: static/knowledge_citespace.png, static/knowledge_clustered.png"
	@echo "═══════════════════════════════════════════════════════════════════════════════"
	$(RUN) python -m scripts.generate_citespace_viz --style both --open

# Lint
lint:
	$(RUN) ruff check src/ tests/

# Format
fmt:
	$(RUN) ruff format src/ tests/

# Type check
typecheck:
	$(RUN) mypy src/

# Install pre-commit hooks
pre-commit:
	$(RUN) pip install pre-commit
	$(RUN) pre-commit install

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
