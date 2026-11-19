"""HTTP API of the Simulation service, under ``/api/simulation``."""

from fastapi import APIRouter

from qs_template import Database
from qs_template.auth import Authenticator


def build_routers(*, auth: Authenticator, database: Database) -> list[APIRouter]:
    """Every router of the service. Add new routers here."""
    return []
