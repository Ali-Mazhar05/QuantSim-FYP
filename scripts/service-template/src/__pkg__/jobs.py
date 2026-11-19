"""Background job handlers of the __Title__ service, by job kind.

A handler receives the claimed job and a progress reporter and returns a JSON-able result
(or ``None``). Register it in :data:`HANDLERS`; the API submits jobs of the same kind
through :func:`job_queue`.
"""

from __pkg__.models import job
from __pkg__.settings import __Class__Settings
from qs_template.jobs import Handler, JobQueue

HANDLERS: dict[str, Handler] = {}


def job_queue(settings: __Class__Settings) -> JobQueue:
    return JobQueue(
        job, lease_seconds=settings.job_lease_seconds, max_attempts=settings.job_max_attempts
    )
