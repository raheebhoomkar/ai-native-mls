"""Invitations, role assignment, profile and password reset (Module 1, part b)."""

from collections.abc import Callable
from datetime import UTC, datetime, timedelta

from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.modules.audit.models import AuditEvent
from app.modules.auth.models import PasswordResetToken, User
from app.modules.organisations import service as organisations
from app.modules.organisations.models import Invitation, Organisation
from app.seed import SEED_PASSWORD, seed
from tests.conftest import PASSWORD

INVITATIONS = "/api/v1/organisations/current/invitations"
MEMBERS = "/api/v1/organisations/current/members"
PREVIEW = "/api/v1/invitations/preview"
ACCEPT = "/api/v1/invitations/accept"
LOGIN = "/api/v1/auth/login"
ME = "/api/v1/auth/me"
NEW_PASSWORD = "a brand new passphrase"

MakeUser = Callable[..., User]
MakeOrg = Callable[..., Organisation]
LoginAs = Callable[[User], TestClient]


def _org(organisation: Organisation) -> dict[str, str]:
    return {"X-Organisation-ID": str(organisation.id)}


def _actions(db: Session) -> set[str]:
    return set(db.scalars(select(AuditEvent.action)))


def test_admin_invites_new_person_who_creates_an_account_and_joins(
    app: FastAPI, db: Session, make_user: MakeUser, make_org: MakeOrg, login_as: LoginAs
) -> None:
    admin = make_user("admin@a.example")
    org = make_org("Brokerage A", {admin: "brokerage_admin"})
    as_admin = login_as(admin)

    created = as_admin.post(INVITATIONS, json={"email": "New.Agent@a.example", "role": "agent"})
    assert created.status_code == 201
    token = created.json()["token"]
    assert db.scalars(select(Invitation)).one().token_hash != token  # only a hash is stored
    assert [i["email"] for i in as_admin.get(INVITATIONS).json()["items"]] == [
        "new.agent@a.example"
    ]
    assert "token" not in as_admin.get(INVITATIONS).json()["items"][0]

    visitor = TestClient(app)  # not signed in
    preview = visitor.post(PREVIEW, json={"token": token}).json()
    assert preview == {
        "organisation_name": "Brokerage A",
        "email": "new.agent@a.example",
        "role": "agent",
        "account_exists": False,
    }

    # A new account needs a name and a valid password.
    incomplete = visitor.post(ACCEPT, json={"token": token})
    assert incomplete.status_code == 422
    assert {d["field"] for d in incomplete.json()["error"]["details"]} == {"full_name", "password"}
    weak = visitor.post(ACCEPT, json={"token": token, "full_name": "New Agent", "password": "x"})
    assert weak.status_code == 422

    accepted = visitor.post(
        ACCEPT, json={"token": token, "full_name": "New Agent", "password": NEW_PASSWORD}
    )
    assert accepted.status_code == 200
    assert accepted.json()["account_created"] is True
    assert "set-cookie" not in accepted.headers  # accepting does not sign anyone in

    signed_in = visitor.post(LOGIN, json={"email": "new.agent@a.example", "password": NEW_PASSWORD})
    assert signed_in.json()["memberships"] == [
        {
            "organisation_id": str(org.id),
            "organisation_name": "Brokerage A",
            "organisation_kind": "brokerage",
            "role": "agent",
        }
    ]

    # The link works once, and the invitation leaves the pending list.
    assert visitor.post(ACCEPT, json={"token": token}).status_code == 400
    assert as_admin.get(INVITATIONS).json()["items"] == []
    assert {"invitation.created", "invitation.accepted", "user.created"} <= _actions(db)


