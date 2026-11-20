"""Write each service's OpenAPI document where the frontend client is generated from (K4).

    uv run --frozen --all-packages python scripts/export-openapi.py            # write all
    uv run --frozen --all-packages python scripts/export-openapi.py --check    # fail if stale

The frontend types come from these files (``npm run gen:api``). ``--check`` is what makes an API
change visible: a service whose spec no longer matches its committed file fails the service's
tests, and the regenerated types then fail the frontend type check where a page used the old field.
The apps are built with placeholder settings; building them opens no connection.
"""

import argparse
import json
import sys
from collections.abc import Callable
from pathlib import Path

from fastapi import FastAPI
from pydantic import SecretStr

REPO = Path(__file__).resolve().parent.parent
OUT = REPO / "frontend" / "src" / "services" / "generated"


def market() -> FastAPI:
    from qs_market.main import build_app
    from qs_market.settings import MarketSettings

    return build_app(
        MarketSettings(
            database_url=SecretStr("postgresql+asyncpg://unused:unused@127.0.0.1:1/unused"),
            redis_url=SecretStr("redis://127.0.0.1:1"),
            content_hash="0123456789ab",
            auth_jwks_url="http://platform/api/platform/.well-known/jwks.json",
        )
    )


def trading() -> FastAPI:
    from qs_trading.main import build_app
    from qs_trading.settings import TradingSettings

    return build_app(
        TradingSettings(
            database_url=SecretStr("postgresql+asyncpg://unused:unused@127.0.0.1:1/unused"),
            redis_url=SecretStr("redis://127.0.0.1:1"),
            content_hash="0123456789ab",
            auth_jwks_url="http://platform/api/platform/.well-known/jwks.json",
        )
    )


# Add a service here when it exists; each entry builds the app with placeholder settings
SERVICES: dict[str, Callable[[], FastAPI]] = {"market": market, "trading": trading}


def spec_path(service: str) -> Path:
    return OUT / service / "openapi.json"


def render(service: str) -> str:
    document = SERVICES[service]().openapi()
    return json.dumps(document, indent=2, sort_keys=True, ensure_ascii=False) + "\n"


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("services", nargs="*", help=f"any of: {', '.join(SERVICES)} (default all)")
    parser.add_argument("--check", action="store_true", help="fail if a committed file is stale")
    args = parser.parse_args(argv)
    unknown = [name for name in args.services if name not in SERVICES]
    if unknown:
        parser.error(f"unknown service: {', '.join(unknown)}")
    stale = []
    for service in args.services or list(SERVICES):
        path = spec_path(service)
        text = render(service)
        if args.check:
            # compare parsed documents so line endings never decide the result
            current = json.loads(path.read_text(encoding="utf-8")) if path.exists() else None
            if current != json.loads(text):
                stale.append(service)
        else:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(text, encoding="utf-8", newline="\n")
            print(f"wrote {path.relative_to(REPO)}")
    if stale:
        print(
            f"stale OpenAPI for: {', '.join(stale)}; run scripts/export-openapi.py and "
            "'npm run gen:api' in frontend, then commit",
            file=sys.stderr,
        )
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
