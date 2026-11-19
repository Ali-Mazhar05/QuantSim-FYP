# syntax=docker/dockerfile:1.7
# Platform service image. Built from the repository root (ci/components.conf) so the
# shared template in libs/ and the workspace lockfile are available.

# Pinned Python 3.12 + uv image, used for both stages so every build is identical
ARG BASE_IMAGE=ghcr.io/astral-sh/uv:0.9-python3.12-bookworm-slim@sha256:e5b65587bce7de595f299855d7385fe7fca39b8a74baa261ba1b7147afa78e58

FROM ${BASE_IMAGE} AS build
ENV UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy UV_PYTHON_DOWNLOADS=never
WORKDIR /app
COPY pyproject.toml uv.lock ./
COPY libs ./libs
COPY services/platform ./services/platform
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-dev --no-editable --package qs-platform

FROM ${BASE_IMAGE} AS runtime
ARG VERSION=0.0.0-local
ARG CONTENT_HASH=local
ARG GIT_SHA=unknown
ARG BUILD_TIME=unknown
LABEL org.opencontainers.image.title="quantsim-platform" \
      org.opencontainers.image.source="https://github.com/Ali-Mazhar05/QuantSim-FYP" \
      org.opencontainers.image.version="${VERSION}" \
      org.opencontainers.image.revision="${GIT_SHA}" \
      org.opencontainers.image.created="${BUILD_TIME}" \
      io.quantsim.content-hash="${CONTENT_HASH}"

RUN groupadd --system --gid 10001 quantsim \
 && useradd --system --uid 10001 --gid quantsim --no-create-home quantsim

COPY --from=build /app/.venv /app/.venv
# Alembic reads its configuration and migrations from the service folder
COPY services/platform/alembic.ini /app/service/alembic.ini
COPY services/platform/migrations /app/service/migrations

ENV PATH="/app/.venv/bin:$PATH" \
    PYTHONUNBUFFERED=1 \
    QS_SERVICE_NAME=platform \
    QS_VERSION=${VERSION} \
    QS_CONTENT_HASH=${CONTENT_HASH}
WORKDIR /app/service
USER quantsim

EXPOSE 8000
HEALTHCHECK --interval=10s --timeout=3s --start-period=10s --retries=3 \
  CMD ["python", "-c", "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8000/api/platform/health', timeout=2).status == 200 else 1)"]

ENTRYPOINT ["qs-platform"]
CMD ["serve"]
