"""Cursor paging for the lists (same envelope as the market bars: ``items`` and ``next_cursor``).

A cursor names the last row of the page it ended, by (created_at, id), so a page never repeats or
skips a row when new ones arrive at the top. It is opaque to callers.
"""

import base64
import binascii
import uuid
from datetime import datetime

from qs_template.errors import ServiceError

DEFAULT_PAGE = 500  # the same convention as the market service
MAX_PAGE = 2000


def encode_cursor(created_at: datetime, row_id: uuid.UUID) -> str:
    text = f"{created_at.isoformat()}|{row_id}"
    return base64.urlsafe_b64encode(text.encode()).decode().rstrip("=")


def decode_cursor(cursor: str) -> tuple[datetime, uuid.UUID]:
    try:
        padded = cursor + "=" * (-len(cursor) % 4)
        stamp, _, ident = base64.urlsafe_b64decode(padded).decode().partition("|")
        return datetime.fromisoformat(stamp), uuid.UUID(ident)
    except (ValueError, binascii.Error, UnicodeDecodeError) as error:
        raise ServiceError(
            422,
            "Bad cursor",
            "The cursor is not one this API gave out; start again without it.",
            type_="urn:quantsim:problem:invalid-cursor",
        ) from error
