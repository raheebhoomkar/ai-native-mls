from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from app.modules.auth.service import MAX_PASSWORD_LENGTH
from app.modules.organisations.permissions import OrganisationKind, Role


class LoginRequest(BaseModel):
    email: str = Field(min_length=3, max_length=320)
    password: str = Field(min_length=1, max_length=MAX_PASSWORD_LENGTH)


class UserOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    email: str
    full_name: str
    is_platform_admin: bool


class MembershipOut(BaseModel):
    organisation_id: UUID
    organisation_name: str
    organisation_kind: OrganisationKind
    role: Role


class MeResponse(BaseModel):
    user: UserOut
    memberships: list[MembershipOut]


class ProfileUpdate(BaseModel):
    full_name: str = Field(min_length=1, max_length=200, pattern=r"\S")


class PasswordChange(BaseModel):
    current_password: str = Field(min_length=1, max_length=MAX_PASSWORD_LENGTH)
    new_password: str = Field(min_length=1, max_length=MAX_PASSWORD_LENGTH)


class PasswordResetIssue(BaseModel):
    email: str = Field(min_length=3, max_length=320)


class PasswordResetIssued(BaseModel):
    """`token` is shown once. Build the link from it and hand it to the user."""

    email: str
    token: str
    expires_in_hours: int


class PasswordResetComplete(BaseModel):
    token: str = Field(min_length=1, max_length=200)
    new_password: str = Field(min_length=1, max_length=MAX_PASSWORD_LENGTH)
