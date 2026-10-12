"""The mail outbox and its sender (spec: account-email, design D4 and D5)."""

from datetime import UTC, datetime, timedelta
from email.message import EmailMessage

import pytest
from pydantic import ValidationError
from sqlalchemy import select, text

from qs_platform.mail import MailSender, queue_mail, render
from qs_platform.models import mail_outbox
from qs_template import Database
from tests.conftest import make_settings

pytestmark = pytest.mark.db

LINK = "http://localhost:5173/set-password#token=secret-token-value&purpose=reset"


class FakeTransport:
    def __init__(self, failures: int = 0) -> None:
        self.sent: list[EmailMessage] = []
        self.failures = failures

    async def __call__(self, message: EmailMessage) -> None:
        if self.failures:
            self.failures -= 1
            raise ConnectionRefusedError("smtp down")
        self.sent.append(message)


async def queue(database: Database) -> None:
    async with database.transaction() as session:
        await queue_mail(
            session, "sara@gmail.com", "reset_password", {"username": "sara.k", "link": LINK}
        )


async def outbox_row(database: Database) -> object:
    async with database.transaction() as session:
        return (await session.execute(select(mail_outbox))).one()


async def test_a_rolled_back_change_queues_no_mail(database: Database) -> None:
    with pytest.raises(RuntimeError):
        async with database.transaction() as session:
            await queue_mail(
                session, "sara@gmail.com", "verify_email", {"username": "s", "link": LINK}
            )
            raise RuntimeError("the sign-up failed")

    async with database.transaction() as session:
        count = (await session.execute(text("SELECT count(*) FROM mail_outbox"))).scalar_one()
    assert count == 0


async def test_due_mail_is_sent_once_with_the_sender_and_the_button_link(
    database: Database,
) -> None:
    await queue(database)
    transport = FakeTransport()
    sender = MailSender(database, make_settings(), transport)

    assert await sender.send_due() == 1
    assert await sender.send_due() == 0

    (message,) = transport.sent
    assert message["From"] == "QuantSim <alimazhar+QuantSim@gmail.com>"
    assert message["To"] == "sara@gmail.com"
    assert message["Subject"] == "Change your QuantSim password"
    html = message.get_body(("html",))
    assert html is not None
    assert "Change password" in html.get_content()
    assert LINK.replace("&", "&amp;") in html.get_content()
    row = await outbox_row(database)
    assert row.sent_at is not None  # type: ignore[attr-defined]


async def test_failures_are_retried_with_growing_delays_then_given_up(
    database: Database, capsys: pytest.CaptureFixture[str]
) -> None:
    await queue(database)
    transport = FakeTransport(failures=100)
    sender = MailSender(database, make_settings(), transport)
    start = datetime.now(UTC)

    await sender.send_due(now=start)
    first = await outbox_row(database)
    await sender.send_due(now=first.next_attempt_at)  # type: ignore[attr-defined]
    second = await outbox_row(database)

    first_delay = first.next_attempt_at - start  # type: ignore[attr-defined]
    second_delay = second.next_attempt_at - first.next_attempt_at  # type: ignore[attr-defined]
    assert first_delay == timedelta(seconds=30)
    assert second_delay == timedelta(seconds=60)
    assert second.failed_at is None  # type: ignore[attr-defined]

    await sender.send_due(now=start + timedelta(hours=25))
    given_up = await outbox_row(database)
    assert given_up.failed_at is not None  # type: ignore[attr-defined]
    assert "secret-token-value" not in capsys.readouterr().out


async def test_mail_queued_while_smtp_is_down_goes_out_when_it_returns(
    database: Database,
) -> None:
    await queue(database)
    transport = FakeTransport(failures=1)
    sender = MailSender(database, make_settings(), transport)

    await sender.send_due()
    row = await outbox_row(database)
    await sender.send_due(now=row.next_attempt_at)  # type: ignore[attr-defined]

    assert len(transport.sent) == 1


async def test_sent_mail_is_purged_after_a_week(database: Database) -> None:
    await queue(database)
    sender = MailSender(database, make_settings(), FakeTransport())
    await sender.send_due()

    assert await sender.purge(now=datetime.now(UTC) + timedelta(days=6)) == 0
    assert await sender.purge(now=datetime.now(UTC) + timedelta(days=8)) == 1


def test_every_template_renders_text_and_html() -> None:
    settings = make_settings()
    for template in ("verify_email", "account_exists", "invite", "reset_password", "approved"):
        message = render(
            settings, "a@b.c", template, {"username": "sara.k", "role": "Quant", "link": LINK}
        )
        assert message.get_body(("plain",)) is not None
        assert message.get_body(("html",)) is not None


def test_the_service_refuses_to_start_without_smtp_where_email_is_required() -> None:
    with pytest.raises(ValidationError, match="QS_SMTP_PASSWORD"):
        make_settings(email_required=True, smtp_host="smtp.gmail.com", smtp_username="x")
