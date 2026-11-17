"""HTTP API of the __Title__ service, under ``/api/__name__``."""

from fastapi import APIRouter

from qs_template import Database
from qs_template.auth import Authenticator


def build_routers(*, auth: Authenticator, database: Database) -> list[APIRouter]:
    """Every router of the service. Add new routers here."""
    return []
