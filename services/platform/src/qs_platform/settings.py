"""Settings of the Platform service, on top of the template's (all ``QS_*``)."""

import base64
import hashlib
from typing import Literal, Self

from pydantic import Field, SecretStr, field_validator, model_validator

from qs_template import ServiceSettings
from qs_template.auth import KNOWN_SERVICES

MIN_CLIENT_SECRET_LENGTH = 32


class PlatformSettings(ServiceSettings):
    service_name: str = "platform"

    # RS256 private key that signs access tokens: PEM, base64-encoded so it fits in one
    # environment variable. Generate with: qs-platform generate-signing-key
    signing_key: SecretStr
    signing_key_id: str = Field(min_length=1, pattern=r"^[A-Za-z0-9._-]+$")
    # Public keys of retired signing keys (a JWKS JSON document), still published so
    # tokens they signed stay valid until they expire
    retired_public_keys: str | None = None

    access_token_ttl_seconds: int = Field(default=900, ge=60, le=3600)
    # Refresh tokens slide: each refresh issues a new one valid for this long
    refresh_token_ttl_seconds: int = Field(default=43_200, ge=300, le=2_592_000)

    # Services that may get service tokens (ADR 09): comma-separated name=secret pairs,
    # e.g. "trading=<64 hex>". A pair with an empty secret is ignored (client disabled).
    service_client_secrets: SecretStr | None = None
    service_token_ttl_seconds: int = Field(default=600, ge=60, le=900)

    # Redis holding the shared token revocation list
    redis_url: SecretStr

    # Brute-force protection on login
    login_max_failures: int = Field(default=5, ge=1, le=20)
    login_lockout_seconds: int = Field(default=900, ge=10, le=86_400)

    # Self sign-up (viewer, analyst, quant); off answers 404 and leaves everything else
    signup_enabled: bool = True
    # Sign-up, resend-verification and forgot-password attempts per client address
    signup_rate_limit: int = Field(default=10, ge=1, le=1000)
    signup_rate_window_seconds: int = Field(default=3600, ge=60, le=86_400)
    # Account emails to one address per window, whatever asks for them
    mail_per_address_limit: int = Field(default=3, ge=1, le=100)
    mail_per_address_window_seconds: int = Field(default=3600, ge=60, le=86_400)
    # Self sign-ups still unverified after this many days are removed
    unverified_retention_days: int = Field(default=7, ge=1, le=90)

    # The environment's website; emailed links point here
    public_app_url: str = "http://localhost:5173"

    # Outgoing mail. DEV and TEST use the environment's Mailpit; ACC and PROD use Gmail
    smtp_host: str | None = None
    smtp_port: int = Field(default=587, ge=1, le=65_535)
    smtp_security: Literal["starttls", "tls", "none"] = "starttls"
    smtp_username: str | None = None
    smtp_password: SecretStr | None = None
    smtp_from: str = "QuantSim <alimazhar3005+QuantSim@gmail.com>"
    # True where real mail must go out (ACC, PROD): refuse to start without SMTP settings
    email_required: bool = False

    @field_validator("signing_key")
    @classmethod
    def _decodes_to_pem(cls, value: SecretStr) -> SecretStr:
        try:
            pem = base64.b64decode(value.get_secret_value(), validate=True)
        except ValueError as exc:
            raise ValueError("QS_SIGNING_KEY must be base64-encoded PEM") from exc
        if b"PRIVATE KEY" not in pem:
            raise ValueError("QS_SIGNING_KEY must contain a PEM private key")
        return value

    @field_validator("service_client_secrets")
    @classmethod
    def _valid_service_clients(cls, value: SecretStr | None) -> SecretStr | None:
        if value is not None:
            _parse_service_clients(value.get_secret_value())
        return value

    @model_validator(mode="after")
    def _mail_configured_when_required(self) -> Self:
        if self.email_required:
            missing = [
                name
                for name, value in (
                    ("QS_SMTP_HOST", self.smtp_host),
                    ("QS_SMTP_USERNAME", self.smtp_username),
                    ("QS_SMTP_PASSWORD", self.smtp_password),
                )
                if not value
            ]
            if missing:
                raise ValueError(
                    "email is required in this environment but "
                    + ", ".join(missing)
                    + " is not set"
                )
        return self

    @property
    def service_client_digests(self) -> dict[str, bytes]:
        """SHA-256 of each service's client secret; the secrets themselves are not kept."""
        if self.service_client_secrets is None:
            return {}
        return {
            name: hashlib.sha256(secret.encode()).digest()
            for name, secret in _parse_service_clients(
                self.service_client_secrets.get_secret_value()
            ).items()
        }

    @property
    def app_url(self) -> str:
        return self.public_app_url.rstrip("/")

    @property
    def signing_key_pem(self) -> bytes:
        return base64.b64decode(self.signing_key.get_secret_value())


def _parse_service_clients(raw: str) -> dict[str, str]:
    """``name=secret,name=secret`` into a dict; never puts a secret in an error."""
    clients: dict[str, str] = {}
    for entry in raw.split(","):
        entry = entry.strip()
        if not entry:
            continue
        name, sep, secret = entry.partition("=")
        name, secret = name.strip(), secret.strip()
        if not sep or name not in KNOWN_SERVICES:
            raise ValueError(
                "QS_SERVICE_CLIENT_SECRETS must be name=secret pairs naming known services"
                f" ({', '.join(sorted(KNOWN_SERVICES))})"
            )
        if name in clients:
            raise ValueError(f"QS_SERVICE_CLIENT_SECRETS names {name} twice")
        if not secret:
            continue
        if len(secret) < MIN_CLIENT_SECRET_LENGTH:
            raise ValueError(
                f"the client secret of {name} must be at least "
                f"{MIN_CLIENT_SECRET_LENGTH} characters"
            )
        clients[name] = secret
    return clients
