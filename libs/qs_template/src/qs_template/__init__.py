"""Shared service template for QuantSim backend services.

Every service builds its FastAPI app with :func:`create_app`, reads its configuration
through a subclass of :class:`ServiceSettings`, and gets the same logging, error
format, health and readiness endpoints and database session handling (NFR-MNT-006).
"""

from qs_template.app import ReadinessCheck, create_app
from qs_template.config import ServiceSettings
from qs_template.db import Database
from qs_template.errors import ServiceError

__all__ = ["Database", "ReadinessCheck", "ServiceError", "ServiceSettings", "create_app"]
