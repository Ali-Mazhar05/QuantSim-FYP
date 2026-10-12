"""Account emails: written to ``mail_outbox`` in the same transaction as the change that
causes them, then sent over SMTP by the relay worker (design D4).

A rolled-back change therefore never sends mail, and mail queued while the SMTP server
is down goes out when it returns. Rows hold the emailed link, so they are deleted a
week after sending. Links and passwords are never logged.
"""

import asyncio
import smtplib
import ssl
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from email.message import EmailMessage
from email.utils import make_msgid
from html import escape
from typing import Any

from sqlalchemy import delete, insert, or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from qs_platform.models import mail_outbox
from qs_platform.settings import PlatformSettings
from qs_template import Database
from qs_template.logging import get_logger

log = get_logger(__name__)

# Retry with growing delays (30 s, doubling, at most an hour) for a day, then give up
FIRST_RETRY_SECONDS = 30
MAX_RETRY_SECONDS = 3600
GIVE_UP_AFTER = timedelta(hours=24)
KEEP_SENT_FOR = timedelta(days=7)
BATCH_SIZE = 20


@dataclass(frozen=True)
class Template:
    subject: str
    intro: str
    button: str | None
    outro: str


TEMPLATES: dict[str, Template] = {
    "verify_email": Template(
        "Verify your QuantSim email",
        "Hi {username}, confirm this is your email address to finish creating your "
        "QuantSim account.",
        "Verify email",
        "The link works once and expires in 24 hours. If you did not sign up, ignore this email.",
    ),
    "account_exists": Template(
        "You already have a QuantSim account",
        "Someone tried to create a QuantSim account with this email address, but it "
        "already has an account ({username}).",
        "Sign in",
        'If you forgot your password, use "Forgot password?" on the sign-in page. If this '
        "was not you, ignore this email.",
    ),
    "invite": Template(
        "You have been invited to QuantSim",
        "Hi {username}, an administrator created a QuantSim account for you with the "
        "{role} role. Set your password to start.",
        "Set password",
        "The link works once and expires in 72 hours.",
    ),
    "reset_password": Template(
        "Change your QuantSim password",
        "Hi {username}, we received a request to change your QuantSim password.",
        "Change password",
        "The link works once and expires in 1 hour. Changing the password signs you out "
        "everywhere. If you did not ask for this, ignore this email.",
    ),
    "approved": Template(
        "Your QuantSim account is approved",
        "Hi {username}, an administrator approved your {role} account. You can sign in now.",
        "Sign in",
        "",
    ),
}


async def queue_mail(session: AsyncSession, to: str, template: str, params: dict[str, str]) -> None:
    """Queue an email in the caller's transaction. ``params`` fill the template and must
    include ``link`` when the template has a button."""
    if template not in TEMPLATES:
        raise ValueError(f"unknown mail template {template}")
    await session.execute(
        insert(mail_outbox).values(to_address=to, template=template, params=params)
    )


def render(
    settings: PlatformSettings, to: str, template: str, params: dict[str, Any]
) -> EmailMessage:
    spec = TEMPLATES[template]
    values = {k: str(v) for k, v in params.items()}
    intro = spec.intro.format(**values)
    outro = spec.outro.format(**values)
    link = values.get("link", "")

    message = EmailMessage()
    message["Subject"] = spec.subject
    message["From"] = settings.smtp_from
    message["To"] = to
    message["Message-ID"] = make_msgid(domain="quantsim.local")

    text_parts = [intro]
    if spec.button and link:
        text_parts.append(f"{spec.button}: {link}")
    if outro:
        text_parts.append(outro)
    message.set_content("\n\n".join(text_parts) + "\n\n- QuantSim\n")

    button = ""
    if spec.button and link:
        button = (
            f'<p style="margin:24px 0"><a href="{escape(link)}" style="background:#3b82f6;'
            "color:#ffffff;padding:10px 18px;border-radius:4px;text-decoration:none;"
            f'font-weight:600;display:inline-block">{escape(spec.button)}</a></p>'
            f'<p style="font-size:12px;color:#6b7280">Or open this link: '
            f'<a href="{escape(link)}" style="color:#3b82f6">{escape(link)}</a></p>'
        )
    message.add_alternative(
        '<div style="font-family:Segoe UI,Arial,sans-serif;max-width:520px;margin:auto;'
        'padding:24px;color:#111827">'
        '<h2 style="margin:0 0 16px;font-size:18px">QuantSim</h2>'
        f"<p>{escape(intro)}</p>{button}"
        + (f'<p style="font-size:13px;color:#4b5563">{escape(outro)}</p>' if outro else "")
        + "</div>",
        subtype="html",
    )
    return message


