"""One error format for every service: RFC 9457 problem details.

Clients and other services always receive ``application/problem+json`` with a type,
title, status and detail, plus the request id so a report can be traced to its logs.
Unexpected errors are logged in full but never leak internals to the caller.
"""

from typing import Any

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from qs_template.logging import get_logger

PROBLEM_JSON = "application/problem+json"

log = get_logger(__name__)


class ServiceError(Exception):
    """An expected failure with a stable, documented type."""

    def __init__(
        self,
        status: int,
        title: str,
        detail: str | None = None,
        *,
        type_: str = "about:blank",
        extra: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(detail or title)
        self.status = status
        self.title = title
        self.detail = detail
        self.type = type_
        self.extra = extra or {}


def problem(
    request: Request,
    status: int,
    title: str,
    detail: str | None = None,
    *,
    type_: str = "about:blank",
    extra: dict[str, Any] | None = None,
) -> JSONResponse:
    body: dict[str, Any] = {"type": type_, "title": title, "status": status}
    if detail:
        body["detail"] = detail
    request_id = getattr(request.state, "request_id", None)
    if request_id:
        body["request_id"] = request_id
    body.update(extra or {})
    return JSONResponse(body, status_code=status, media_type=PROBLEM_JSON)


async def _service_error(request: Request, exc: Exception) -> JSONResponse:
    assert isinstance(exc, ServiceError)
    return problem(request, exc.status, exc.title, exc.detail, type_=exc.type, extra=exc.extra)


async def _http_error(request: Request, exc: Exception) -> JSONResponse:
    assert isinstance(exc, StarletteHTTPException)
    response = problem(request, exc.status_code, _title(exc.status_code), str(exc.detail))
    for name, value in (exc.headers or {}).items():
        response.headers[name] = value
    return response


async def _validation_error(request: Request, exc: Exception) -> JSONResponse:
    assert isinstance(exc, RequestValidationError)
    errors = [
        {"location": list(e.get("loc", [])), "message": e.get("msg", ""), "type": e.get("type", "")}
        for e in exc.errors()
    ]
    return problem(
        request,
        422,
        "Invalid request",
        "One or more fields are missing or invalid.",
        extra={"errors": errors},
    )


async def _unexpected_error(request: Request, exc: Exception) -> JSONResponse:
    log.exception("unhandled error", path=request.url.path)
    return problem(request, 500, "Internal error", "The request could not be completed.")


def _title(status: int) -> str:
    return {
        400: "Bad request",
        401: "Not authenticated",
        403: "Forbidden",
        404: "Not found",
        405: "Method not allowed",
        409: "Conflict",
        429: "Too many requests",
        503: "Service unavailable",
    }.get(status, "Error")


def install_error_handlers(app: FastAPI) -> None:
    app.add_exception_handler(ServiceError, _service_error)
    app.add_exception_handler(StarletteHTTPException, _http_error)
    app.add_exception_handler(RequestValidationError, _validation_error)
    app.add_exception_handler(Exception, _unexpected_error)
