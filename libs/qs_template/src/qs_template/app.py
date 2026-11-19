"""The application factory every service uses.

``create_app`` returns a FastAPI app that already has:

- every route under ``/api/<service>``, the prefix the gateway routes on
- ``GET /api/<service>/health``: liveness, with the build's version and content hash
  (the deploy smoke test checks the hash)
- ``GET /api/<service>/ready``: readiness, which runs the database ping and any
  service-specific checks and answers 503 while one fails
- a request id on every request (taken from ``X-Request-ID`` or generated), returned
  in the response, bound to every log line and included in error bodies
- one structured access-log line per request
- problem-details error responses
"""

import time
import uuid
from collections.abc import AsyncIterator, Awaitable, Callable, Sequence
from contextlib import asynccontextmanager
from dataclasses import dataclass
from typing import Any

import structlog
from fastapi import APIRouter, FastAPI, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from qs_template.config import ServiceSettings
from qs_template.db import Database
from qs_template.errors import install_error_handlers
from qs_template.logging import configure_logging, get_logger

REQUEST_ID_HEADER = "X-Request-ID"

log = get_logger(__name__)


@dataclass(frozen=True)
class ReadinessCheck:
    """A named dependency check; it raises when the dependency is unusable."""

    name: str
    check: Callable[[], Awaitable[None]]


Hook = Callable[[], Awaitable[None]]


def create_app(
    settings: ServiceSettings,
    *,
    database: Database | None = None,
    routers: Sequence[APIRouter] = (),
    readiness_checks: Sequence[ReadinessCheck] = (),
    on_startup: Sequence[Hook] = (),
    on_shutdown: Sequence[Hook] = (),
) -> FastAPI:
    configure_logging(
        service=settings.service_name,
        environment=settings.environment,
        level=settings.log_level,
    )
    prefix = settings.api_prefix
    checks = list(readiness_checks)
    if database is not None:
        checks.insert(0, ReadinessCheck("database", database.ping))

    @asynccontextmanager
    async def lifespan(_: FastAPI) -> AsyncIterator[None]:
        for hook in on_startup:
            await hook()
        log.info("service started", version=settings.version, content_hash=settings.content_hash)
        try:
            yield
        finally:
            for hook in on_shutdown:
                await hook()
            if database is not None:
                await database.close()
            log.info("service stopped")

    app = FastAPI(
        title=f"QuantSim {settings.service_name}",
        version=settings.version,
        openapi_url=f"{prefix}/openapi.json",
        docs_url=f"{prefix}/docs",
        redoc_url=None,
        lifespan=lifespan,
    )
    install_error_handlers(app)
    app.middleware("http")(_request_context)
    _allow_cross_site_calls(app, settings.cors_origin_list)

    @app.get(f"{prefix}/health", tags=["operations"])
    async def health() -> dict[str, str]:
        return {
            "status": "ok",
            "service": settings.service_name,
            "version": settings.version,
            "content_hash": settings.content_hash,
        }

    @app.get(f"{prefix}/ready", tags=["operations"])
    async def ready() -> JSONResponse:
        results: dict[str, str] = {}
        healthy = True
        for item in checks:
            try:
                await item.check()
                results[item.name] = "ok"
            except Exception as exc:
                healthy = False
                results[item.name] = "unavailable"
                log.warning("readiness check failed", check=item.name, error=str(exc))
        body: dict[str, Any] = {"status": "ready" if healthy else "not ready", "checks": results}
        return JSONResponse(body, status_code=200 if healthy else 503)

    for router in routers:
        app.include_router(router, prefix=prefix)

    return app


async def _request_context(
    request: Request, call_next: Callable[[Request], Awaitable[Response]]
) -> Response:
    request_id = request.headers.get(REQUEST_ID_HEADER) or uuid.uuid4().hex
    request.state.request_id = request_id
    structlog.contextvars.bind_contextvars(request_id=request_id)
    started = time.perf_counter()
    status = 500
    try:
        response = await call_next(request)
        status = response.status_code
        response.headers[REQUEST_ID_HEADER] = request_id
        return response
    finally:
        log.info(
            "request",
            method=request.method,
            path=request.url.path,
            status=status,
            duration_ms=round((time.perf_counter() - started) * 1000, 1),
        )
        structlog.contextvars.unbind_contextvars("request_id", "user_id")


def _allow_cross_site_calls(app: FastAPI, origins: list[str]) -> None:
    """Let the listed websites call the API from a browser (CORS), including Chrome's
    private-network check, so a public site may reach an API on localhost."""
    if not origins:
        return
    app.add_middleware(
        CORSMiddleware,
        allow_origins=origins,
        allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE"],
        allow_headers=["Authorization", "Content-Type"],
        allow_private_network=True,
        max_age=600,
    )
