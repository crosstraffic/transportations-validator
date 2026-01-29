FROM python:3.11-slim

WORKDIR /app

# Install system dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    && rm -rf /var/lib/apt/lists/*

# Copy all source files first
COPY pyproject.toml README.md alembic.ini ./
COPY src/ src/
COPY migrations/ migrations/
COPY scripts/ scripts/
COPY seed_data/ seed_data/
COPY entrypoint.sh .

# Fix Windows line endings
RUN sed -i 's/\r$//' entrypoint.sh

# Install Python package
RUN pip install --no-cache-dir -e .

# Make entrypoint executable
RUN chmod +x entrypoint.sh

EXPOSE 8000

ENTRYPOINT ["./entrypoint.sh"]
