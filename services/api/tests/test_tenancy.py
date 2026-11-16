"""Tenant isolation and role checks (INSTRUCTIONS.md section 10, scenarios 1 and 2)."""

from collections.abc import Callable

from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.pagination import encode_cursor
from app.modules.audit import service as audit
from app.modules.audit.models import AuditEvent
from app.modules.auth.models import User
from app.modules.organisations.models import Organisation

CURRENT = "/api/v1/organisations/current"
MEMBERS = "/api/v1/organisations/current/members"
ORGANISATIONS = "/api/v1/organisations"
AUDIT = "/api/v1/audit-events"

MakeUser = Callable[..., User]
MakeOrg = Callable[..., Organisation]
LoginAs = Callable[[User], TestClient]


def _org(organisation: Organisation) -> dict[str, str]:
    return {"X-Organisation-ID": str(organisation.id)}


def test_member_of_one_organisation_cannot_read_another(
    db: Session, make_user: MakeUser, make_org: MakeOrg, login_as: LoginAs
) -> None:
    alice, bob = make_user("alice@a.example"), make_user("bob@b.example")
    org_a = make_org("Brokerage A", {alice: "brokerage_admin"})
    org_b = make_org("Brokerage B", {bob: "agent"})
    as_alice = login_as(alice)

    for path in (CURRENT, MEMBERS, AUDIT):
        assert as_alice.get(path, headers=_org(org_a)).status_code == 200
        denied = as_alice.get(path, headers=_org(org_b))
        assert denied.status_code == 403, path
        assert "Brokerage B" not in denied.text and "bob@b.example" not in denied.text

    denials = db.scalars(select(AuditEvent).where(AuditEvent.action == "access.denied")).all()
    assert len(denials) == 3
    assert {event.actor_user_id for event in denials} == {alice.id}
    assert {event.target_id for event in denials} == {str(org_b.id)}


def test_unknown_organisation_looks_the_same_as_a_forbidden_one(
    make_user: MakeUser, make_org: MakeOrg, login_as: LoginAs
) -> None:
    alice, bob = make_user("alice@a.example"), make_user("bob@b.example")
    make_org("Brokerage A", {alice: "agent"})
    org_b = make_org("Brokerage B", {bob: "agent"})
    as_alice = login_as(alice)

    forbidden = as_alice.get(CURRENT, headers=_org(org_b))
    unknown = as_alice.get(
        CURRENT, headers={"X-Organisation-ID": "00000000-0000-4000-8000-000000000000"}
    )

    assert forbidden.status_code == unknown.status_code == 403
    assert forbidden.json()["error"]["message"] == unknown.json()["error"]["message"]


def test_member_list_contains_only_the_active_organisation(
    make_user: MakeUser, make_org: MakeOrg, login_as: LoginAs
) -> None:
    alice, bob, carol = (
        make_user("alice@a.example"),
        make_user("bob@b.example"),
        make_user("carol@a.example"),
    )
    make_org("Brokerage A", {alice: "agent", carol: "broker"})
    make_org("Brokerage B", {bob: "agent"})

    members = login_as(alice).get(MEMBERS).json()["items"]

    assert {member["email"] for member in members} == {"alice@a.example", "carol@a.example"}
    assert {member["role"] for member in members} == {"agent", "broker"}


def test_audit_log_is_admin_only_and_scoped_to_the_organisation(
    db: Session, make_user: MakeUser, make_org: MakeOrg, login_as: LoginAs
) -> None:
    admin, agent, outsider = (
        make_user("admin@a.example"),
        make_user("agent@a.example"),
        make_user("bob@b.example"),
    )
    org_a = make_org("Brokerage A", {admin: "brokerage_admin", agent: "agent"})
    org_b = make_org("Brokerage B", {outsider: "brokerage_admin"})
    audit.record(db, "test.event_a", organisation_id=org_a.id)
    audit.record(db, "test.event_b", organisation_id=org_b.id)
    db.commit()

    # An agent is a member but lacks audit:read.
    assert login_as(agent).get(AUDIT).status_code == 403

    actions = {item["action"] for item in login_as(admin).get(AUDIT).json()["items"]}
    assert "test.event_a" in actions
    assert "test.event_b" not in actions


