"""The role matrix (SPEC section 1): each role adds to the one below it, and the
POC frontend's capability map grants exactly what the backend enforces."""

import re
import uuid
from itertools import pairwise
from pathlib import Path
from typing import Annotated

import pytest
from fastapi import Depends, FastAPI
from fastapi.testclient import TestClient

from qs_template.auth import (
    ROLE_CAPABILITIES,
    ROLE_RANK,
    Authenticator,
    Capability,
    Principal,
    Role,
    can,
)
from qs_template.errors import install_error_handlers

POC_PERMISSIONS = Path(__file__).resolve().parents[3] / "frontend/src/demo/permissions.ts"
POC_ROLES = {
    "Viewer": Role.VIEWER,
    "Analyst": Role.ANALYST,
    "Quant": Role.QUANT,
    "Admin": Role.ADMIN,
}


def poc_capabilities() -> dict[Role, set[str]]:
    source = POC_PERMISSIONS.read_text(encoding="utf-8")
    table = source[source.index("const CAPABILITIES") : source.index("export function can")]
    result = {}
    for name, role in POC_ROLES.items():
        block = re.search(rf"{name}: \[(.*?)\]", table, re.DOTALL)
        assert block, f"{name} missing from permissions.ts"
        result[role] = set(re.findall(r"'([a-z_]+)'", block.group(1)))
    return result


def test_the_poc_map_grants_exactly_what_the_backend_enforces() -> None:
    poc = poc_capabilities()
    poc_names = set().union(*poc.values())
    for role, granted in ROLE_CAPABILITIES.items():
        assert {c.value for c in granted if c.value in poc_names} == poc[role], role


def test_every_poc_capability_exists_in_the_backend() -> None:
    known = {c.value for c in Capability}
    assert set().union(*poc_capabilities().values()) <= known


def test_each_role_has_everything_the_role_below_it_has() -> None:
    ordered = sorted(ROLE_CAPABILITIES, key=ROLE_RANK.__getitem__)
    for lower, higher in pairwise(ordered):
        assert ROLE_CAPABILITIES[lower] < ROLE_CAPABILITIES[higher]


@pytest.mark.parametrize(
    ("role", "capability", "allowed"),
    [
        (Role.VIEWER, Capability.VIEW_MARKET_DATA, True),
        (Role.VIEWER, Capability.VIEW_INGESTION_RUNS, False),
        (Role.ANALYST, Capability.VIEW_INGESTION_RUNS, True),
        (Role.ANALYST, Capability.TRIGGER_INGESTION, False),
        (Role.QUANT, Capability.TRIGGER_INGESTION, True),
        (Role.QUANT, Capability.BACKFILL_MARKET_DATA, False),
        (Role.QUANT, Capability.MANAGE_USERS, False),
        (Role.ADMIN, Capability.MANAGE_USERS, True),
    ],
)
def test_spec_rules(role: Role, capability: Capability, allowed: bool) -> None:
    assert can(role, capability) is allowed


def principal_as(role: Role) -> Principal:
    return Principal(
        user_id=uuid.uuid4(), username="u", role=role, token_id="t", issued_at=1_700_000_000
    )


@pytest.mark.parametrize("role", list(Role))
def test_require_capability_refuses_roles_without_it(role: Role) -> None:
    auth = Authenticator.__new__(Authenticator)
    check = auth.require_capability(Capability.TRIGGER_INGESTION)
    app = FastAPI()
    install_error_handlers(app)
    app.dependency_overrides[auth.principal] = lambda: principal_as(role)

    @app.post("/runs")
    async def trigger(_: Annotated[Principal, Depends(check)]) -> dict[str, bool]:
        return {"ok": True}

    status = TestClient(app).post("/runs").status_code
    assert status == (200 if role in (Role.QUANT, Role.ADMIN) else 403)