def test_existing_user_accepts_invitation_into_a_second_organisation_only(
    app: FastAPI, db: Session, make_user: MakeUser, make_org: MakeOrg, login_as: LoginAs
) -> None:
    admin_b, alice = make_user("admin@b.example"), make_user("alice@a.example")
    make_org("Brokerage A", {alice: "agent"})
    org_b = make_org("Brokerage B", {admin_b: "brokerage_admin"})
    other = make_org("Brokerage C")

    token = (
        login_as(admin_b).post(INVITATIONS, json={"email": alice.email, "role": "broker"})
    ).json()["token"]
    visitor = TestClient(app)
    assert visitor.post(PREVIEW, json={"token": token}).json()["account_exists"] is True

    # A password sent for an existing account is ignored, not used to overwrite it.
    accepted = visitor.post(ACCEPT, json={"token": token, "password": "attacker-chosen-password"})
    assert accepted.json()["account_created"] is False
    assert visitor.post(LOGIN, json={"email": alice.email, "password": PASSWORD}).status_code == 200

    assert organisations.get_membership(db, org_b.id, alice.id).role == "broker"  # type: ignore[union-attr]
    assert organisations.get_membership(db, other.id, alice.id) is None


def test_invitation_rules(
    app: FastAPI, db: Session, make_user: MakeUser, make_org: MakeOrg, login_as: LoginAs
) -> None:
    admin, agent = make_user("admin@a.example"), make_user("agent@a.example")
    make_org("Brokerage A", {admin: "brokerage_admin", agent: "agent"})
    as_admin = login_as(admin)

    # Only administrators may invite or see invitations.
    as_agent = login_as(agent)
    assert (
        as_agent.post(INVITATIONS, json={"email": "x@a.example", "role": "agent"}).status_code
        == 403
    )
    assert as_agent.get(INVITATIONS).status_code == 403

    def invite(email: str, role: str) -> int:
        return as_admin.post(INVITATIONS, json={"email": email, "role": role}).status_code

    assert invite("not-an-email", "agent") == 422
    assert invite("x@a.example", "owner") == 422
    assert invite("x@a.example", "mls_admin") == 422  # wrong administrator role for a brokerage
    assert invite(agent.email, "broker") == 409  # already a member

    # Inviting the same person again replaces the earlier link.
    first = as_admin.post(INVITATIONS, json={"email": "x@a.example", "role": "agent"}).json()
    second = as_admin.post(INVITATIONS, json={"email": "x@a.example", "role": "broker"}).json()
    visitor = TestClient(app)
    assert visitor.post(PREVIEW, json={"token": first["token"]}).status_code == 400
    assert visitor.post(PREVIEW, json={"token": second["token"]}).json()["role"] == "broker"

    # Revoked and expired links stop working, with the same answer as a made-up token.
    assert as_admin.delete(f"{INVITATIONS}/{second['id']}").status_code == 204
    assert as_admin.delete(f"{INVITATIONS}/{second['id']}").status_code == 404
    revoked = visitor.post(PREVIEW, json={"token": second["token"]})
    third = as_admin.post(INVITATIONS, json={"email": "y@a.example", "role": "agent"}).json()
    db.scalars(select(Invitation).where(Invitation.email == "y@a.example")).one().expires_at = (
        datetime.now(UTC) - timedelta(seconds=1)
    )
    db.commit()
    expired = visitor.post(
        ACCEPT, json={"token": third["token"], "full_name": "Y", "password": NEW_PASSWORD}
    )
    unknown = visitor.post(PREVIEW, json={"token": "made-up"})
    assert revoked.status_code == expired.status_code == unknown.status_code == 400
    assert revoked.json()["error"]["message"] == unknown.json()["error"]["message"]


