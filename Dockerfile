# syntax=docker/dockerfile:1

FROM python:3.13-slim-bookworm

# uv desde su imagen oficial, con version pinneada (nunca :latest en un build).
COPY --from=ghcr.io/astral-sh/uv:0.12.5 /uv /uvx /bin/

ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PROJECT_ENVIRONMENT=/opt/venv \
    PATH="/opt/venv/bin:${PATH}" \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1

# curl: lo usa el healthcheck del contenedor.
RUN apt-get update \
 && apt-get install -y --no-install-recommends curl \
 && rm -rf /var/lib/apt/lists/*

WORKDIR /srv

# --- Capa 1: dependencias ---
# Se invalida SOLO si cambian pyproject.toml o uv.lock. El cache mount hace que
# reinstalar sea casi instantaneo aun cuando se invalida.
COPY pyproject.toml uv.lock ./
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-dev

# --- Capa 2: codigo ---
# Cambia en cada edicion, pero no vuelve a instalar dependencias.
COPY app ./app

# Nunca root.
RUN useradd --system --create-home --uid 10001 app && chown -R app:app /srv
USER app

EXPOSE 8000
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
