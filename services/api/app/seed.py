"""Demo seed data.

    python -m app.seed

Locally it uses a fixed, published password. In production it runs only when both
SEED_DEMO_DATA=true and SEED_PASSWORD are set, and uses that password, so a public
demo never has accounts with a password that is printed in the README.

`--if-configured` makes it a silent no-op unless SEED_DEMO_DATA=true (used at container start).

Safe to run again: existing users and organisations are left as they are.
"""

import sys
from io import BytesIO
from uuid import UUID

from PIL import Image, ImageDraw, ImageFont
from sqlalchemy import select
from sqlalchemy.orm import Session

import app.main  # noqa: F401  # importing the app registers every module's models on Base
from app.core.config import get_settings
from app.core.db import get_engine
from app.core.errors import AppError
from app.modules.auth import service as auth
from app.modules.auth.models import User
from app.modules.compliance import service as compliance
from app.modules.geo.service import request_geocode
from app.modules.listings import service as listings
from app.modules.listings.models import Listing, Property
from app.modules.listings.schemas import (
    Address,
    Area,
    ListingCreate,
    Money,
    PropertyCreate,
    TransitionRequest,
)
from app.modules.media import service as media
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


def _demo_listing(
    session: Session,
    agent: TenantContext,
    approver: TenantContext,
    number: int,
    row: DemoRow,
    remarks: str = "Fictional demo listing for local development.",
) -> Listing:
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
                "remarks": remarks,
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
    return listing


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
            _demo_listing(session, agent, approver, number, row)
            created.append(f"listing {row[0]}")
    return created


# Remarks a policy check flags, so the review queue has something to show. Fictional.
COMPLIANCE_DEMO: DemoRow = (
    "[Demo] 2 BHK to let near the IT park", "rent", "38000", "private", "pending_review",
    "apartment", "Hinjewadi", "Pune", 2, 2, "850",
)  # fmt: skip
COMPLIANCE_REMARKS = (
    "Fictional demo listing. Bright 2 BHK, 10 minutes from the IT park. "
    "Vegetarians only, no bachelors."
)


def _seed_compliance_demo(session: Session, orgs: dict[str, Organisation]) -> list[str]:
    """One Sunrise listing submitted with remarks the policy flags; its check is queued for
    the worker. Added on its own so existing local databases get it too."""
    if session.scalar(select(Listing.id).where(Listing.title == COMPLIANCE_DEMO[0])):
        return []
    agent_user = auth.get_user_by_email(session, "sunrise.agent@demo.example.com")
    approver_user = auth.get_user_by_email(session, "sunrise.admin@demo.example.com")
    if agent_user is None or approver_user is None:
        return []
    org = orgs["Sunrise Realty"]
    agent = _context(session, agent_user, org)
    listing = _demo_listing(
        session, agent, _context(session, approver_user, org), 9, COMPLIANCE_DEMO,
        COMPLIANCE_REMARKS,
    )  # fmt: skip
    compliance.scan_on_submit(session, agent, listing.id)
    return [f"listing {listing.title} (policy check queued)"]


# Muted wall, roof and sky colours; one set per demo photo.
_PHOTO_COLOURS = (
    ((214, 196, 160), (140, 70, 50), (150, 190, 220)),
    ((190, 200, 205), (70, 80, 95), (230, 200, 160)),
)


def _demo_photo(number: int) -> bytes:
    """A drawn house, clearly labelled as a demo; no real photograph is shipped."""
    wall, roof, sky = _PHOTO_COLOURS[(number - 1) % len(_PHOTO_COLOURS)]
    image = Image.new("RGB", (1200, 800), sky)
    draw = ImageDraw.Draw(image)
    draw.rectangle((0, 680, 1200, 800), fill=(110, 150, 90))
    draw.rectangle((330, 360, 870, 690), fill=wall)
    draw.polygon([(280, 380), (600, 150), (920, 380)], fill=roof)
    draw.rectangle((550, 520, 650, 690), fill=roof)
    draw.text((40, 30), f"[Demo] photo {number}", fill="white", font=ImageFont.load_default(56))
    out = BytesIO()
    image.save(out, "JPEG", quality=85)
    return out.getvalue()


def _stored(session: Session, asset_id: UUID) -> bool:
    try:
        media.get_content(session, asset_id)
    except AppError:
        return False
    return True


def _seed_photos(session: Session, orgs: dict[str, Organisation]) -> list[str]:
    """Two photos per demo listing. Also replaces photos whose files are gone, as on a fresh
    container with local storage. The background worker makes their thumbnails."""
    created: list[str] = []
    for org_name, (agent_email, _, _) in DEMO_LISTINGS.items():
        agent_user = auth.get_user_by_email(session, agent_email)
        if agent_user is None:
            continue
        agent = _context(session, agent_user, orgs[org_name])
        demo = session.scalars(
            select(Listing).where(
                Listing.organisation_id == orgs[org_name].id,
                Listing.title.startswith("[Demo]"),
                Listing.archived_at.is_(None),
            )
        ).all()
        for listing in demo:
            _, photos = media.list_media(session, agent, listing.id)
            if photos and all(_stored(session, photo.id) for photo in photos):
                continue
            for photo in photos:
                media.delete(session, agent, photo.id)
            for number in (1, 2):
                media.upload(
                    session,
                    agent,
                    listing.id,
                    filename=f"demo-photo-{number}.jpg",
                    declared_type="image/jpeg",
                    data=_demo_photo(number),
                )
            created.append(f"photos for {listing.title}")
    return created


def seed(session: Session, password: str = SEED_PASSWORD) -> list[str]:
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
                password=password,
                is_platform_admin=platform_admin,
            )
            created.append(f"user {email}")
        for org_name, role in memberships.items():
            if organisations.get_membership(session, orgs[org_name].id, user.id) is None:
                organisations.add_member(
                    session, user_id=user.id, organisation_id=orgs[org_name].id, role=role
                )
    created += _seed_listings(session, orgs)
    created += _seed_compliance_demo(session, orgs)
    created += _locate_old_properties(session, orgs)
    return created + _seed_photos(session, orgs)


def _locate_old_properties(session: Session, orgs: dict[str, Organisation]) -> list[str]:
    """Queue a lookup for demo properties seeded before locations existed (Sprint 12)."""
    old = session.scalars(
        select(Property).where(
            Property.organisation_id.in_([org.id for org in orgs.values()]),
            Property.geo_status.is_(None),
        )
    ).all()
    for prop in old:
        request_geocode(session, prop)
    return [f"location lookups for {len(old)} older properties"] if old else []


def main(argv: list[str] | None = None) -> int:
    args = sys.argv[1:] if argv is None else argv
    settings = get_settings()
    if "--if-configured" in args and not settings.seed_demo_data:
        return 0
    password = SEED_PASSWORD
    if settings.environment == "production":
        if not settings.seed_demo_data or settings.seed_password is None:
            print(
                "Refusing to seed in production: set SEED_DEMO_DATA=true and SEED_PASSWORD.",
                file=sys.stderr,
            )
            return 1
        password = settings.seed_password.get_secret_value()
    with Session(get_engine()) as session, session.begin():
        created = seed(session, password)
    print("\n".join(f"Created {item}" for item in created) or "Nothing to create.")
    if password == SEED_PASSWORD:
        print(f"Every seeded user signs in with the password: {SEED_PASSWORD}")
    else:
        print("Seeded users sign in with the password from SEED_PASSWORD.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
