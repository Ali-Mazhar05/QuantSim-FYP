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

import inspect
import time
import uuid
from collections.abc import AsyncIterator, Awaitable, Callable, Iterator, Sequence
from contextlib import asynccontextmanager
from dataclasses import dataclass
from typing import Any

import structlog
from fastapi import APIRouter, FastAPI, Request, Response
from fastapi.dependencies.models import Dependant
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.routing import iter_route_contexts

from qs_template.config import ServiceSettings
from qs_template.db import Database
from qs_template.errors import install_error_handlers
from qs_template.logging import configure_logging, get_logger

# The readiness body, for 200 and 503 alike
READINESS_SCHEMA: dict[str, Any] = {
    "type": "object",
    "required": ["status", "checks"],
    "properties": {
        "status": {"type": "string", "enum": ["ready", "not ready"]},
        "checks": {"type": "object", "additionalProperties": {"type": "string"}},
    },
}

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

    @app.get(
        f"{prefix}/ready",
        tags=["operations"],
        responses={
            200: {"description": "Every check passed"},
            503: {
                "description": "A check failed; the body names it",
                "content": {"application/json": {"schema": READINESS_SCHEMA}},
            },
        },
    )
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


def request_scoped_yield_dependencies(app: FastAPI) -> list[str]:
    """Every ``yield`` dependency of ``app``'s routes whose exit code runs after the response.

    FastAPI runs a yield dependency's code after ``yield`` once the response has been sent
    unless it is declared with ``Depends(..., scope="function")``. For a dependency that
    commits (``Database.session`` and anything built on ``Database.transaction``) that
    means a client can get its 201 before the row is committed and miss it on its next
    request. Each service asserts this returns ``[]`` for its app. Every entry reads
    ``"<METHODS> <path>: <parameter> -> <dependency>"``.
    """
    found: list[str] = []
    # iter_route_contexts flattens included routers, which FastAPI keeps as lazy entries
    # in app.routes, and gives each route the dependant it actually runs with.
    for route in iter_route_contexts(app.routes):
        dependant = getattr(route, "dependant", None)
        if not isinstance(dependant, Dependant):
            continue
        methods = ",".join(sorted(route.methods or {"WS"}))
        where = f"{methods} {route.path}"
        for sub in _sub_dependants(dependant):
            if sub.scope != "function" and _yields(sub.call):
                entry = f"{where}: {sub.name or '<dependencies>'} -> {_call_name(sub.call)}"
                if entry not in found:
                    found.append(entry)
    return found


def _sub_dependants(dependant: Dependant) -> Iterator[Dependant]:
    for sub in dependant.dependencies:
        yield sub
        yield from _sub_dependants(sub)


def _yields(call: Callable[..., Any] | None) -> bool:
    """Whether ``call`` is a (sync or async) generator function, as FastAPI decides it."""
    if call is None:
        return False
    candidates: list[Any] = [call]
    if not inspect.isroutine(call) and not inspect.isclass(call):
        candidates.append(getattr(call, "__call__", None))  # noqa: B004
    for candidate in candidates:
        if candidate is None:
            continue
        unwrapped = inspect.unwrap(candidate)
        if inspect.isgeneratorfunction(unwrapped) or inspect.isasyncgenfunction(unwrapped):
            return True
    return False


def _call_name(call: Callable[..., Any] | None) -> str:
    return str(getattr(call, "__qualname__", None) or type(call).__qualname__)


def _allow_cross_site_calls(app: FastAPI, origins: list[str]) -> None:
    """Let the listed websites call the API from a browser (CORS), including Chrome's
    private-network check, so a public site may reach an API on localhost."""
    if not origins:
        return
    app.add_middleware(
        CORSMiddleware,
        allow_origins=origins,
        allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE"],
        # Idempotency-Key lets a page retry a write (e.g. submitting a run) without doing
        # it twice; the server keys the write on it
        allow_headers=["Authorization", "Content-Type", "Idempotency-Key"],
        allow_private_network=True,
        max_age=600,
    )
