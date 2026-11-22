"""A-NFR-11 (NFR-SEC-007): the DEV-only static settings never reach TEST, ACC or PROD.

A static service token (``SERVICE_TOKEN`` / ``QS_SERVICE_TOKEN``) and the demo market
environments (``TRADING_DEMO_ENVIRONMENTS``, read by the service as
``QS_TRADING_DEMO_ENVIRONMENTS``) are for DEV only. This checks the deploy configuration
as committed: the env files and the encrypted secrets of test, acc and prod do not set
them, and the compose file does not hard-code them for any environment; it may only pass
on an environment variable of the same name, with an empty default.
"""

import re
from pathlib import Path

import pytest

DEPLOY = Path(__file__).resolve().parents[4] / "deploy"
COMPOSE = DEPLOY / "compose" / "docker-compose.yml"
PROTECTED_ENVS = ("test", "acc", "prod")

DEV_ONLY = ("SERVICE_TOKEN", "QS_SERVICE_TOKEN", "TRADING_DEMO_ENVIRONMENTS")
"""Settings DEV may have and no later environment may."""

_KEY = re.compile(r"^\s*(?:export\s+)?([A-Za-z_][A-Za-z0-9_]*)\s*=")


def env_keys(path: Path) -> set[str]:
    """The variable names an env file (plain or SOPS-encrypted dotenv) sets."""
    keys: set[str] = set()
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.lstrip().startswith("#"):
            continue
        found = _KEY.match(line)
        if found:
            keys.add(found.group(1))
    return keys


def _dev_only(name: str) -> bool:
    bare = name.removeprefix("QS_")
    return bare in DEV_ONLY or bare.endswith("SERVICE_TOKEN")


def compose_settings(text: str) -> list[tuple[int, str, str]]:
    """``(line, name, value)`` of every DEV-only setting the compose file passes on, in
    mapping (``NAME: value``) or list (``- NAME=value``) form."""
    found: list[tuple[int, str, str]] = []
    pattern = re.compile(r"^\s*(?:-\s*)?['\"]?([A-Za-z_][A-Za-z0-9_]*)['\"]?\s*[:=]\s*(.*)$")
    for number, line in enumerate(text.splitlines(), start=1):
        if line.lstrip().startswith("#"):
            continue
        matched = pattern.match(line)
        if matched and _dev_only(matched.group(1)):
            found.append((number, matched.group(1), matched.group(2).strip()))
    return found


def passed_on_empty(name: str, value: str) -> bool:
    """Whether ``value`` only passes on the environment's own variable of the same name
    (``${TRADING_DEMO_ENVIRONMENTS:-}`` for ``QS_TRADING_DEMO_ENVIRONMENTS``), with no
    default or an empty one."""
    matched = re.fullmatch(r"(['\"]?)\$\{([A-Za-z_][A-Za-z0-9_]*)(:?-)?\}\1", value)
    return matched is not None and matched.group(2) in (name, name.removeprefix("QS_"))


@pytest.mark.parametrize("env", PROTECTED_ENVS)
def test_protected_env_files_set_no_dev_only_setting(env: str) -> None:
    keys = env_keys(DEPLOY / "env" / f"{env}.env")
    assert "QS_ENV" in keys  # the file was read
    assert not {k for k in keys if _dev_only(k)}, f"deploy/env/{env}.env sets a DEV-only setting"


@pytest.mark.parametrize("env", PROTECTED_ENVS)
def test_protected_secrets_hold_no_service_token(env: str) -> None:
    # SOPS keeps a dotenv file's names in clear text and encrypts only the values
    keys = env_keys(DEPLOY / "secrets" / f"{env}.enc.env")
    assert "sops_version" in keys  # the file was read
    assert not {k for k in keys if _dev_only(k)}, f"deploy/secrets/{env}.enc.env"


def test_dev_still_has_its_demo_environments() -> None:
    # The rule above would pass vacuously if the parser missed the setting
    assert "TRADING_DEMO_ENVIRONMENTS" in env_keys(DEPLOY / "env" / "dev.env")


def test_compose_never_hard_codes_a_dev_only_setting() -> None:
    settings = compose_settings(COMPOSE.read_text(encoding="utf-8"))
    names = {name for _, name, _ in settings}
    assert "QS_TRADING_DEMO_ENVIRONMENTS" in names  # the trading service passes it on
    hard_coded = [s for s in settings if not passed_on_empty(s[1], s[2])]
    assert not hard_coded, f"{COMPOSE.name} hard-codes a DEV-only setting: {hard_coded}"


@pytest.mark.parametrize(
    ("line", "ok"),
    [
        ("      QS_TRADING_DEMO_ENVIRONMENTS: ${TRADING_DEMO_ENVIRONMENTS:-}", True),
        ("      QS_SERVICE_TOKEN: ${SERVICE_TOKEN}", True),
        ('      QS_SERVICE_TOKEN: "${QS_SERVICE_TOKEN:-}"', True),
        ("      QS_TRADING_DEMO_ENVIRONMENTS: bundled", False),
        ("      QS_TRADING_DEMO_ENVIRONMENTS: ${TRADING_DEMO_ENVIRONMENTS:-bundled}", False),
        ("      - QS_SERVICE_TOKEN=dev-token", False),
        ("      QS_SERVICE_TOKEN: ${OTHER_SECRET}", False),
        ("      PLATFORM_SERVICE_TOKEN: abc", False),
    ],
)
def test_the_compose_rule(line: str, ok: bool) -> None:
    [(_, name, value)] = compose_settings(line)
    assert passed_on_empty(name, value) is ok
