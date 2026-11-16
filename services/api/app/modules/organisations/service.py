from collections.abc import Sequence
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.pagination import PageParams, paginate
from app.modules.organisations.models import Membership, Organisation


def create_organisation(session: Session, *, name: str, kind: str) -> Organisation:
    organisation = Organisation(name=name.strip(), kind=kind)
    session.add(organisation)
    session.flush()
    return organisation


def add_member(session: Session, *, user_id: UUID, organisation_id: UUID, role: str) -> Membership:
    membership = Membership(user_id=user_id, organisation_id=organisation_id, role=role)
    session.add(membership)
    session.flush()
    return membership


def get_organisation(session: Session, organisation_id: UUID) -> Organisation | None:
    return session.get(Organisation, organisation_id)


def list_memberships(session: Session, user_id: UUID) -> Sequence[tuple[Membership, Organisation]]:
    rows = session.execute(
        select(Membership, Organisation)
        .join(Organisation, Organisation.id == Membership.organisation_id)
        .where(Membership.user_id == user_id)
        .order_by(Organisation.name, Organisation.id)
    ).all()
    return [(row[0], row[1]) for row in rows]


def list_organisations(
    session: Session, page: PageParams, *, member_user_id: UUID | None
) -> tuple[Sequence[Organisation], str | None]:
    """Organisations the user belongs to; every organisation when `member_user_id` is None."""
    stmt = select(Organisation)
    if member_user_id is not None:
        stmt = stmt.where(
            Organisation.id.in_(
                select(Membership.organisation_id).where(Membership.user_id == member_user_id)
            )
        )
    return paginate(session, stmt, page, sort=Organisation.created_at, id_column=Organisation.id)


def list_members(
    session: Session, organisation_id: UUID, page: PageParams
) -> tuple[Sequence[Membership], str | None]:
    stmt = select(Membership).where(Membership.organisation_id == organisation_id)
    return paginate(session, stmt, page, sort=Membership.created_at, id_column=Membership.id)