def test_user_in_several_organisations_must_choose_one(
    make_user: MakeUser, make_org: MakeOrg, login_as: LoginAs
) -> None:
    alice = make_user("alice@a.example")
    org_a = make_org("Brokerage A", {alice: "agent"})
    org_b = make_org("Brokerage B", {alice: "broker"})
    as_alice = login_as(alice)

    missing = as_alice.get(CURRENT)
    assert missing.status_code == 400
    assert missing.json()["error"]["code"] == "organisation_required"

    assert as_alice.get(CURRENT, headers=_org(org_a)).json()["name"] == "Brokerage A"
    assert as_alice.get(CURRENT, headers=_org(org_b)).json()["name"] == "Brokerage B"

    malformed = as_alice.get(CURRENT, headers={"X-Organisation-ID": "not-a-uuid"})
    assert malformed.status_code == 422


def test_user_without_membership_has_no_tenant_access(
    make_user: MakeUser, login_as: LoginAs
) -> None:
    assert login_as(make_user("loner@example.com")).get(CURRENT).status_code == 400


def test_tenant_routes_require_sign_in(client: TestClient) -> None:
    for path in (ORGANISATIONS, CURRENT, MEMBERS, AUDIT):
        assert client.get(path).status_code == 401, path
    create = client.post(ORGANISATIONS, json={"name": "X", "kind": "brokerage"})
    assert create.status_code == 401


def test_only_platform_admin_creates_organisations(
    db: Session, make_user: MakeUser, make_org: MakeOrg, login_as: LoginAs
) -> None:
    root = make_user("root@example.com", platform_admin=True)
    admin = make_user("admin@a.example")
    make_org("Brokerage A", {admin: "brokerage_admin"})
    body = {"name": "New Brokerage", "kind": "brokerage"}

    # A brokerage administrator is not a platform administrator.
    assert login_as(admin).post(ORGANISATIONS, json=body).status_code == 403

    as_root = login_as(root)
    created = as_root.post(ORGANISATIONS, json=body)
    assert created.status_code == 201
    event = db.scalars(select(AuditEvent).where(AuditEvent.action == "organisation.created")).one()
    assert event.actor_user_id == root.id
    assert str(event.organisation_id) == created.json()["id"]

    invalid = as_root.post(ORGANISATIONS, json={"name": "   ", "kind": "franchise"})
    assert invalid.status_code == 422
    assert {d["field"] for d in invalid.json()["error"]["details"]} == {"body.name", "body.kind"}


def test_platform_admin_can_act_in_any_organisation_but_others_see_only_their_own(
    make_user: MakeUser, make_org: MakeOrg, login_as: LoginAs
) -> None:
    root = make_user("root@example.com", platform_admin=True)
    alice = make_user("alice@a.example")
    org_a = make_org("Brokerage A", {alice: "agent"})
    make_org("Brokerage B")
    as_root = login_as(root)

    assert as_root.get(MEMBERS, headers=_org(org_a)).status_code == 200
    assert as_root.get(AUDIT, headers=_org(org_a)).status_code == 200
    names = {item["name"] for item in as_root.get(ORGANISATIONS).json()["items"]}
    assert {"Brokerage A", "Brokerage B"} <= names

    mine = login_as(alice).get(ORGANISATIONS).json()["items"]
    assert [item["name"] for item in mine] == ["Brokerage A"]


def test_member_list_paginates_without_gaps_or_repeats(
    make_user: MakeUser, make_org: MakeOrg, login_as: LoginAs
) -> None:
    users = [make_user(f"user{n}@a.example") for n in range(5)]
    make_org("Brokerage A", dict.fromkeys(users, "agent"))
    as_user = login_as(users[0])

    seen: list[str] = []
    cursor: str | None = None
    for _ in range(10):
        params: dict[str, str | int] = {"limit": 2}
        if cursor:
            params["cursor"] = cursor
        page = as_user.get(MEMBERS, params=params).json()
        seen += [member["email"] for member in page["items"]]
        cursor = page["next_cursor"]
        if cursor is None:
            break

    assert sorted(seen) == sorted(user.email for user in users)

    # A cursor with the wrong shape or types is rejected, not passed to the database.
    for bad in ({"sort": "not-a-date", "id": "x"}, {"n": 1}, {"sort": 5, "id": 5}):
        response = as_user.get(MEMBERS, params={"cursor": encode_cursor(bad)})
        assert response.status_code == 400, bad
        assert response.json()["error"]["code"] == "invalid_cursor"
