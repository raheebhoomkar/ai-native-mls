"""The single place where roles are mapped to permissions.

Routers ask for a permission with `require("...")`; they never check role names.
Platform administrators hold every permission in every organisation.
The matrix is documented in docs/security/rbac-matrix.md; keep both in step.
"""

from typing import Literal

OrganisationKind = Literal["mls", "brokerage"]
Role = Literal["mls_admin", "brokerage_admin", "broker", "agent", "api_consumer"]

ORGANISATION_KINDS: tuple[str, ...] = ("mls", "brokerage")
ROLES: tuple[str, ...] = ("mls_admin", "brokerage_admin", "broker", "agent", "api_consumer")

Permission = Literal["organisation:read", "member:read", "audit:read"]

_ADMIN: frozenset[Permission] = frozenset({"organisation:read", "member:read", "audit:read"})
_STAFF: frozenset[Permission] = frozenset({"organisation:read", "member:read"})

ROLE_PERMISSIONS: dict[str, frozenset[Permission]] = {
    "mls_admin": _ADMIN,
    "brokerage_admin": _ADMIN,
    "broker": _STAFF,
    "agent": _STAFF,
    "api_consumer": frozenset({"organisation:read"}),
}
