from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, EmailStr, Field

from app.modules.auth.service import MAX_PASSWORD_LENGTH
from app.modules.organisations.permissions import OrganisationKind, Permission, Role


class OrganisationCreate(BaseModel):
    name: str = Field(min_length=1, max_length=200, pattern=r"\S")
    kind: OrganisationKind


class OrganisationOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    name: str
    kind: OrganisationKind
    created_at: datetime


class CurrentOrganisationOut(OrganisationOut):
    """The active organisation plus what the caller may do in it (for building navigation)."""

    # None when a platform administrator acts in an organisation they do not belong to.
    my_role: Role | None
    my_permissions: list[Permission]
    assignable_roles: list[Role]


class MemberOut(BaseModel):
    user_id: UUID
    email: str
    full_name: str
    role: Role
    joined_at: datetime


class RoleChange(BaseModel):
    role: Role


class InvitationCreate(BaseModel):
    email: EmailStr
    role: Role


class InvitationOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    email: str
    role: Role
    created_at: datetime
    expires_at: datetime


class InvitationCreated(InvitationOut):
    """`token` is shown once. Build the link from it and send it to the invited person."""

    token: str


class InvitationToken(BaseModel):
    token: str = Field(min_length=1, max_length=200)


class InvitationPreview(BaseModel):
    organisation_name: str
    email: str
    role: Role
    account_exists: bool


class InvitationAccept(InvitationToken):
    # Required only when the invited email has no account yet.
    full_name: str | None = Field(default=None, max_length=200)
    password: str | None = Field(default=None, max_length=MAX_PASSWORD_LENGTH)


class InvitationAccepted(BaseModel):
    organisation_name: str
    email: str
    account_created: bool
