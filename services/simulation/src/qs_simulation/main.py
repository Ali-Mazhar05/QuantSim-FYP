"""Builds the Simulation service application.

``uvicorn --factory qs_simulation.main:create`` reads the settings from the environment; tests
call :func:`build_app` with their own pieces.
"""

from fastapi import FastAPI

from qs_simulation.api import build_routers
from qs_simulation.settings import SimulationSettings
from qs_template import Database, ReadinessCheck, create_app
from qs_template.auth import Authenticator
from qs_template.revocation import RevocationList


def build_app(
    settings: SimulationSettings,
    *,
    database: Database | None = None,
    revocations: RevocationList | None = None,
    authenticator: Authenticator | None = None,
) -> FastAPI:
    database = database or Database(settings)
    revocations = revocations or RevocationList.from_url(settings.redis_url.get_secret_value())
    auth = authenticator or Authenticator(settings, is_revoked=revocations.is_revoked)
    return create_app(
        settings,
        database=database,
        routers=build_routers(auth=auth, database=database),
        readiness_checks=[ReadinessCheck("redis", revocations.ping)],
        on_shutdown=[revocations.close],
    )


def create() -> FastAPI:
    return build_app(SimulationSettings())
