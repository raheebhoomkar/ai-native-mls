from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from app.modules.organisations.permissions import OrganisationKind, Role


class OrganisationCreate(BaseModel):
    name: str = Field(min_length=1, max_length=200, pattern=r"\S")
    kind: OrganisationKind


class OrganisationOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    name: str
    kind: OrganisationKind
    created_at: datetime


class MemberOut(BaseModel):
    user_id: UUID
    email: str
    full_name: str
    role: Role
    joined_at: datetime
