# syntax=docker/dockerfile:1

ARG PYTHON_VERSION=3.14
ARG UV_VERSION=0.10.10

FROM ghcr.io/astral-sh/uv:${UV_VERSION} AS uv

# --- base: interpreter + uv ---------------------------------------------
FROM python:${PYTHON_VERSION}-slim AS base

ENV PYTHONUNBUFFERED=1 \
    UV_LINK_MODE=copy \
    UV_PYTHON_DOWNLOADS=0

COPY --from=uv /uv /uvx /usr/local/bin/

WORKDIR /app

# --- builder: production virtualenv -------------------------------------
FROM base AS builder

ENV UV_COMPILE_BYTECODE=1 \
    UV_CACHE_DIR=/root/.cache/uv

RUN --mount=type=cache,target=/root/.cache/uv \
    --mount=type=bind,source=uv.lock,target=uv.lock \
    --mount=type=bind,source=pyproject.toml,target=pyproject.toml \
    uv sync --frozen --no-dev --extra all --no-install-project

COPY pyproject.toml uv.lock README.md LICENSE ./
COPY src ./src

RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-dev --extra all --no-editable

# --- dev: toolchain for docker-compose.dev.yml and Dev Containers -------
FROM base AS dev

ARG USERNAME=dev
ARG USER_UID=1000
ARG USER_GID=1000

RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        curl git make \
        libpango-1.0-0 libpangoft2-1.0-0 libharfbuzz-subset0 \
        fonts-dejavu-core fonts-liberation \
    && rm -rf /var/lib/apt/lists/*

RUN groupadd --gid "${USER_GID}" "${USERNAME}" \
    && useradd --uid "${USER_UID}" --gid "${USER_GID}" \
        --create-home --shell /bin/bash "${USERNAME}" \
    && mkdir -p /app/.venv \
    && chown -R "${USERNAME}:${USERNAME}" /app

ENV UV_PROJECT_ENVIRONMENT=/app/.venv \
    PYTHONPYCACHEPREFIX=/app/.cache/pycache \
    PATH="/app/.venv/bin:${PATH}" \
    HOST=0.0.0.0 \
    PORT=8081

USER ${USERNAME}

EXPOSE 8081

CMD ["sh", "-c", "uv sync --frozen --all-groups && make dev"]

# --- prod: minimal runtime ----------------------------------------------
FROM python:${PYTHON_VERSION}-slim AS prod

RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        tini \
        libpango-1.0-0 libpangoft2-1.0-0 libharfbuzz-subset0 \
        fonts-dejavu-core fonts-liberation \
    && rm -rf /var/lib/apt/lists/* \
    && groupadd --system app \
    && useradd --system --gid app --home-dir /app app \
    && mkdir -p /app/files \
    && chown -R app:app /app

COPY --from=builder --chown=app:app /app/.venv /app/.venv

ENV PATH="/app/.venv/bin:${PATH}" \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    HOST=0.0.0.0 \
    PORT=8081

WORKDIR /app
USER app

EXPOSE 8081

HEALTHCHECK --interval=30s --timeout=3s --start-period=5s --retries=3 \
    CMD ["python", "-c", "import os, urllib.request; urllib.request.urlopen(f\"http://127.0.0.1:{os.environ['PORT']}/ping\", timeout=2)"]

ENTRYPOINT ["/usr/bin/tini", "--"]
CMD ["jcpy"]
