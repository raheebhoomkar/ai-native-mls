"""Local development seed data. Refuses to run in production.

    python -m app.seed

Safe to run again: existing users and organisations are left as they are.
"""

import sys

from sqlalchemy import select
from sqlalchemy.orm import Session

import app.main  # noqa: F401  # importing the app registers every module's models on Base
from app.core.config import get_settings
from app.core.db import get_engine
from app.modules.auth import service as auth
from app.modules.organisations import service as organisations
from app.modules.organisations.models import Organisation

# Published in the README on purpose: these accounts exist only on a developer's machine.
SEED_PASSWORD = "local-dev-password"  # noqa: S105

ORGANISATIONS = {"Demo MLS": "mls", "Sunrise Realty": "brokerage", "Harbour Homes": "brokerage"}

# email: (full name, platform admin, {organisation: role})
USERS: dict[str, tuple[str, bool, dict[str, str]]] = {
    "platform.admin@demo.example.com": ("Priya Platform", True, {}),
    "mls.admin@demo.example.com": ("Meera MLS", False, {"Demo MLS": "mls_admin"}),
    "sunrise.admin@demo.example.com": (
        "Sanjay Sunrise",
        False,
        {"Sunrise Realty": "brokerage_admin"},
    ),
    "sunrise.agent@demo.example.com": ("Asha Agent", False, {"Sunrise Realty": "agent"}),
    "harbour.admin@demo.example.com": ("Hari Harbour", False, {"Harbour Homes": "brokerage_admin"}),
    # Belongs to two organisations, to exercise the organisation switcher.
    "two.orgs@demo.example.com": (
        "Tara Two",
        False,
        {"Sunrise Realty": "broker", "Harbour Homes": "agent"},
    ),
}


def seed(session: Session) -> list[str]:
    created: list[str] = []
    orgs: dict[str, Organisation] = {}
    for name, kind in ORGANISATIONS.items():
        existing = session.scalar(select(Organisation).where(Organisation.name == name))
        orgs[name] = existing or organisations.create_organisation(session, name=name, kind=kind)
        if existing is None:
            created.append(f"organisation {name}")
    for email, (full_name, platform_admin, memberships) in USERS.items():
        user = auth.get_user_by_email(session, email)
        if user is None:
            user = auth.create_user(
                session,
                email=email,
                full_name=full_name,
                password=SEED_PASSWORD,
                is_platform_admin=platform_admin,
            )
            created.append(f"user {email}")
        for org_name, role in memberships.items():
            if organisations.get_membership(session, orgs[org_name].id, user.id) is None:
                organisations.add_member(
                    session, user_id=user.id, organisation_id=orgs[org_name].id, role=role
                )
    return created


def main() -> int:
    if get_settings().environment == "production":
        print("Refusing to seed: ENVIRONMENT is production.", file=sys.stderr)
        return 1
    with Session(get_engine()) as session, session.begin():
        created = seed(session)
    print("\n".join(f"Created {item}" for item in created) or "Nothing to create.")
    print(f"Every seeded user signs in with the password: {SEED_PASSWORD}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
