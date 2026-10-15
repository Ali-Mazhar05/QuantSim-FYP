"""Builds the Market Data service application.

``uvicorn --factory qs_market.main:create`` reads the settings from the environment;
tests call :func:`build_app` with their own pieces.
"""

from fastapi import FastAPI

from qs_market.api import build_routers
from qs_market.api_correlation import build_correlation_routers
from qs_market.api_data import build_data_routers
from qs_market.settings import MarketSettings
from qs_market.symbol_directory import DirectorySource
from qs_template import Database, ReadinessCheck, create_app
from qs_template.auth import Authenticator
from qs_template.revocation import RevocationList


def build_app(
    settings: MarketSettings,
    *,
    database: Database | None = None,
    revocations: RevocationList | None = None,
    authenticator: Authenticator | None = None,
) -> FastAPI:
    database = database or Database(settings)
    revocations = revocations or RevocationList.from_url(settings.redis_url.get_secret_value())
    auth = authenticator or Authenticator(settings, is_revoked=revocations.is_revoked)
    directory = None
    if settings.symbol_directory_dir is not None:
        directory = DirectorySource(
            settings.symbol_directory_dir, max_age_days=settings.symbol_directory_max_age_days
        )
        directory.get()  # a wrong folder stops the service at start, not at the first add
    return create_app(
        settings,
        database=database,
        routers=[
            *build_routers(auth=auth, database=database, directory=directory),
            *build_data_routers(auth=auth, database=database),
            *build_correlation_routers(auth=auth, database=database),
        ],
        readiness_checks=[ReadinessCheck("redis", revocations.ping)],
        on_shutdown=[revocations.close],
    )


def create() -> FastAPI:
    return build_app(MarketSettings())
