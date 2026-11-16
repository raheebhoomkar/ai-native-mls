"""The single place where roles are mapped to permissions.

Routers ask for a permission with `require("...")`; they never check role names.
Platform administrators hold every permission in every organisation.
The matrix is documented in docs/security/rbac-matrix.md; keep both in step.
"""

from typing import Literal, get_args

OrganisationKind = Literal["mls", "brokerage"]
Role = Literal["mls_admin", "brokerage_admin", "broker", "agent", "api_consumer"]

ORGANISATION_KINDS: tuple[str, ...] = ("mls", "brokerage")
ROLES: tuple[str, ...] = ("mls_admin", "brokerage_admin", "broker", "agent", "api_consumer")

# The administrator role an organisation of each kind may hold; other roles fit both kinds.
ALLOWED_ROLES: dict[str, tuple[str, ...]] = {
    "mls": ("mls_admin", "broker", "agent", "api_consumer"),
    "brokerage": ("brokerage_admin", "broker", "agent", "api_consumer"),
}

Permission = Literal[
    "organisation:read",
    "member:read",
    "member:manage",
    "audit:read",
    "listing:read",
    # Create listings and properties; edit listings you are the listing agent of.
    "listing:write",
    # Edit any listing in the organisation and reassign its agent.
    "listing:manage_all",
    # Approve a listing that is pending review so it becomes active.
    "listing:publish",
]
ALL_PERMISSIONS: frozenset[Permission] = frozenset(get_args(Permission))

_ADMIN: frozenset[Permission] = ALL_PERMISSIONS
_BROKER: frozenset[Permission] = frozenset(
    {
        "organisation:read",
        "member:read",
        "listing:read",
        "listing:write",
        "listing:manage_all",
        "listing:publish",
    }
)
_AGENT: frozenset[Permission] = frozenset(
    {"organisation:read", "member:read", "listing:read", "listing:write"}
)

ROLE_PERMISSIONS: dict[str, frozenset[Permission]] = {
    "mls_admin": _ADMIN,
    "brokerage_admin": _ADMIN,
    "broker": _BROKER,
    "agent": _AGENT,
    "api_consumer": frozenset({"organisation:read", "listing:read"}),
}
