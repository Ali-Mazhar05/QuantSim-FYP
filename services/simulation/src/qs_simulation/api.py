"""HTTP API of the Simulation service, under ``/api/simulation``."""

from fastapi import APIRouter

from qs_simulation.api_calibrations import build_calibration_routers
from qs_simulation.api_runs import build_run_routers
from qs_simulation.ports import Calibrator
from qs_template import Database
from qs_template.auth import Authenticator
from qs_template.jobs import JobQueue


def build_routers(
    *,
    auth: Authenticator,
    database: Database,
    queue: JobQueue,
    calibrator: Calibrator,
    can_calibrate: bool,
) -> list[APIRouter]:
    """Every router of the service. Add new routers here."""
    return [
        *build_calibration_routers(
            auth=auth, database=database, queue=queue, calibrator=calibrator, can_run=can_calibrate
        ),
        *build_run_routers(auth=auth, database=database),
    ]
