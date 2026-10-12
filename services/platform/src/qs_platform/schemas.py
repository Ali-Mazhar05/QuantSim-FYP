"""Request and response bodies of the Platform API (the published contract)."""

import uuid
from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, EmailStr, Field, computed_field, field_validator

from qs_template.auth import ROLE_CAPABILITIES, ROLE_RANK, Role

USERNAME_PATTERN = r"^[a-z0-9._-]{3,40}$"


class LoginRequest(BaseModel):
    # A username or an email address
    username: str = Field(min_length=1, max_length=254)
    password: str = Field(min_length=1, max_length=1024)


class TokenResponse(BaseModel):
    access_token: str
    token_type: Literal["Bearer"] = "Bearer"  # noqa: S105 - a scheme name, not a secret
    expires_in: int
    refresh_token: str
    refresh_expires_in: int
    user: "UserOut"


class RefreshRequest(BaseModel):
    refresh_token: str = Field(min_length=20, max_length=200)


class UserOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    username: str
    email: str
    display_name: str
    role: Role
    is_active: bool
    created_at: datetime
    last_login_at: datetime | None
    deactivated_at: datetime | None
    email_verified_at: datetime | None = None
    approved_at: datetime | None = None

    @computed_field  # type: ignore[prop-decorator]
    @property
    def status(self) -> Literal["active", "invited", "pending", "disabled"]:
        """As the Users page shows it: invited until the email is verified, pending until
        an admin approves a Quant or Analyst sign-up."""
        if not self.is_active:
            return "disabled"
        if self.email_verified_at is None:
            return "invited"
        return "active" if self.approved_at else "pending"


class MeOut(UserOut):
    """The signed-in user, with what their role allows, so the UI shows exactly that."""

    @computed_field  # type: ignore[prop-decorator]
    @property
    def capabilities(self) -> list[str]:
        return sorted(c.value for c in ROLE_CAPABILITIES[self.role])

    @computed_field  # type: ignore[prop-decorator]
    @property
    def role_rank(self) -> int:
        return ROLE_RANK[self.role]


class CreateUserRequest(BaseModel):
    """An admin invitation: the user sets their own password through the emailed link."""

    username: str = Field(pattern=USERNAME_PATTERN, description="lowercase, 3-40 characters")
    email: EmailStr
    display_name: str = Field(min_length=1, max_length=120)
    role: Role


class SignUpRequest(BaseModel):
    username: str = Field(pattern=USERNAME_PATTERN, description="lowercase, 3-40 characters")
    email: EmailStr
    password: str = Field(min_length=12, max_length=1024)
    # Admin is not a choice here; only an admin can make someone an admin
    account_type: Literal["viewer", "analyst", "quant"]

    @field_validator("username", mode="before")
    @classmethod
    def _lowercase(cls, value: object) -> object:
        return value.strip().lower() if isinstance(value, str) else value


class EmailRequest(BaseModel):
    email: EmailStr


class LinkTokenRequest(BaseModel):
    token: str = Field(min_length=20, max_length=200)


class ResetPasswordRequest(BaseModel):
    token: str = Field(min_length=20, max_length=200)
    password: str = Field(min_length=12, max_length=1024)


class MessageOut(BaseModel):
    message: str


class VerifyEmailOut(BaseModel):
    status: Literal["verified"] = "verified"
    # True for a Quant or Analyst sign-up that still waits for an admin
    approval_required: bool


class PasswordSetOut(BaseModel):
    status: Literal["password_set"] = "password_set"


class ChangeRoleRequest(BaseModel):
    role: Role


class UserList(BaseModel):
    items: list[UserOut]
    total: int


class AuditEntryOut(BaseModel):
    operation: str
    changed_by: str | None
    request_id: str | None
    changed_at: datetime
    changes: dict[str, Any]


TokenResponse.model_rebuild()
