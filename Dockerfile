FROM python:3.12-slim-bookworm AS builder

RUN apt-get update && apt-get install -y --no-install-recommends gcc build-essential && rm -rf /var/lib/apt/lists/*

ENV PATH="/venv/bin:$PATH" \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    UV_CACHE_DIR=/root/.cache/uv \
    UV_COMPILE_BYTECODE=1 \
    UV_FROZEN=1 \
    UV_LINK_MODE=copy \
    UV_NO_MANAGED_PYTHON=1 \
    UV_PROJECT_ENVIRONMENT=/venv \
    UV_PYTHON_DOWNLOADS=never \
    VIRTUAL_ENV=/venv

RUN pip install uv --quiet

WORKDIR /app
RUN --mount=type=cache,target=/root/.cache/uv \
    --mount=type=bind,source=uv.lock,target=uv.lock \
    --mount=type=bind,source=pyproject.toml,target=pyproject.toml \
    uv venv $VIRTUAL_ENV && \
    uv sync --no-install-project --no-editable

COPY src /app/src
COPY migrations /app/migrations
COPY alembic.ini /app/
COPY entrypoint.sh /app/entrypoint.sh

FROM python:3.12-slim

ENV PATH="/venv/bin:$PATH" \
    PYTHONPATH="/app"

WORKDIR /app

RUN groupadd -r appuser && useradd -r -g appuser -d /app -s /sbin/nologin appuser

COPY --link --from=builder /venv /venv
COPY --link --from=builder /app /app

RUN chmod +x /app/entrypoint.sh && chown -R appuser:appuser /app

USER appuser

CMD ["/app/entrypoint.sh"]
