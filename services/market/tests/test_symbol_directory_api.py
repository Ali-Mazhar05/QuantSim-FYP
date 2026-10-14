"""POST /instruments with the symbol directory configured, by role and by reason."""

import logging
from collections.abc import AsyncIterator
from pathlib import Path
from typing import Any

import httpx
import pytest
from fakeredis import FakeAsyncRedis

from qs_market.main import build_app
from qs_market.symbol_directory import NASDAQ_FILE, OTHER_FILE, DirectoryError
from qs_template import Database
from qs_template.auth import Authenticator, Role, StaticKeys
from qs_template.revocation import RevocationList
from tests import instrument_support as support
from tests.instrument_support import API, NEW_INSTRUMENT, bearer, make_settings, make_token

database = support.database
pytestmark = pytest.mark.db

FIXTURE = Path(__file__).parent / "fixtures" / "symdir"
VALIDATION = "urn:quantsim:problem:validation"
ADMIN = bearer(make_token(Role.ADMIN))


def _app_client(database: Database, url: str, **settings: Any) -> httpx.AsyncClient:
    config = make_settings(url, **settings)
    app = build_app(
        config,
        database=database,
        revocations=RevocationList(FakeAsyncRedis()),
        authenticator=Authenticator(config, jwks=StaticKeys(support._jwks())),
    )
    return httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://market")


@pytest.fixture
async def checked(
    database: Database, migrated_database_url: str
) -> AsyncIterator[httpx.AsyncClient]:
    async with _app_client(database, migrated_database_url, symbol_directory_dir=FIXTURE) as http:
        yield http


@pytest.fixture
async def unchecked(
    database: Database, migrated_database_url: str
) -> AsyncIterator[httpx.AsyncClient]:
    async with _app_client(database, migrated_database_url) as http:
        yield http


def body(symbol: str, asset_class: str = "equity", **extra: Any) -> dict[str, Any]:
    return {**NEW_INSTRUMENT, "symbol": symbol, "asset_class": asset_class, **extra}


async def test_known_symbol_is_added(checked: httpx.AsyncClient) -> None:
    response = await checked.post(f"{API}/instruments", json=body("AMD"), headers=ADMIN)
    assert response.status_code == 201, response.text
    assert response.json()["symbol"] == "AMD"


async def test_known_etf_is_added(checked: httpx.AsyncClient) -> None:
    response = await checked.post(
        f"{API}/instruments", json=body("ARKK", "etf", exchange="ARCX"), headers=ADMIN
    )
    assert response.status_code == 201, response.text


async def test_class_share_dash_form_is_accepted(checked: httpx.AsyncClient) -> None:
    response = await checked.post(
        f"{API}/instruments", json=body("BRK-B", exchange="XNYS"), headers=ADMIN
    )
    assert response.status_code == 201, response.text
    assert response.json()["symbol"] == "BRK-B"


@pytest.mark.parametrize(
    ("symbol", "asset_class", "field", "words"),
    [
        ("NOSUCH", "equity", "symbol", "not in the Nasdaq symbol directory"),
        ("ZXYZ.A", "equity", "symbol", "test issue"),
        ("ZZZTX", "equity", "symbol", "test issue"),
        ("AACG", "equity", "symbol", "financial status D"),
        ("SPY", "equity", "asset_class", "is an ETF"),
        ("AAPL", "etf", "asset_class", "is not an ETF"),
    ],
)
async def test_rejection_reasons(
    checked: httpx.AsyncClient, symbol: str, asset_class: str, field: str, words: str
) -> None:
    response = await checked.post(
        f"{API}/instruments", json=body(symbol, asset_class), headers=ADMIN
    )
    assert response.status_code == 422, response.text
    problem = response.json()
    assert problem["type"] == VALIDATION
    assert problem["errors"][0]["location"] == ["body", field]
    assert words in problem["errors"][0]["message"]
    assert (await checked.get(f"{API}/instruments", headers=ADMIN)).json() == []


async def test_directory_does_not_change_who_may_add(checked: httpx.AsyncClient) -> None:
    for role in Role:
        response = await checked.post(
            f"{API}/instruments", json=body("NOSUCH"), headers=bearer(make_token(role))
        )
        assert response.status_code == (422 if role is Role.ADMIN else 403), role
    anonymous = await checked.post(f"{API}/instruments", json=body("NOSUCH"))
    assert anonymous.status_code == 401


async def test_patch_is_not_checked(
    checked: httpx.AsyncClient, unchecked: httpx.AsyncClient
) -> None:
    created = await unchecked.post(f"{API}/instruments", json=body("NOSUCH"), headers=ADMIN)
    assert created.status_code == 201
    patched = await checked.patch(
        f"{API}/instruments/{created.json()['id']}", json={"notes": "kept"}, headers=ADMIN
    )
    assert patched.status_code == 200
    assert patched.json()["notes"] == "kept"


async def test_disabled_mode_adds_any_symbol(unchecked: httpx.AsyncClient) -> None:
    for symbol, asset_class in (("NOSUCH", "equity"), ("ZZTEST", "etf")):
        response = await unchecked.post(
            f"{API}/instruments", json=body(symbol, asset_class), headers=ADMIN
        )
        assert response.status_code == 201, response.text


async def test_stale_directory_warns_and_still_adds(
    database: Database,
    migrated_database_url: str,
    caplog: pytest.LogCaptureFixture,
    tmp_path: Path,
) -> None:
    for name in (NASDAQ_FILE, OTHER_FILE):
        text = (FIXTURE / name).read_text(encoding="utf-8")
        old = text.replace("File Creation Time: 1014202612:11", "File Creation Time: 0102202012:00")
        (tmp_path / name).write_text(old, encoding="utf-8")
    async with _app_client(database, migrated_database_url, symbol_directory_dir=tmp_path) as http:
        with caplog.at_level(logging.WARNING):
            response = await http.post(f"{API}/instruments", json=body("AMD"), headers=ADMIN)
    assert response.status_code == 201, response.text
    assert any("days old" in r.getMessage() for r in caplog.records)


async def test_missing_files_stop_start_up(
    database: Database, migrated_database_url: str, tmp_path: Path
) -> None:
    with pytest.raises(DirectoryError):
        _app_client(database, migrated_database_url, symbol_directory_dir=tmp_path)


async def test_files_removed_after_start_give_503(
    database: Database, migrated_database_url: str, tmp_path: Path
) -> None:
    for name in (NASDAQ_FILE, OTHER_FILE):
        (tmp_path / name).write_bytes((FIXTURE / name).read_bytes())
    async with _app_client(database, migrated_database_url, symbol_directory_dir=tmp_path) as http:
        (tmp_path / NASDAQ_FILE).unlink()
        response = await http.post(f"{API}/instruments", json=body("AMD"), headers=ADMIN)
    assert response.status_code == 503
    assert response.json()["type"] == "urn:quantsim:problem:symbol-directory-unavailable"
