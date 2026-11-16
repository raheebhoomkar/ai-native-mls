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
