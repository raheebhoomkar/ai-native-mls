import hashlib
import secrets
from datetime import UTC, datetime, timedelta
from uuid import UUID

from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.errors import AppError, ErrorDetail
from app.modules.auth.models import AuthSession, User

MIN_PASSWORD_LENGTH = 12
# Upper bound keeps a huge password from tying up the hasher.
MAX_PASSWORD_LENGTH = 128

_hasher = PasswordHasher()
# Verified when the account does not exist, so response time does not reveal which emails exist.
_DUMMY_HASH = _hasher.hash(secrets.token_urlsafe(16))


def normalise_email(email: str) -> str:
    return email.strip().lower()


def _hash_token(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def get_user_by_email(session: Session, email: str) -> User | None:
    return session.scalar(select(User).where(User.email == normalise_email(email)))


def get_users(session: Session, user_ids: list[UUID]) -> dict[UUID, User]:
    if not user_ids:
        return {}
    users = session.scalars(select(User).where(User.id.in_(user_ids)))
    return {user.id: user for user in users}


def create_user(
    session: Session,
    *,
    email: str,
    full_name: str,
    password: str,
    is_platform_admin: bool = False,
) -> User:
    if not MIN_PASSWORD_LENGTH <= len(password) <= MAX_PASSWORD_LENGTH:
        raise AppError(
            422,
            "validation_error",
            "Request validation failed.",
            [
                ErrorDetail(
                    field="password",
                    message=f"Must be {MIN_PASSWORD_LENGTH} to {MAX_PASSWORD_LENGTH} characters.",
                )
            ],
        )
    if get_user_by_email(session, email) is not None:
        raise AppError(409, "email_taken", "A user with this email already exists.")
    user = User(
        email=normalise_email(email),
        full_name=full_name.strip(),
        password_hash=_hasher.hash(password),
        is_platform_admin=is_platform_admin,
    )
    session.add(user)
    session.flush()
    return user


def authenticate(session: Session, email: str, password: str) -> User | None:
    """Return the user for valid credentials, otherwise None. Never says which part was wrong."""
    user = get_user_by_email(session, email)
    try:
        _hasher.verify(user.password_hash if user else _DUMMY_HASH, password)
    except (VerificationError, InvalidHashError):
        return None
    if user is None or not user.is_active:
        return None
    return user


def create_session(session: Session, user: User) -> str:
    """Start a login session and return the raw token for the cookie. It is not stored."""
    token = secrets.token_urlsafe(32)
    ttl = timedelta(hours=get_settings().session_ttl_hours)
    session.add(
        AuthSession(
            user_id=user.id, token_hash=_hash_token(token), expires_at=datetime.now(UTC) + ttl
        )
    )
    session.flush()
    return token


def resolve_session(session: Session, token: str) -> tuple[AuthSession, User] | None:
    row = session.execute(
        select(AuthSession, User)
        .join(User, User.id == AuthSession.user_id)
        .where(
            AuthSession.token_hash == _hash_token(token),
            AuthSession.revoked_at.is_(None),
            AuthSession.expires_at > datetime.now(UTC),
            User.is_active,
        )
    ).first()
    return (row[0], row[1]) if row else None


def revoke_session(session: Session, auth_session: AuthSession) -> None:
    auth_session.revoked_at = datetime.now(UTC)
    session.flush()
