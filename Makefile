.PHONY: up ups down build lint lint-fix format quality test migrate cli-sessions cli-proxies

# Docker
up:
	docker compose up -d

ups:
	docker compose up

down:
	docker compose down -v

build:
	docker compose --progress=plain build

# Code quality
lint:
	uv run ruff check src/ tests/

lint-fix:
	uv run ruff check src/ tests/ --fix

format:
	uv run ruff format src/ tests/

format-check:
	uv run ruff format src/ tests/ --check

quality:
	uv run ruff check src/ tests/ --fix --unsafe-fixes
	uv run ruff format src/ tests/

# Tests
test:
	uv run pytest tests/ -v --tb=short

test-cov:
	uv run pytest tests/ -v --tb=short --cov=src --cov-report=term-missing

# Database
migrate:
	uv run alembic upgrade head

migrate-create:
	uv run alembic revision --autogenerate -m "$(MSG)"

# CLI
cli-sessions:
	uv run python -m src.cli.sessions $(CMD)

cli-proxies:
	uv run python -m src.cli.proxies $(CMD)
