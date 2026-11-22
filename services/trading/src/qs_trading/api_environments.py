"""Demo environment route, under ``/api/trading`` (task A18).

Signed-in users (any role):  GET /demo-environments

On LOCAL and DEV, ``QS_TRADING_DEMO_ENVIRONMENTS`` lets the worker run portfolios over the
fixture files of a directory (see :func:`qs_trading.jobs.environment_factory`). The
Create Portfolio page lists them beside the market service's replay environments, so a
portfolio can be bound to one. This route lists the replay fixtures of that directory:
id, name, type, the number of sessions and the first and last session date. Without the
setting (TEST, ACC, PROD) the list is empty.

Each file is read once and kept until its size or modification time changes. A file that
is not a replay fixture with a UUID id (a synthetic run, a broken file) is left out.
"""

import json
import uuid
from datetime import date
from functools import lru_cache
from pathlib import Path
from typing import Annotated, Any

from fastapi import APIRouter, Depends

from qs_template.auth import Authenticator, Principal
from qs_template.logging import get_logger
from qs_trading.jobs import BUNDLED_DEMO_ENVIRONMENTS
from qs_trading.schemas import DemoEnvironmentOut

__all__ = ["build_environment_routers", "demo_directory", "list_demo_environments"]

log = get_logger(__name__)

_REPLAY_TYPES = frozenset({"historical_replay", "replay"})


def demo_directory(configured: str) -> Path | None:
    """The directory ``QS_TRADING_DEMO_ENVIRONMENTS`` names (``bundled`` = the package's
    own), or ``None`` when it is not set."""
    if not configured:
        return None
    return BUNDLED_DEMO_ENVIRONMENTS if configured == "bundled" else Path(configured)


def _date(value: Any) -> date | None:
    if not isinstance(value, str):
        return None
    try:
        return date.fromisoformat(value)
    except ValueError:
        return None


@lru_cache(maxsize=64)
def _read(path: str, _mtime_ns: int, _size: int) -> DemoEnvironmentOut | None:
    """One fixture file described, or ``None`` when it is not a listable replay fixture.
    The modification time and size are part of the cache key only."""
    try:
        document = json.loads(Path(path).read_bytes())
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        log.warning("demo environment file unreadable", path=path)
        return None
    if not isinstance(document, dict):
        return None
    environment = document.get("environment")
    items = document.get("items")
    if not isinstance(environment, dict) or not isinstance(items, list):
        return None
    if environment.get("type") not in _REPLAY_TYPES:
        return None
    try:
        env_id = uuid.UUID(str(environment.get("id")))
    except ValueError:
        return None
    sessions = {item.get("session") for item in items if isinstance(item, dict)}
    dates = sorted(
        d
        for d in (_date(item.get("session_date")) for item in items if isinstance(item, dict))
        if d is not None
    )
    name = environment.get("name")
    return DemoEnvironmentOut(
        id=env_id,
        name=name if isinstance(name, str) and name else str(env_id),
        env_type="replay",
        sessions=len(sessions - {None}),
        start_date=_date(environment.get("start_date")) or (dates[0] if dates else None),
        end_date=_date(environment.get("end_date")) or (dates[-1] if dates else None),
    )


def list_demo_environments(directory: Path | None) -> list[DemoEnvironmentOut]:
    """The replay fixtures of ``directory``, by name; empty when it is ``None`` or does
    not exist."""
    if directory is None or not directory.is_dir():
        return []
    found: list[DemoEnvironmentOut] = []
    for path in sorted(directory.glob("*.json")):
        try:
            stat = path.stat()
        except OSError:
            continue
        described = _read(str(path), stat.st_mtime_ns, stat.st_size)
        if described is not None:
            found.append(described)
    return sorted(found, key=lambda e: (e.name, str(e.id)))


def build_environment_routers(*, auth: Authenticator, demo_environments: str) -> list[APIRouter]:
    router = APIRouter(tags=["environments"])
    directory = demo_directory(demo_environments)

    Reader = Annotated[Principal, Depends(auth.principal)]

    @router.get("/demo-environments", responses={401: {}})
    async def demo_environments_list(_: Reader) -> list[DemoEnvironmentOut]:
        return list_demo_environments(directory)

    return [router]
