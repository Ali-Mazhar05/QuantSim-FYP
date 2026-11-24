"""Where calibration reads prices from (B15): the market service, or a recorded file."""

import json
from datetime import date
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any
from uuid import UUID

from qs_simulation.domain.calibration import MISSING_ADJUSTED_PRICES, CalibrationRefused, PricePoint
from qs_simulation.ports import Getter, InstrumentInfo, InstrumentNotFound, PriceSourceError
from qs_template.errors import ServiceError

PAGE_LIMIT = 2000  # the market service's largest page (api_data.MAX_LIMIT)
MAX_PAGES = 100  # 200,000 sessions: far more than any window; stops a cursor that never ends


def _decimal(value: Any, session_date: str) -> Decimal:
    try:
        return Decimal(str(value))
    except InvalidOperation as error:
        raise CalibrationRefused(
            MISSING_ADJUSTED_PRICES, f"the adjusted close on {session_date} is not a number"
        ) from error


class MarketPriceSource:
    """Reads the instrument and its adjusted closes from the market service through ``Getter``
    (the K3 service client: timeouts, retries and a circuit breaker live there).

    A 404 is ``InstrumentNotFound``; any other failure is ``PriceSourceError``, which the
    job retries. A bar without an adjusted close refuses the calibration: a raw price is never
    substituted (ADR 08).
    """

    def __init__(self, getter: Getter, *, prefix: str = "/api/market") -> None:
        self._getter = getter
        self._prefix = prefix

    async def _get(self, path: str, params: dict[str, Any] | None = None) -> Any:
        try:
            return await self._getter.get_json(f"{self._prefix}{path}", params=params)
        except ServiceError as error:
            upstream = error.extra.get("upstream_status")
            if error.status == 404 or upstream == 404:
                raise InstrumentNotFound(path) from error
            raise PriceSourceError(f"the market service failed on {path}: {error}") from error
        except (OSError, TimeoutError) as error:
            raise PriceSourceError(f"the market service could not be reached: {error}") from error

    async def instrument(self, instrument_id: UUID) -> InstrumentInfo:
        body = await self._get(f"/instruments/{instrument_id}")
        return InstrumentInfo(
            instrument_id=instrument_id,
            symbol=str(body["symbol"]),
            name=str(body.get("name", "")),
            status=str(body.get("status", "active")),
        )

    async def window(self, instrument_id: UUID, start: date, end: date) -> list[PricePoint]:
        points: list[PricePoint] = []
        params: dict[str, Any] = {
            "from": start.isoformat(),
            "to": end.isoformat(),
            "limit": PAGE_LIMIT,
        }
        for _ in range(MAX_PAGES):
            page = await self._get(f"/instruments/{instrument_id}/bars", params)
            for bar in page["items"]:
                if bar["adj_close"] is None:
                    raise CalibrationRefused(
                        MISSING_ADJUSTED_PRICES,
                        f"the bar of {bar['session_date']} has no adjusted close",
                    )
                points.append(
                    PricePoint(
                        session_date=date.fromisoformat(bar["session_date"]),
                        adj_close=_decimal(bar["adj_close"], bar["session_date"]),
                        revision=int(bar["revision"]),
                    )
                )
            cursor = page.get("next_cursor")
            if cursor is None:
                return points
            params["cursor"] = cursor
        raise PriceSourceError("the market service paged past the limit")


class FilePriceSource:
    """Reads the adjusted closes of a recorded replay fixture (``contracts/fixtures``): the same
    prices the replay feed serves, with no network. A tick carries no revision, so every close is
    revision 1; the fingerprint of a file window is therefore stable but not the market's."""

    def __init__(self, path: Path) -> None:
        document = json.loads(path.read_text(encoding="utf-8"))
        self._symbols = {UUID(i["id"]): i["symbol"] for i in document["environment"]["instruments"]}
        self._closes: dict[UUID, list[PricePoint]] = {i: [] for i in self._symbols}
        for tick in document["items"]:
            self._closes[UUID(tick["instrument_id"])].append(
                PricePoint(
                    date.fromisoformat(tick["session_date"]), Decimal(tick["close"]), revision=1
                )
            )

    async def instrument(self, instrument_id: UUID) -> InstrumentInfo:
        if instrument_id not in self._symbols:
            raise InstrumentNotFound(str(instrument_id))
        symbol = self._symbols[instrument_id]
        return InstrumentInfo(instrument_id, symbol, symbol, "active")

    async def window(self, instrument_id: UUID, start: date, end: date) -> list[PricePoint]:
        if instrument_id not in self._closes:
            raise InstrumentNotFound(str(instrument_id))
        return [p for p in self._closes[instrument_id] if start <= p.session_date <= end]
