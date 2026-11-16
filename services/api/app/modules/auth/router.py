from datetime import UTC, datetime, timedelta

from fastapi import APIRouter, Request, Response
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.db import SessionDep
from app.core.errors import AppError, ErrorResponse
from app.modules.audit import service as audit
from app.modules.auth import service
from app.modules.auth.deps import (
    SESSION_COOKIE,
    AuthenticatedDep,
    CurrentUser,
    PlatformAdmin,
    client_ip,
)
from app.modules.auth.models import User
from app.modules.auth.schemas import (
    LoginRequest,
    MembershipOut,
    MeResponse,
    PasswordChange,
    PasswordResetComplete,
    PasswordResetIssue,
    PasswordResetIssued,
    ProfileUpdate,
    UserOut,
)
from app.modules.organisations import service as organisations

router = APIRouter(prefix="/auth", tags=["auth"])

LOGIN_FAILED = "auth.login_failed"
RATE_WINDOW = timedelta(minutes=15)
MAX_FAILURES_PER_EMAIL = 10
MAX_FAILURES_PER_IP = 30


def _me(session: Session, user: User) -> MeResponse:
    return MeResponse(
        user=UserOut.model_validate(user),
        memberships=[
            MembershipOut(
                organisation_id=organisation.id,
                organisation_name=organisation.name,
                organisation_kind=organisation.kind,
                role=membership.role,
            )
            for membership, organisation in organisations.list_memberships(session, user.id)
        ],
    )


@router.post(
    "/login",
    responses={401: {"model": ErrorResponse}, 429: {"model": ErrorResponse}},
)
def login(
    body: LoginRequest, request: Request, response: Response, session: SessionDep
) -> MeResponse:
    """Start a session. The session token is set as an httpOnly cookie, not returned."""
    email = service.normalise_email(body.email)
    ip = client_ip(request)

    # Failed attempts are counted from the audit log, so the limit holds across processes.
    since = datetime.now(UTC) - RATE_WINDOW
    too_many = audit.count_recent(
        session, LOGIN_FAILED, since, target_id=email
    ) >= MAX_FAILURES_PER_EMAIL or (
        ip is not None
        and audit.count_recent(session, LOGIN_FAILED, since, ip_address=ip) >= MAX_FAILURES_PER_IP
    )
    if too_many:
        raise AppError(
            429, "rate_limited", "Too many failed sign-in attempts. Try again in 15 minutes."
        )

    user = service.authenticate(session, email, body.password)
    if user is None:
        audit.record(session, LOGIN_FAILED, target_type="email", target_id=email, ip_address=ip)
        session.commit()  # keep the audit event; the raise below would roll it back
        raise AppError(401, "invalid_credentials", "Invalid email or password.")

    token = service.create_session(session, user)
    audit.record(
        session,
        "auth.login",
        actor_user_id=user.id,
        target_type="user",
        target_id=str(user.id),
        ip_address=ip,
    )
    settings = get_settings()
    response.set_cookie(
        SESSION_COOKIE,
        token,
        max_age=settings.session_ttl_hours * 3600,
        httponly=True,
        samesite="lax",
        secure=settings.environment == "production",
        path="/",
    )
    return _me(session, user)


@router.post("/logout", status_code=204, responses={401: {"model": ErrorResponse}})
def logout(
    request: Request, response: Response, session: SessionDep, authenticated: AuthenticatedDep
) -> None:
    service.revoke_session(session, authenticated.auth_session)
    audit.record(
        session,
        "auth.logout",
        actor_user_id=authenticated.user.id,
        target_type="user",
        target_id=str(authenticated.user.id),
        ip_address=client_ip(request),
    )
    response.delete_cookie(SESSION_COOKIE, path="/")


@router.get("/me", responses={401: {"model": ErrorResponse}})
def me(session: SessionDep, user: CurrentUser) -> MeResponse:
    return _me(session, user)


@router.patch("/me", responses={401: {"model": ErrorResponse}})
def update_me(
    body: ProfileUpdate, request: Request, session: SessionDep, user: CurrentUser
) -> MeResponse:
    service.update_profile(session, user, full_name=body.full_name)
    audit.record(
        session,
        "user.profile_updated",
        actor_user_id=user.id,
        target_type="user",
        target_id=str(user.id),
        ip_address=client_ip(request),
    )
    return _me(session, user)


@router.post("/password", status_code=204, responses={401: {"model": ErrorResponse}})
def change_password(
    body: PasswordChange, request: Request, session: SessionDep, authenticated: AuthenticatedDep
) -> None:
    """Change your own password. Your other sessions are signed out."""
    user = authenticated.user
    service.change_password(
        session,
        user,
        current_password=body.current_password,
        new_password=body.new_password,
        keep=authenticated.auth_session,
    )
    audit.record(
        session,
        "auth.password_changed",
        actor_user_id=user.id,
        target_type="user",
        target_id=str(user.id),
        ip_address=client_ip(request),
    )


@router.post(
    "/password-reset-links",
    status_code=201,
    responses={401: {"model": ErrorResponse}, 403: {"model": ErrorResponse}},
)
def issue_password_reset(
    body: PasswordResetIssue, request: Request, session: SessionDep, admin: PlatformAdmin
) -> PasswordResetIssued:
    """Platform administrators only. Returns a one-time token to hand to the user.

    Organisation administrators cannot do this: a user may belong to several
    organisations, and resetting their password would give access to all of them.
    """
    user = service.get_user_by_email(session, body.email)
    if user is None or not user.is_active:
        raise AppError(404, "not_found", "No active user has this email.")
    token = service.issue_password_reset(session, user, created_by=admin)
    audit.record(
        session,
        "auth.password_reset_issued",
        actor_user_id=admin.id,
        target_type="user",
        target_id=str(user.id),
        ip_address=client_ip(request),
    )
    return PasswordResetIssued(
        email=user.email,
        token=token,
        expires_in_hours=int(service.PASSWORD_RESET_TTL.total_seconds() // 3600),
    )


@router.post("/password-reset", status_code=204, responses={400: {"model": ErrorResponse}})
def complete_password_reset(
    body: PasswordResetComplete, request: Request, session: SessionDep
) -> None:
    """Set a new password with a reset token. All of the user's sessions are signed out."""
    user = service.complete_password_reset(
        session, token=body.token, new_password=body.new_password
    )
    audit.record(
        session,
        "auth.password_reset_completed",
        actor_user_id=user.id,
        target_type="user",
        target_id=str(user.id),
        ip_address=client_ip(request),
    )
