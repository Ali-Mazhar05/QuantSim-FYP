"""Property-based contract tests of the Trading API (I2-61): Schemathesis generates
requests for every operation in the service's own OpenAPI document and checks each
response against it.

For every generated request, valid or not, the service must:

- never answer with a server error;
- answer only with a status code its OpenAPI document lists for that operation;
- send a body that matches the documented schema for that status and content type.

The app is the real router stack over the in-memory store (``fake_app``), so no database
is needed and the test runs on every build. It runs once as an admin, who may call every
route, and once as a viewer, whose writes must be refused within the documented codes.
"""

from typing import Any

import pytest
import schemathesis
from api_support import FakeStore, as_role, fake_app
from hypothesis import HealthCheck, settings
from schemathesis.checks import (
    content_type_conformance,
    not_a_server_error,
    response_schema_conformance,
    status_code_conformance,
)

from qs_template.auth import Role

CHECKS = [
    not_a_server_error,
    status_code_conformance,
    content_type_conformance,
    response_schema_conformance,
]

# Readiness pings the database, which the in-memory app has none of, so it is left out: its
# 503 is the documented answer, not a fault
schema = schemathesis.openapi.from_asgi("/api/trading/openapi.json", fake_app(FakeStore())).exclude(
    path_regex=r"/ready$"
)


@pytest.mark.parametrize("role", [Role.ADMIN, Role.VIEWER])
@schema.parametrize()
@settings(
    max_examples=25,
    deadline=None,
    suppress_health_check=[HealthCheck.too_slow, HealthCheck.filter_too_much],
)
def test_every_operation_keeps_to_its_openapi_contract(
    role: Role, case: schemathesis.Case[Any]
) -> None:
    case.call_and_validate(headers=as_role(role), checks=CHECKS)
