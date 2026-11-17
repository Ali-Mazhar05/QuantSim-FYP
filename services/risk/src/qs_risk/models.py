"""Tables of risk_db. Every change here needs a migration in ``migrations/versions``."""

from sqlalchemy import MetaData

from qs_template.jobs import job_table

metadata = MetaData()

job = job_table(metadata)