Transport = Callable[[EmailMessage], Awaitable[None]]


def smtp_transport(settings: PlatformSettings) -> Transport:
    """Sends through the configured SMTP server; the blocking client runs in a thread."""
    host = settings.smtp_host
    if not host:
        raise ValueError("QS_SMTP_HOST is not set")

    def send(message: EmailMessage) -> None:
        context = ssl.create_default_context()
        if settings.smtp_security == "tls":
            client: smtplib.SMTP = smtplib.SMTP_SSL(
                host, settings.smtp_port, timeout=30, context=context
            )
        else:
            client = smtplib.SMTP(host, settings.smtp_port, timeout=30)
        with client:
            if settings.smtp_security == "starttls":
                client.starttls(context=context)
            if settings.smtp_username and settings.smtp_password:
                client.login(settings.smtp_username, settings.smtp_password.get_secret_value())
            client.send_message(message)

    async def transport(message: EmailMessage) -> None:
        await asyncio.to_thread(send, message)

    return transport


class MailSender:
    """Sends due rows of ``mail_outbox`` until stopped."""

    def __init__(
        self,
        database: Database,
        settings: PlatformSettings,
        transport: Transport,
        *,
        poll_seconds: float = 5.0,
    ) -> None:
        self._database = database
        self._settings = settings
        self._transport = transport
        self._poll_seconds = poll_seconds
        self._stopping = asyncio.Event()

    async def send_due(self, now: datetime | None = None) -> int:
        """Send one batch of due mail; returns how many were sent."""
        now = now or datetime.now(UTC)
        sent = 0
        async with self._database.transaction() as session:
            rows = (
                await session.execute(
                    select(mail_outbox)
                    .where(
                        mail_outbox.c.sent_at.is_(None),
                        mail_outbox.c.failed_at.is_(None),
                        mail_outbox.c.next_attempt_at <= now,
                    )
                    .order_by(mail_outbox.c.id)
                    .limit(BATCH_SIZE)
                    .with_for_update(skip_locked=True)
                )
            ).all()
            for row in rows:
                try:
                    message = render(self._settings, row.to_address, row.template, row.params)
                    await self._transport(message)
                except Exception as exc:  # any failure is retried later
                    await self._failed(session, row, now, exc)
                    continue
                await session.execute(
                    update(mail_outbox)
                    .where(mail_outbox.c.id == row.id)
                    .values(sent_at=now, attempts=row.attempts + 1, last_error=None)
                )
                log.info("account email sent", mail_id=row.id, template=row.template)
                sent += 1
        return sent

    async def _failed(self, session: AsyncSession, row: Any, now: datetime, exc: Exception) -> None:
        attempts = row.attempts + 1
        # Only the exception type and a short message: never the link
        error = f"{type(exc).__name__}: {str(exc)[:200]}"
        if now - row.created_at >= GIVE_UP_AFTER:
            values: dict[str, Any] = {"failed_at": now}
            log.error("account email given up", mail_id=row.id, template=row.template, error=error)
        else:
            delay = min(FIRST_RETRY_SECONDS * 2 ** (attempts - 1), MAX_RETRY_SECONDS)
            values = {"next_attempt_at": now + timedelta(seconds=delay)}
            log.warning(
                "account email failed; will retry",
                mail_id=row.id,
                template=row.template,
                retry_in_seconds=delay,
                error=error,
            )
        await session.execute(
            update(mail_outbox)
            .where(mail_outbox.c.id == row.id)
            .values(attempts=attempts, last_error=error, **values)
        )

    async def purge(self, now: datetime | None = None) -> int:
        """Delete mail sent or given up more than a week ago (the rows hold links)."""
        cutoff = (now or datetime.now(UTC)) - KEEP_SENT_FOR
        async with self._database.transaction() as session:
            result = await session.execute(
                delete(mail_outbox).where(
                    or_(mail_outbox.c.sent_at < cutoff, mail_outbox.c.failed_at < cutoff)
                )
            )
        return int(result.rowcount or 0)  # type: ignore[attr-defined]

    async def run(self) -> None:
        while not self._stopping.is_set():
            try:
                await self.send_due()
            except Exception as exc:  # keep the worker alive
                log.error("mail sender error", error=str(exc))
            try:
                await asyncio.wait_for(self._stopping.wait(), timeout=self._poll_seconds)
            except TimeoutError:
                pass

    def stop(self) -> None:
        self._stopping.set()
