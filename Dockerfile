# syntax=docker/dockerfile:1

# Two stages, for one reason: uv is a build tool and was 57.1MB of the runtime image.
# It is not needed to *run* anything - the Makefile's `uv run` targets all execute on the
# host, and the container's command is uvicorn from the virtualenv - so its only effect in
# the image that ships was weight, plus a package installer sitting in a service container
# for anyone who gets a shell in it.
#
# The virtualenv is built at the same absolute path in both stages, which is what makes it
# copyable: the shebangs and `pyvenv.cfg` inside it are absolute, so a venv built at one
# path and copied to another is broken in ways that only appear at runtime.

# --- build: uv lives here and never reaches the image that runs ---
FROM python:3.13-slim-bookworm AS build

COPY --from=ghcr.io/astral-sh/uv:0.12.5 /uv /bin/uv

ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PROJECT_ENVIRONMENT=/opt/venv

WORKDIR /srv
COPY pyproject.toml uv.lock ./
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-dev

# --- runtime ---
FROM python:3.13-slim-bookworm

ENV PATH="/opt/venv/bin:${PATH}" \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1

# curl, for the container healthcheck. 6.06MB, and kept deliberately: the same binary is
# what makes a container debuggable from the inside when something is wrong with it, and
# `python -c urllib...` would save the layer at the cost of that.
RUN apt-get update \
 && apt-get install -y --no-install-recommends curl \
 && rm -rf /var/lib/apt/lists/*

COPY --from=build /opt/venv /opt/venv

WORKDIR /srv
COPY app ./app

# Never root. No home directory: a service account has no use for one.
RUN useradd --system --uid 10001 app && chown -R app:app /srv
USER app

EXPOSE 8000
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
