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
from app.modules.auth.models import User
from app.modules.listings import service as listings
from app.modules.listings.models import Listing
from app.modules.listings.schemas import (
    Address,
    Area,
    ListingCreate,
    Money,
    PropertyCreate,
    TransitionRequest,
)
from app.modules.organisations import service as organisations
from app.modules.organisations.deps import TenantContext
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

# Fictional listings, marked [Demo]. Addresses and prices are invented, not market data.
# organisation: (agent, approver, [(title, type, price, visibility, final status,
#                                   property type, locality, city, beds, baths, sq ft)])
DemoRow = tuple[str, str, str, str, str, str, str, str, int | None, int | None, str]
DEMO_LISTINGS: dict[str, tuple[str, str, list[DemoRow]]] = {
    "Sunrise Realty": (
        "sunrise.agent@demo.example.com",
        "sunrise.admin@demo.example.com",
        [
            ("[Demo] 3 BHK apartment near the lake", "sale", "25000000", "network", "active",
             "apartment", "Powai", "Mumbai", 3, 2, "1250"),
            ("[Demo] Compact studio to let", "rent", "45000", "private", "draft",
             "apartment", "Andheri West", "Mumbai", 1, 1, "420"),
            ("[Demo] Garden villa", "sale", "55000000", "private", "pending_review",
             "villa", "Koregaon Park", "Pune", 4, 4, "3200"),
            ("[Demo] Corner office space", "sale", "18000000", "network", "sold",
             "commercial", "Baner", "Pune", None, 2, "900"),
        ],
    ),
    "Harbour Homes": (
        "two.orgs@demo.example.com",
        "harbour.admin@demo.example.com",
        [
            ("[Demo] Sea-facing 2 BHK", "sale", "32000000", "network", "active",
             "apartment", "Worli", "Mumbai", 2, 2, "980"),
        ],
    ),
}  # fmt: skip


def _context(session: Session, user: User, organisation: Organisation) -> TenantContext:
    membership = organisations.get_membership(session, organisation.id, user.id)
    return TenantContext(user, organisation.id, membership.role if membership else None)


def _seed_listings(session: Session, orgs: dict[str, Organisation]) -> list[str]:
    created: list[str] = []
    for org_name, (agent_email, approver_email, rows) in DEMO_LISTINGS.items():
        org = orgs[org_name]
        if session.scalar(select(Listing.id).where(Listing.organisation_id == org.id).limit(1)):
            continue  # this organisation already has listings; leave them alone
        agent_user = auth.get_user_by_email(session, agent_email)
        approver_user = auth.get_user_by_email(session, approver_email)
        if agent_user is None or approver_user is None:
            continue
        agent = _context(session, agent_user, org)
        approver = _context(session, approver_user, org)
        for number, row in enumerate(rows, start=1):
            title, kind, price, visibility, status, ptype, locality, city, beds, baths, sqft = row
            prop = listings.create_property(
                session,
                agent,
                PropertyCreate.model_validate(
                    {
                        "property_type": ptype,
                        "address": Address(
                            line1=f"Unit {number}, Example Towers",
                            locality=locality,
                            city=city,
                            country="IN",
                        ),
                        "bedrooms": beds,
                        "bathrooms": baths,
                        "area": Area.model_validate({"value": sqft, "unit": "sqft"}),
                    }
                ),
            )
            listing = listings.create_listing(
                session,
                agent,
                ListingCreate.model_validate(
                    {
                        "property_id": prop.id,
                        "listing_type": kind,
                        "title": title,
                        "remarks": "Fictional demo listing for local development.",
                        "list_price": {"amount": price, "currency": "INR"},
                        "visibility": visibility,
                    }
                ),
            )
            # Walk the real lifecycle, so history and audit rows look like genuine use.
            steps = {
                "draft": [],
                "pending_review": [(agent, "pending_review")],
                "active": [(agent, "pending_review"), (approver, "active")],
                "sold": [(agent, "pending_review"), (approver, "active"), (agent, "sold")],
            }[status]
            for ctx, to in steps:
                sold_price = Money.model_validate({"amount": price, "currency": "INR"})
                listings.transition_listing(
                    session,
                    ctx,
                    listing.id,
                    TransitionRequest(
                        to=to,
                        version=listing.version,
                        sold_price=sold_price if to == "sold" else None,
                    ),
                )
                session.refresh(listing)
            created.append(f"listing {title}")
    return created


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
    return created + _seed_listings(session, orgs)


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
