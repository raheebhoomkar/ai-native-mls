from dataclasses import dataclass
from typing import Annotated

from fastapi import Depends, Request

from app.core.db import SessionDep
from app.core.errors import AppError
from app.modules.auth import service
from app.modules.auth.models import AuthSession, User

SESSION_COOKIE = "mls_session"


@dataclass(frozen=True)
class Authenticated:
    user: User
    auth_session: AuthSession


def client_ip(request: Request) -> str | None:
    # shortcut: behind a reverse proxy this is the proxy's address,
    # upgrade to trusted forwarded headers when the app is deployed (Sprint 5).
    return request.client.host if request.client else None


def _authenticated(request: Request, session: SessionDep) -> Authenticated:
    token = request.cookies.get(SESSION_COOKIE)
    resolved = service.resolve_session(session, token) if token else None
    if resolved is None:
        raise AppError(401, "unauthenticated", "Sign in to continue.")
    return Authenticated(auth_session=resolved[0], user=resolved[1])


AuthenticatedDep = Annotated[Authenticated, Depends(_authenticated)]


def _current_user(authenticated: AuthenticatedDep) -> User:
    return authenticated.user


CurrentUser = Annotated[User, Depends(_current_user)]


def _platform_admin(user: CurrentUser) -> User:
    if not user.is_platform_admin:
        raise AppError(403, "forbidden", "You do not have permission to do this.")
    return user


PlatformAdmin = Annotated[User, Depends(_platform_admin)]
