"""Builds the Platform service application.

``uvicorn --factory qs_platform.main:create`` (what ``qs-platform serve`` runs) reads the
settings from the environment; tests call :func:`build_app` with their own pieces.
"""

from fastapi import FastAPI

from qs_platform.api import build_routers
from qs_platform.keys import SigningKeys
from qs_platform.service import UserService
from qs_platform.settings import PlatformSettings
from qs_template import Database, ReadinessCheck, create_app
from qs_template.auth import Authenticator, StaticKeys
from qs_template.revocation import RevocationList


def build_app(
    settings: PlatformSettings,
    *,
    database: Database | None = None,
    revocations: RevocationList | None = None,
) -> FastAPI:
    database = database or Database(settings)
    revocations = revocations or RevocationList.from_url(
        settings.redis_url.get_secret_value(),
        max_token_lifetime_seconds=settings.access_token_ttl_seconds,
    )
    keys = SigningKeys(
        settings.signing_key_pem, settings.signing_key_id, settings.retired_public_keys
    )
    # The Platform service verifies its own tokens with the keys it holds
    auth = Authenticator(
        settings, jwks=StaticKeys(keys.jwks()), is_revoked=revocations.is_revoked
    )
    service = UserService(settings, keys, revocations)
    return create_app(
        settings,
        database=database,
        routers=build_routers(service=service, auth=auth, database=database, keys=keys),
        readiness_checks=[ReadinessCheck("redis", revocations.ping)],
        on_shutdown=[revocations.close],
    )


def create() -> FastAPI:
    return build_app(PlatformSettings())  # type: ignore[call-arg]
