from collections.abc import Sequence
from datetime import UTC, datetime, timedelta
from uuid import UUID

from sqlalchemy import ColumnElement, select, update
from sqlalchemy.orm import Session

from app.core.errors import AppError, ErrorDetail
from app.core.pagination import PageParams, paginate
from app.modules.auth import service as auth
from app.modules.auth.models import User
from app.modules.organisations.models import Invitation, Membership, Organisation
from app.modules.organisations.permissions import ALLOWED_ROLES

INVITATION_TTL = timedelta(days=7)


def create_organisation(session: Session, *, name: str, kind: str) -> Organisation:
    organisation = Organisation(name=name.strip(), kind=kind)
    session.add(organisation)
    session.flush()
    return organisation


def _check_role(organisation: Organisation, role: str) -> None:
    allowed = ALLOWED_ROLES[organisation.kind]
    if role not in allowed:
        raise AppError(
            422,
            "validation_error",
            "Request validation failed.",
            [
                ErrorDetail(
                    field="role",
                    message=f"A {organisation.kind} organisation allows: {', '.join(allowed)}.",
                )
            ],
        )


def add_member(session: Session, *, user_id: UUID, organisation_id: UUID, role: str) -> Membership:
    membership = Membership(user_id=user_id, organisation_id=organisation_id, role=role)
    session.add(membership)
    session.flush()
    return membership


def get_organisation(session: Session, organisation_id: UUID) -> Organisation | None:
    return session.get(Organisation, organisation_id)


def get_membership(session: Session, organisation_id: UUID, user_id: UUID) -> Membership | None:
    return session.scalar(
        select(Membership).where(
            Membership.organisation_id == organisation_id, Membership.user_id == user_id
        )
    )


def _member_or_404(session: Session, organisation_id: UUID, user_id: UUID) -> Membership:
    membership = get_membership(session, organisation_id, user_id)
    if membership is None:
        raise AppError(404, "not_found", "This user is not a member of the organisation.")
    return membership


def change_role(
    session: Session, organisation: Organisation, *, user_id: UUID, role: str, actor: User
) -> tuple[Membership, str]:
    """Return the membership and its previous role."""
    if user_id == actor.id:
        # Also guarantees an administrator can never remove the last administrator: themselves.
        raise AppError(409, "cannot_change_self", "You cannot change your own role.")
    _check_role(organisation, role)
    membership = _member_or_404(session, organisation.id, user_id)
    previous = membership.role
    membership.role = role
    session.flush()
    return membership, previous


def remove_member(
    session: Session, organisation_id: UUID, *, user_id: UUID, actor: User
) -> Membership:
    if user_id == actor.id:
        raise AppError(409, "cannot_change_self", "You cannot remove yourself.")
    membership = _member_or_404(session, organisation_id, user_id)
    session.delete(membership)
    session.flush()
    return membership


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


# --- Invitations ---------------------------------------------------------------------------


def _pending(now: datetime) -> tuple[ColumnElement[bool], ...]:
    return (
        Invitation.accepted_at.is_(None),
        Invitation.revoked_at.is_(None),
        Invitation.expires_at > now,
    )


def create_invitation(
    session: Session, organisation: Organisation, *, email: str, role: str, invited_by: User
) -> tuple[Invitation, str]:
    """Return the invitation and its link token. The token is not stored and cannot be re-read."""
    _check_role(organisation, role)
    email = auth.normalise_email(email)
    existing_user = auth.get_user_by_email(session, email)
    if existing_user and get_membership(session, organisation.id, existing_user.id):
        raise AppError(409, "already_member", "This person is already a member.")

    now = datetime.now(UTC)
    # A new invitation replaces an earlier pending one for the same person.
    session.execute(
        update(Invitation)
        .where(
            Invitation.organisation_id == organisation.id, Invitation.email == email, *_pending(now)
        )
        .values(revoked_at=now)
    )
    token, token_hash = auth.new_token()
    invitation = Invitation(
        organisation_id=organisation.id,
        email=email,
        role=role,
        token_hash=token_hash,
        invited_by_user_id=invited_by.id,
        expires_at=now + INVITATION_TTL,
    )
    session.add(invitation)
    session.flush()
    return invitation, token


def list_pending_invitations(
    session: Session, organisation_id: UUID, page: PageParams
) -> tuple[Sequence[Invitation], str | None]:
    stmt = select(Invitation).where(
        Invitation.organisation_id == organisation_id, *_pending(datetime.now(UTC))
    )
    return paginate(session, stmt, page, sort=Invitation.created_at, id_column=Invitation.id)


def revoke_invitation(session: Session, organisation_id: UUID, invitation_id: UUID) -> Invitation:
    now = datetime.now(UTC)
    invitation = session.scalar(
        select(Invitation).where(
            Invitation.id == invitation_id,
            # Scoped to the active organisation: another tenant's invitation is "not found".
            Invitation.organisation_id == organisation_id,
            *_pending(now),
        )
    )
    if invitation is None:
        raise AppError(404, "not_found", "No pending invitation with this ID.")
    invitation.revoked_at = now
    session.flush()
    return invitation


def find_invitation(
    session: Session, token: str, *, lock: bool = False
) -> tuple[Invitation, Organisation]:
    stmt = (
        select(Invitation, Organisation)
        .join(Organisation, Organisation.id == Invitation.organisation_id)
        .where(Invitation.token_hash == auth.hash_token(token), *_pending(datetime.now(UTC)))
    )
    if lock:
        stmt = stmt.with_for_update(of=Invitation)
    row = session.execute(stmt).first()
    if row is None:
        raise auth.invalid_link()
    return row[0], row[1]


def accept_invitation(
    session: Session, *, token: str, full_name: str | None, password: str | None
) -> tuple[Invitation, User, bool]:
    """Join the inviting organisation. Returns `(invitation, user, account_was_created)`.

    Holding the link is enough to accept: it adds a membership to the invited email's
    account but never signs anyone in, so it cannot be used to take over an account.
    """
    invitation, _ = find_invitation(session, token, lock=True)
    user = auth.get_user_by_email(session, invitation.email)
    created = user is None
    if user is None:
        missing = [
            ErrorDetail(field=field, message="Required to create your account.")
            for field, value in (("full_name", full_name), ("password", password))
            if not value or not value.strip()
        ]
        if missing or full_name is None or password is None:
            raise AppError(422, "validation_error", "Request validation failed.", missing)
        user = auth.create_user(
            session, email=invitation.email, full_name=full_name, password=password
        )
    elif not user.is_active:
        raise auth.invalid_link()
    if get_membership(session, invitation.organisation_id, user.id):
        raise AppError(409, "already_member", "You are already a member of this organisation.")
    add_member(
        session, user_id=user.id, organisation_id=invitation.organisation_id, role=invitation.role
    )
    invitation.accepted_at = datetime.now(UTC)
    session.flush()
    return invitation, user, created
