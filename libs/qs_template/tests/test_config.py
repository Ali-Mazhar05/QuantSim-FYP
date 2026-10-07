import pytest
from pydantic import ValidationError

from qs_template.config import ServiceSettings


def test_reads_prefixed_environment_variables(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("QS_SERVICE_NAME", "market")
    monkeypatch.setenv("QS_DATABASE_URL", "postgresql+asyncpg://u:p@db/market")
    monkeypatch.setenv("QS_ENVIRONMENT", "dev")

    settings = ServiceSettings()

    assert settings.service_name == "market"
    assert settings.environment == "dev"
    assert settings.api_prefix == "/api/market"


def test_hides_the_database_password(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("QS_SERVICE_NAME", "market")
    monkeypatch.setenv("QS_DATABASE_URL", "postgresql+asyncpg://u:secret@db/market")

    settings = ServiceSettings()

    assert "secret" not in repr(settings)
    assert "secret" in settings.database_url.get_secret_value()


def test_refuses_to_start_without_required_settings(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("QS_SERVICE_NAME", raising=False)
    monkeypatch.delenv("QS_DATABASE_URL", raising=False)

    with pytest.raises(ValidationError) as error:
        ServiceSettings()

    missing = {e["loc"][0] for e in error.value.errors()}
    assert missing == {"service_name", "database_url"}


@pytest.mark.parametrize("name", ["Market", "market_data", "", "1market"])
def test_rejects_service_names_that_are_not_url_safe(
    monkeypatch: pytest.MonkeyPatch, name: str
) -> None:
    monkeypatch.setenv("QS_SERVICE_NAME", name)
    monkeypatch.setenv("QS_DATABASE_URL", "postgresql+asyncpg://u:p@db/x")

    with pytest.raises(ValidationError):
        ServiceSettings()


def test_rejects_an_unknown_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("QS_SERVICE_NAME", "market")
    monkeypatch.setenv("QS_DATABASE_URL", "postgresql+asyncpg://u:p@db/x")
    monkeypatch.setenv("QS_ENVIRONMENT", "staging")

    with pytest.raises(ValidationError):
        ServiceSettings()