def test_member_management_cannot_cross_tenants(
    db: Session, make_user: MakeUser, make_org: MakeOrg, login_as: LoginAs
) -> None:
    admin_a, admin_b, bob = (
        make_user("admin@a.example"),
        make_user("admin@b.example"),
        make_user("bob@b.example"),
    )
    org_a = make_org("Brokerage A", {admin_a: "brokerage_admin"})
    org_b = make_org("Brokerage B", {admin_b: "brokerage_admin", bob: "agent"})
    invitation_b = (
        login_as(admin_b).post(INVITATIONS, json={"email": "new@b.example", "role": "agent"}).json()
    )
    as_a = login_as(admin_a)

    # Acting in their own organisation, B's records do not exist for A's administrator.
    assert as_a.patch(f"{MEMBERS}/{bob.id}", json={"role": "broker"}).status_code == 404
    assert as_a.delete(f"{MEMBERS}/{bob.id}").status_code == 404
    assert as_a.delete(f"{INVITATIONS}/{invitation_b['id']}").status_code == 404
    # Naming B's organisation directly is forbidden.
    b = _org(org_b)
    denied = [
        as_a.patch(f"{MEMBERS}/{bob.id}", json={"role": "broker"}, headers=b),
        as_a.delete(f"{MEMBERS}/{bob.id}", headers=b),
        as_a.get(INVITATIONS, headers=b),
        as_a.post(INVITATIONS, json={"email": "spy@a.example", "role": "agent"}, headers=b),
    ]
    assert [response.status_code for response in denied] == [403, 403, 403, 403]

    assert organisations.get_membership(db, org_b.id, bob.id).role == "agent"  # type: ignore[union-attr]
    assert organisations.get_membership(db, org_a.id, bob.id) is None
    assert len(login_as(admin_b).get(INVITATIONS).json()["items"]) == 1


def test_role_change_and_removal(
    db: Session, make_user: MakeUser, make_org: MakeOrg, login_as: LoginAs
) -> None:
    admin, agent = make_user("admin@a.example"), make_user("agent@a.example")
    org = make_org("Brokerage A", {admin: "brokerage_admin", agent: "agent"})
    as_admin, as_agent = login_as(admin), login_as(agent)

    # An agent cannot promote themselves or anyone else.
    assert (
        as_agent.patch(f"{MEMBERS}/{agent.id}", json={"role": "brokerage_admin"}).status_code == 403
    )
    assert as_agent.delete(f"{MEMBERS}/{admin.id}").status_code == 403

    # An administrator cannot demote or remove themselves, so one always remains.
    assert as_admin.patch(f"{MEMBERS}/{admin.id}", json={"role": "agent"}).status_code == 409
    assert as_admin.delete(f"{MEMBERS}/{admin.id}").status_code == 409

    assert as_admin.patch(f"{MEMBERS}/{agent.id}", json={"role": "mls_admin"}).status_code == 422
    assert as_admin.patch(f"{MEMBERS}/{agent.id}", json={"role": "broker"}).status_code == 204
    assert organisations.get_membership(db, org.id, agent.id).role == "broker"  # type: ignore[union-attr]
    change = db.scalars(select(AuditEvent).where(AuditEvent.action == "member.role_changed")).one()
    assert change.detail == {"from": "agent", "to": "broker"}
    assert change.actor_user_id == admin.id and change.organisation_id == org.id

    assert as_admin.delete(f"{MEMBERS}/{agent.id}").status_code == 204
    # The removed member keeps their account but loses access at once.
    assert as_agent.get(ME).json()["memberships"] == []
    assert as_agent.get(MEMBERS, headers=_org(org)).status_code == 403


def test_current_organisation_reports_callers_permissions(
    make_user: MakeUser, make_org: MakeOrg, login_as: LoginAs
) -> None:
    root = make_user("root@example.com", platform_admin=True)
    admin, agent = make_user("admin@a.example"), make_user("agent@a.example")
    org = make_org("Brokerage A", {admin: "brokerage_admin", agent: "agent"})
    current = "/api/v1/organisations/current"

    as_agent = login_as(agent).get(current).json()
    assert as_agent["my_role"] == "agent"
    assert as_agent["my_permissions"] == ["member:read", "organisation:read"]
    assert "member:manage" in login_as(admin).get(current).json()["my_permissions"]
    as_root = login_as(root).get(current, headers=_org(org)).json()
    assert as_root["my_role"] is None and "member:manage" in as_root["my_permissions"]
    assert as_root["assignable_roles"] == ["brokerage_admin", "broker", "agent", "api_consumer"]


