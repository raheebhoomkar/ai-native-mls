import hashlib
import secrets
from datetime import UTC, datetime, timedelta
from uuid import UUID

from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError
from sqlalchemy import select, update
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.errors import AppError, ErrorDetail
from app.modules.auth.models import AuthSession, PasswordResetToken, User

MIN_PASSWORD_LENGTH = 12
# Upper bound keeps a huge password from tying up the hasher.
MAX_PASSWORD_LENGTH = 128
PASSWORD_RESET_TTL = timedelta(hours=24)

_hasher = PasswordHasher()
# Verified when the account does not exist, so response time does not reveal which emails exist.
_DUMMY_HASH = _hasher.hash(secrets.token_urlsafe(16))


def normalise_email(email: str) -> str:
    return email.strip().lower()


def hash_token(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def new_token() -> tuple[str, str]:
    """Return `(token, token_hash)`. Give the token to the user once; store only the hash."""
    token = secrets.token_urlsafe(32)
    return token, hash_token(token)


def invalid_link() -> AppError:
    return AppError(400, "invalid_token", "This link is invalid or has expired.")


def _hash_password(password: str, field: str = "password") -> str:
    if not MIN_PASSWORD_LENGTH <= len(password) <= MAX_PASSWORD_LENGTH:
        raise AppError(
            422,
            "validation_error",
            "Request validation failed.",
            [
                ErrorDetail(
                    field=field,
                    message=f"Must be {MIN_PASSWORD_LENGTH} to {MAX_PASSWORD_LENGTH} characters.",
                )
            ],
        )
    return _hasher.hash(password)


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
    password_hash = _hash_password(password)
    if get_user_by_email(session, email) is not None:
        raise AppError(409, "email_taken", "A user with this email already exists.")
    user = User(
        email=normalise_email(email),
        full_name=full_name.strip(),
        password_hash=password_hash,
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
    token, token_hash = new_token()
    ttl = timedelta(hours=get_settings().session_ttl_hours)
    session.add(
        AuthSession(user_id=user.id, token_hash=token_hash, expires_at=datetime.now(UTC) + ttl)
    )
    session.flush()
    return token


def resolve_session(session: Session, token: str) -> tuple[AuthSession, User] | None:
    row = session.execute(
        select(AuthSession, User)
        .join(User, User.id == AuthSession.user_id)
        .where(
            AuthSession.token_hash == hash_token(token),
            AuthSession.revoked_at.is_(None),
            AuthSession.expires_at > datetime.now(UTC),
            User.is_active,
        )
    ).first()
    return (row[0], row[1]) if row else None


def revoke_session(session: Session, auth_session: AuthSession) -> None:
    auth_session.revoked_at = datetime.now(UTC)
    session.flush()


def revoke_all_sessions(
    session: Session, user_id: UUID, *, keep: AuthSession | None = None
) -> None:
    stmt = (
        update(AuthSession)
        .where(AuthSession.user_id == user_id, AuthSession.revoked_at.is_(None))
        .values(revoked_at=datetime.now(UTC))
    )
    if keep is not None:
        stmt = stmt.where(AuthSession.id != keep.id)
    session.execute(stmt)


def update_profile(session: Session, user: User, *, full_name: str) -> None:
    user.full_name = full_name.strip()
    session.flush()


def change_password(
    session: Session, user: User, *, current_password: str, new_password: str, keep: AuthSession
) -> None:
    """Change the signed-in user's password and sign out their other sessions."""
    try:
        _hasher.verify(user.password_hash, current_password)
    except (VerificationError, InvalidHashError):
        raise AppError(
            422,
            "validation_error",
            "Request validation failed.",
            [ErrorDetail(field="current_password", message="The current password is not correct.")],
        ) from None
    user.password_hash = _hash_password(new_password, "new_password")
    revoke_all_sessions(session, user.id, keep=keep)
    session.flush()


def issue_password_reset(session: Session, user: User, *, created_by: User) -> str:
    """Create a one-time reset link token, replacing any earlier unused one."""
    now = datetime.now(UTC)
    session.execute(
        update(PasswordResetToken)
        .where(PasswordResetToken.user_id == user.id, PasswordResetToken.used_at.is_(None))
        .values(used_at=now)
    )
    token, token_hash = new_token()
    session.add(
        PasswordResetToken(
            user_id=user.id,
            token_hash=token_hash,
            created_by_user_id=created_by.id,
            expires_at=now + PASSWORD_RESET_TTL,
        )
    )
    session.flush()
    return token


def complete_password_reset(session: Session, *, token: str, new_password: str) -> User:
    now = datetime.now(UTC)
    row = session.execute(
        select(PasswordResetToken, User)
        .join(User, User.id == PasswordResetToken.user_id)
        .where(
            PasswordResetToken.token_hash == hash_token(token),
            PasswordResetToken.used_at.is_(None),
            PasswordResetToken.expires_at > now,
            User.is_active,
        )
        .with_for_update(of=PasswordResetToken)
    ).first()
    if row is None:
        raise invalid_link()
    reset, user = row[0], row[1]
    user.password_hash = _hash_password(new_password, "new_password")
    reset.used_at = now
    revoke_all_sessions(session, user.id)
    session.flush()
    return user
