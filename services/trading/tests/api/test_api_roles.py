"""Every route of the service has a declared rule, and every role gets exactly what the
rule allows: the declared roles pass, other roles get 403, no or a forged token 401."""

from api_support import (
    API,
    MATRIX,
    FakeStore,
    check_role_matrix,
    client_for,
    fake_app,
    seed_targets,
)


def test_every_route_has_a_declared_rule() -> None:
    found = {
        (method.upper(), path.removeprefix(API))
        for path, operations in fake_app(FakeStore()).openapi()["paths"].items()
        for method in operations
    }
    assert found == set(MATRIX)


async def test_every_route_allows_exactly_the_declared_roles() -> None:
    async with client_for(fake_app(FakeStore())) as http:
        await check_role_matrix(http, await seed_targets(http))


def test_money_is_a_decimal_string_in_the_openapi_document() -> None:
    schemas = fake_app(FakeStore()).openapi()["components"]["schemas"]
    assert schemas["PortfolioOut"]["properties"]["initial_capital"]["type"] == "string"
