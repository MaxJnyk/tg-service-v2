FROM python:3.12-slim AS base

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

# Install uv for fast dependency resolution
RUN pip install --no-cache-dir uv

# Copy dependency files first for caching
COPY pyproject.toml ./

# Install dependencies
RUN uv pip install --system --no-cache .

# Copy source code
COPY src/ ./src/
COPY migrations/ ./migrations/
COPY alembic.ini ./

CMD ["python", "-m", "src.main"]
