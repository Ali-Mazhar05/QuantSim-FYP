"""Settings of the Platform service, on top of the template's (all ``QS_*``)."""

import base64

from pydantic import Field, SecretStr, field_validator

from qs_template import ServiceSettings


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

    # Redis holding the shared token revocation list
    redis_url: SecretStr

    # Brute-force protection on login
    login_max_failures: int = Field(default=5, ge=1, le=20)
    login_lockout_seconds: int = Field(default=900, ge=10, le=86_400)

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

    @property
    def signing_key_pem(self) -> bytes:
        return base64.b64decode(self.signing_key.get_secret_value())