def test_profile_update_and_password_change(
    app: FastAPI, make_user: MakeUser, login_as: LoginAs
) -> None:
    user = make_user("agent@a.example")
    here, elsewhere = login_as(user), login_as(user)

    assert (
        here.patch(ME, json={"full_name": "  Asha Rao  "}).json()["user"]["full_name"] == "Asha Rao"
    )
    assert here.patch(ME, json={"full_name": "   "}).status_code == 422

    change = "/api/v1/auth/password"
    wrong = here.post(change, json={"current_password": "nope", "new_password": NEW_PASSWORD})
    assert wrong.status_code == 422
    assert wrong.json()["error"]["details"][0]["field"] == "current_password"
    short = here.post(change, json={"current_password": PASSWORD, "new_password": "short"})
    assert short.json()["error"]["details"][0]["field"] == "new_password"

    ok = here.post(change, json={"current_password": PASSWORD, "new_password": NEW_PASSWORD})
    assert ok.status_code == 204
    assert here.get(ME).status_code == 200  # this session stays signed in
    assert elsewhere.get(ME).status_code == 401  # other sessions are signed out
    fresh = TestClient(app)
    assert fresh.post(LOGIN, json={"email": user.email, "password": PASSWORD}).status_code == 401
    assert (
        fresh.post(LOGIN, json={"email": user.email, "password": NEW_PASSWORD}).status_code == 200
    )


def test_password_reset_link_is_platform_admin_only_and_single_use(
    app: FastAPI, db: Session, make_user: MakeUser, make_org: MakeOrg, login_as: LoginAs
) -> None:
    root = make_user("root@example.com", platform_admin=True)
    admin, agent = make_user("admin@a.example"), make_user("agent@a.example")
    make_org("Brokerage A", {admin: "brokerage_admin", agent: "agent"})
    issue, complete = "/api/v1/auth/password-reset-links", "/api/v1/auth/password-reset"

    # An organisation administrator must not be able to take over a member's account.
    assert login_as(admin).post(issue, json={"email": agent.email}).status_code == 403
    as_root = login_as(root)
    assert as_root.post(issue, json={"email": "nobody@a.example"}).status_code == 404

    old_session = login_as(agent)
    first = as_root.post(issue, json={"email": agent.email}).json()["token"]
    token = as_root.post(issue, json={"email": agent.email}).json()["token"]
    assert db.scalars(select(PasswordResetToken.token_hash)).all().count(token) == 0

    visitor = TestClient(app)
    # Issuing a second link cancels the first.
    assert (
        visitor.post(complete, json={"token": first, "new_password": NEW_PASSWORD}).status_code
        == 400
    )
    assert visitor.post(complete, json={"token": token, "new_password": "short"}).status_code == 422
    assert (
        visitor.post(complete, json={"token": token, "new_password": NEW_PASSWORD}).status_code
        == 204
    )
    assert (
        visitor.post(
            complete, json={"token": token, "new_password": "another long one"}
        ).status_code
        == 400
    )

    assert old_session.get(ME).status_code == 401  # every session is signed out
    assert (
        visitor.post(LOGIN, json={"email": agent.email, "password": NEW_PASSWORD}).status_code
        == 200
    )
    assert {"auth.password_reset_issued", "auth.password_reset_completed"} <= _actions(db)

    expired = as_root.post(issue, json={"email": agent.email}).json()["token"]
    for row in db.scalars(select(PasswordResetToken).where(PasswordResetToken.used_at.is_(None))):
        row.expires_at = datetime.now(UTC) - timedelta(seconds=1)
    db.commit()
    assert (
        visitor.post(complete, json={"token": expired, "new_password": NEW_PASSWORD}).status_code
        == 400
    )


def test_seed_is_repeatable_and_accounts_can_sign_in(app: FastAPI, db: Session) -> None:
    seed(db)  # may find the data already there: the developer's database can be seeded
    assert seed(db) == []
    db.commit()
    response = TestClient(app).post(
        LOGIN, json={"email": "two.orgs@demo.example.com", "password": SEED_PASSWORD}
    )
    assert {m["organisation_name"] for m in response.json()["memberships"]} == {
        "Sunrise Realty",
        "Harbour Homes",
    }
