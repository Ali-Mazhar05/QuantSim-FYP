# syntax=docker/dockerfile:1.7
# Market data service image. Built from the repository root (ci/components.conf) so the
# shared template in libs/ and the workspace lockfile are available.
#
# One image, several processes (docs/ingestion-plan.md section 3): the default command
# serves the API; the compose file starts the same image as
#   python -m qs_market worker | relay | scheduler
# and as `alembic upgrade head` for the one-shot market-migrate.

# Pinned Python 3.12 + uv image, used for both stages so every build is identical
ARG BASE_IMAGE=ghcr.io/astral-sh/uv:0.9-python3.12-bookworm-slim@sha256:e5b65587bce7de595f299855d7385fe7fca39b8a74baa261ba1b7147afa78e58

FROM ${BASE_IMAGE} AS build
ENV UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy UV_PYTHON_DOWNLOADS=never
WORKDIR /app
COPY pyproject.toml uv.lock ./
COPY libs ./libs
COPY services/market ./services/market
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-dev --no-editable --package qs-market

FROM ${BASE_IMAGE} AS runtime
ARG VERSION=0.0.0-local
ARG CONTENT_HASH=local
ARG GIT_SHA=unknown
ARG BUILD_TIME=unknown
LABEL org.opencontainers.image.title="quantsim-market" \
      org.opencontainers.image.source="https://github.com/Ali-Mazhar05/QuantSim-FYP" \
      org.opencontainers.image.version="${VERSION}" \
      org.opencontainers.image.revision="${GIT_SHA}" \
      org.opencontainers.image.created="${BUILD_TIME}" \
      io.quantsim.content-hash="${CONTENT_HASH}"

RUN groupadd --system --gid 10001 quantsim \
 && useradd --system --uid 10001 --gid quantsim --no-create-home quantsim

COPY --from=build /app/.venv /app/.venv
# Alembic reads its configuration and migrations from the service folder
COPY services/market/alembic.ini /app/service/alembic.ini
COPY services/market/migrations /app/service/migrations
# Recorded vendor responses for QS_VENDOR=fixture (DEV and smoke tests; no network)
COPY services/market/tests/fixtures /app/service/fixtures

ENV PATH="/app/.venv/bin:$PATH" \
    PYTHONUNBUFFERED=1 \
    QS_SERVICE_NAME=market \
    QS_VERSION=${VERSION} \
    QS_CONTENT_HASH=${CONTENT_HASH} \
    QS_FIXTURE_DIR=/app/service/fixtures
WORKDIR /app/service
USER quantsim

EXPOSE 8000
# Only meaningful for the API; the compose file disables it for worker, relay and scheduler
HEALTHCHECK --interval=10s --timeout=3s --start-period=10s --retries=3 \
  CMD ["python", "-c", "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8000/api/market/health', timeout=2).status == 200 else 1)"]

CMD ["uvicorn", "qs_market.main:create", "--factory", "--host", "0.0.0.0", "--port", "8000", "--proxy-headers"]
