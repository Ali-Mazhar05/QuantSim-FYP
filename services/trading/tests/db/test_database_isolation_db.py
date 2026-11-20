"""A-NFR-11 (NFR-SEC-007): each service's login role reaches only its own database.

The SQL is read from db-init in ``deploy/compose/docker-compose.yml``, the very text every
deploy runs, and applied the way psql would for two made-up services, twice (db-init runs
before every deploy, so it must be idempotent). Then each role can connect to its own
database and is refused by the other's."""

import os
import re
import textwrap
import uuid
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

import pytest
from sqlalchemy import text
from sqlalchemy.engine import make_url
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import create_async_engine
from trading_db_support import execute_autocommit, run

COMPOSE = Path(__file__).resolve().parents[4] / "deploy" / "compose" / "docker-compose.yml"


def db_init_sql() -> str:
    """The heredoc db-init feeds psql for every service."""
    found = re.search(r"<<'SQL'\n(.*?)\n[ \t]*SQL\n", COMPOSE.read_text(encoding="utf-8"), re.S)
    assert found, f"no <<'SQL' heredoc in {COMPOSE}"
    return textwrap.dedent(found.group(1))


def _literal(value: str) -> str:
    return "'" + value.replace("'", "''") + "'"


def _identifier(value: str) -> str:
    return '"' + value.replace('"', '""') + '"'


def psql_statements(sql: str, variables: dict[str, str]) -> list[tuple[str, bool]]:
    """``(statement, gexec)`` pairs with psql's ``:'var'`` and ``:"var"`` substituted;
    ``gexec`` statements produce the statements to run (psql's ``\\gexec``)."""
    for name, value in variables.items():
        sql = sql.replace(f":'{name}'", _literal(value)).replace(f':"{name}"', _identifier(value))
    assert not re.search(r":['\"]\w+['\"]", sql), f"an unset psql variable is left: {sql}"
    statements: list[tuple[str, bool]] = []
    for body, end in re.findall(r"(.*?)(;|\\gexec)", sql, re.S):
        if body.strip():
            statements.append((body.strip(), end == "\\gexec"))
    return statements


async def apply_db_init(admin_url: str, name: str, password: str) -> None:
    engine = create_async_engine(admin_url, isolation_level="AUTOCOMMIT")
    try:
        async with engine.connect() as connection:
            for statement, gexec in psql_statements(db_init_sql(), {"name": name, "pw": password}):
                if not gexec:
                    await connection.execute(text(statement))
                    continue
                for (generated,) in (await connection.execute(text(statement))).all():
                    await connection.execute(text(str(generated)))
    finally:
        await engine.dispose()


async def current_database(url: str) -> str:
    engine = create_async_engine(url)
    try:
        async with engine.connect() as connection:
            return str(await connection.scalar(text("SELECT current_database()")))
    finally:
        await engine.dispose()


@contextmanager
def two_services() -> Iterator[dict[str, str]]:
    """Two services set up by db-init: name -> password. Dropped afterwards."""
    admin_url = os.environ["TEST_DATABASE_URL"]
    suffix = uuid.uuid4().hex[:10]
    services = {f"svc_a_{suffix}": uuid.uuid4().hex, f"svc_b_{suffix}": uuid.uuid4().hex}
    try:
        for _ in range(2):  # the second pass must change nothing and not fail
            for name, password in services.items():
                run(apply_db_init(admin_url, name, password))
        yield services
    finally:
        for name in services:
            run(execute_autocommit(admin_url, f'DROP DATABASE IF EXISTS "{name}" WITH (FORCE)'))
            run(execute_autocommit(admin_url, f'DROP ROLE IF EXISTS "{name}"'))


def _url(role: str, password: str, database: str) -> str:
    base = make_url(os.environ["TEST_DATABASE_URL"])
    url = base.set(username=role, password=password, database=database)
    return url.render_as_string(hide_password=False)


def test_the_db_init_sql_is_found_and_parsed() -> None:
    statements = psql_statements(db_init_sql(), {"name": "svc", "pw": "secret"})
    kinds = [(s.split()[0].upper(), gexec) for s, gexec in statements]
    assert ("REVOKE", False) in kinds and ("GRANT", False) in kinds
    assert [gexec for _, gexec in statements].count(True) == 2  # CREATE ROLE, CREATE DATABASE
    builtin = [s for s, _ in statements if "REVOKE CONNECT ON DATABASE" in s.upper()]
    closed = sorted(re.findall(r"REVOKE CONNECT ON DATABASE (\w+) FROM PUBLIC", " ".join(builtin)))
    assert closed == ["postgres", "template1"]
    assert all('"svc"' in s or "'svc'" in s for s, _ in statements if s not in builtin)


@pytest.mark.db
def test_each_service_role_reaches_only_its_own_database() -> None:
    with two_services() as services:
        (a, a_password), (b, b_password) = services.items()
        assert run(current_database(_url(a, a_password, a))) == a
        assert run(current_database(_url(b, b_password, b))) == b
        for role, password, other in ((a, a_password, b), (b, b_password, a)):
            # Neither the other service's database nor the built-in ones
            for database in (other, "postgres", "template1"):
                with pytest.raises(DBAPIError) as refused:
                    run(current_database(_url(role, password, database)))
                assert "permission denied for database" in str(refused.value), refused.value
