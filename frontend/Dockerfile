# syntax=docker/dockerfile:1.7

# Base images are pinned by digest so every build of the same source is identical.
ARG NODE_IMAGE=node:22-alpine@sha256:0a7108bf6c7bf5de370ffb1a3ed6be93d405b43ff159f681a8d18c0e2bc2e402
ARG NGINX_IMAGE=nginxinc/nginx-unprivileged:1.29-alpine@sha256:0c79d56aee561a1d81c63f00eee5fb5fe29279560cdc55e91425133104c7fbe6

FROM ${NODE_IMAGE} AS deps
WORKDIR /app
COPY package.json package-lock.json ./
RUN --mount=type=cache,target=/root/.npm npm ci --no-audit --no-fund

FROM deps AS build
COPY . .
RUN npm run build

# Build metadata comes last so changing it never invalidates the cached build above.
ARG VERSION=0.0.0-local
ARG CONTENT_HASH=local
ARG GIT_SHA=unknown
ARG BUILD_TIME=unknown
RUN printf '{"version":"%s","content_hash":"%s","git_sha":"%s","built_at":"%s"}\n' \
      "$VERSION" "$CONTENT_HASH" "$GIT_SHA" "$BUILD_TIME" > dist/version.json

FROM ${NGINX_IMAGE} AS runtime
ARG VERSION=0.0.0-local
ARG CONTENT_HASH=local
ARG GIT_SHA=unknown
ARG BUILD_TIME=unknown
LABEL org.opencontainers.image.title="quantsim-frontend" \
      org.opencontainers.image.source="https://github.com/Ali-Mazhar05/QuantSim-FYP" \
      org.opencontainers.image.version="${VERSION}" \
      org.opencontainers.image.revision="${GIT_SHA}" \
      org.opencontainers.image.created="${BUILD_TIME}" \
      io.quantsim.content-hash="${CONTENT_HASH}"

COPY nginx.conf /etc/nginx/conf.d/default.conf
COPY --from=build /app/dist /usr/share/nginx/html

EXPOSE 8080
HEALTHCHECK --interval=10s --timeout=3s --start-period=5s --retries=3 \
  CMD wget -q -O /dev/null http://127.0.0.1:8080/healthz || exit 1
