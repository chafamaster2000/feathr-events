# syntax=docker/dockerfile:1

FROM python:3.13-slim-bookworm

# uv from its official image, pinned (never :latest in a build).
COPY --from=ghcr.io/astral-sh/uv:0.12.5 /uv /uvx /bin/

ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PROJECT_ENVIRONMENT=/opt/venv \
    PATH="/opt/venv/bin:${PATH}" \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1

# curl: used by the container healthcheck.
RUN apt-get update \
 && apt-get install -y --no-install-recommends curl \
 && rm -rf /var/lib/apt/lists/*

WORKDIR /srv

# --- Layer 1: dependencies ---
# Invalidated ONLY when pyproject.toml or uv.lock change. The cache mount makes
# reinstalling nearly instant even when it is.
COPY pyproject.toml uv.lock ./
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-dev

# --- Layer 2: source ---
# Changes on every edit, but does not reinstall dependencies.
COPY app ./app

# Never root.
RUN useradd --system --create-home --uid 10001 app && chown -R app:app /srv
USER app

EXPOSE 8000
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
