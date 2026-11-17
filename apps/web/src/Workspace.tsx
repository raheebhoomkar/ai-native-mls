/** The signed-in application: navigation, organisation switcher and pages. */

import { useCallback, useEffect, useRef, useState } from "react";
import {
  NavLink,
  Navigate,
  Route,
  Routes,
  useLocation,
  useNavigate,
} from "react-router";

import { PlatformAdmin, Profile } from "./Account";
import {
  api,
  ApiError,
  type CurrentOrganisation,
  describeError,
  type Me,
  type Organisation,
  ROLE_LABELS,
  setActiveOrganisation,
} from "./api";
import { ApiKeys } from "./ApiKeys";
import { Audit } from "./Audit";
import { ComplianceQueue } from "./ComplianceQueue";
import { Dashboard } from "./Dashboard";
import { Monitor } from "./Monitor";
import { Notifications, NotificationsLink } from "./Notifications";
import { Webhooks } from "./Webhooks";
import { ListingDetail } from "./ListingDetail";
import { EditListing, NewListing } from "./ListingForm";
import { ListingImport } from "./ListingImport";
import { Listings } from "./Listings";
import { Members } from "./Members";
import { SystemStatus } from "./SystemStatus";

const STORAGE_KEY = "mls.organisation";

function remembered(): string | null {
  try {
    return window.localStorage.getItem(STORAGE_KEY);
  } catch {
    return null; // storage can be blocked; the first organisation is used instead
  }
}

function remember(id: string) {
  try {
    window.localStorage.setItem(STORAGE_KEY, id);
  } catch {
    // not remembered across visits; nothing else depends on it
  }
}

type Current =
  | { state: "loading" }
  | { state: "none" }
  | { state: "ready"; organisation: CurrentOrganisation }
  | { state: "error"; message: string };

export function Workspace({
  me,
  onMeChanged,
  onSignedOut,
}: {
  me: Me;
  onMeChanged: (me: Me) => void;
  onSignedOut: () => void;
}) {
  const [options, setOptions] = useState<Organisation[] | null>(null);
  const [optionsError, setOptionsError] = useState<string | null>(null);
  const [selected, setSelected] = useState<string | null>(null);
  const [current, setCurrent] = useState<Current>({ state: "loading" });
  const [signOutError, setSignOutError] = useState<string | null>(null);
  const isPlatformAdmin = me.user.is_platform_admin;
  const [menuOpen, setMenuOpen] = useState(false);
  const navigate = useNavigate();
  const { pathname } = useLocation();
  const firstPath = useRef(pathname);

  // After navigating, close the phone menu and move focus to the new page, as a full
  // page load would; screen readers then start reading the new content.
  useEffect(() => {
    // eslint-disable-next-line react-hooks/set-state-in-effect -- follows the route
    setMenuOpen(false);
    if (pathname === firstPath.current) return;
    firstPath.current = pathname;
    document.getElementById("content")?.focus();
  }, [pathname]);

  // Members choose among their memberships; platform administrators among all organisations.
  const loadOptions = useCallback(async () => {
    try {
      const list = isPlatformAdmin
        ? (await api<{ items: Organisation[] }>("/organisations?limit=100"))
            .items
        : me.memberships.map((m) => ({
            id: m.organisation_id,
            name: m.organisation_name,
            kind: m.organisation_kind,
          }));
      setOptions(list);
      setOptionsError(null);
      setSelected((previous) => {
        const wanted = previous ?? remembered();
        return list.some((o) => o.id === wanted)
          ? wanted
          : (list[0]?.id ?? null);
      });
    } catch (error) {
      setOptionsError(describeError(error));
    }
  }, [isPlatformAdmin, me.memberships]);

  useEffect(() => {
    // eslint-disable-next-line react-hooks/set-state-in-effect -- loads remote data on mount
    void loadOptions();
  }, [loadOptions]);

  useEffect(() => {
    if (options === null) return;
    let cancelled = false;
    setActiveOrganisation(selected);
    if (selected === null) {
      // eslint-disable-next-line react-hooks/set-state-in-effect -- mirrors the selection
      setCurrent({ state: "none" });
      return;
    }
    remember(selected);
    setCurrent({ state: "loading" });
    api<CurrentOrganisation>("/organisations/current")
      .then(
        (organisation) =>
          !cancelled && setCurrent({ state: "ready", organisation }),
      )
      .catch(
        (error) =>
          !cancelled &&
          setCurrent({ state: "error", message: describeError(error) }),
      );
    return () => {
      cancelled = true;
    };
  }, [options, selected]);

  async function signOut() {
    setSignOutError(null);
    try {
      await api("/auth/logout", { method: "POST" });
    } catch (error) {
      // An already-expired session is as good as signed out.
      if (!(error instanceof ApiError && error.status === 401)) {
        setSignOutError(describeError(error));
        return;
      }
    }
    setActiveOrganisation(null);
    onSignedOut();
  }

  const organisation = current.state === "ready" ? current.organisation : null;
  const canSeeMembers = organisation?.my_permissions.includes("member:read");
  const canSeeListings = organisation?.my_permissions.includes("listing:read");
  const canReview = organisation?.my_permissions.includes("listing:publish");
  const canManageKeys = organisation?.my_permissions.includes("member:manage");
  const canAudit = organisation?.my_permissions.includes("audit:read");

  return (
    <>
      <header className="bar">
        <button
          type="button"
          className="menu-button"
          aria-expanded={menuOpen}
          aria-controls="main-nav"
          onClick={() => setMenuOpen((open) => !open)}
        >
          Menu
        </button>
        <nav
          id="main-nav"
          aria-label="Main"
          className={menuOpen ? "open" : undefined}
        >
          <NavLink to="/" end>
            Home
          </NavLink>
          {canSeeListings && <NavLink to="/listings">Listings</NavLink>}
          {canReview && <NavLink to="/compliance">Review queue</NavLink>}
          {canSeeListings && <NavLink to="/monitor">Monitor</NavLink>}
          {canSeeMembers && <NavLink to="/members">Members</NavLink>}
          {canManageKeys && <NavLink to="/api-keys">API keys</NavLink>}
          {canManageKeys && <NavLink to="/webhooks">Webhooks</NavLink>}
          {canAudit && <NavLink to="/audit">Audit</NavLink>}
          {organisation && (
            <NotificationsLink organisationId={organisation.id} />
          )}
          <NavLink to="/profile">Profile</NavLink>
          {isPlatformAdmin && <NavLink to="/admin">Platform</NavLink>}
        </nav>
        <div className="bar-end">
          {options && options.length > 1 && (
            <label>
              Organisation{" "}
              <select
                value={selected ?? ""}
                onChange={(e) => setSelected(e.target.value)}
              >
                {options.map((option) => (
                  <option key={option.id} value={option.id}>
                    {option.name}
                  </option>
                ))}
              </select>
            </label>
          )}
          <button type="button" onClick={signOut}>
            Sign out
          </button>
        </div>
      </header>
      {signOutError && <p role="alert">{signOutError}</p>}
      {optionsError && <p role="alert">{optionsError}</p>}
      {current.state === "error" && <p role="alert">{current.message}</p>}

      <Routes>
        <Route
          path="/"
          element={
            <>
              <section aria-labelledby="account-heading">
                <h2 id="account-heading">Your account</h2>
                <p>
                  Signed in as {me.user.full_name} ({me.user.email})
                  {isPlatformAdmin && " · Platform administrator"}
                </p>
                {current.state === "loading" && <p>Loading organisation…</p>}
                {current.state === "none" && (
                  <p>
                    {isPlatformAdmin
                      ? "No organisations exist yet. Create one under Platform."
                      : "You do not belong to an organisation yet. Ask an administrator for an invitation link."}
                  </p>
                )}
                {organisation && (
                  <p>
                    Working in {organisation.name} (
                    {organisation.kind === "mls" ? "MLS" : "brokerage"}) as{" "}
                    {organisation.my_role
                      ? ROLE_LABELS[organisation.my_role]
                      : "platform administrator, not a member"}
                    .
                  </p>
                )}
              </section>
              {organisation && <Dashboard organisation={organisation} />}
              <SystemStatus />
            </>
          }
        />
        <Route
          path="/listings"
          element={
            organisation && canSeeListings ? (
              <Listings organisation={organisation} />
            ) : current.state === "loading" ? (
              <p>Loading…</p>
            ) : (
              <p>You cannot view listings in this organisation.</p>
            )
          }
        />
        {organisation && canSeeListings && (
          <>
            {organisation.my_permissions.includes("listing:write") && (
              <>
                <Route
                  path="/listings/new"
                  element={<NewListing organisation={organisation} />}
                />
                <Route path="/listings/import" element={<ListingImport />} />
              </>
            )}
            <Route
              path="/listings/:id"
              element={
                <ListingDetail
                  organisation={organisation}
                  myUserId={me.user.id}
                />
              }
            />
            <Route
              path="/listings/:id/edit"
              element={<EditListing organisation={organisation} />}
            />
          </>
        )}
        {current.state === "loading" && (
          <Route path="/listings/*" element={<p>Loading…</p>} />
        )}
        <Route
          path="/compliance"
          element={
            organisation && canReview ? (
              <ComplianceQueue organisation={organisation} />
            ) : current.state === "ready" || current.state === "error" ? (
              <p>You cannot review listings in this organisation.</p>
            ) : (
              <p>Loading…</p>
            )
          }
        />
        <Route
          path="/api-keys"
          element={
            organisation && canManageKeys ? (
              <ApiKeys organisation={organisation} />
            ) : current.state === "ready" || current.state === "error" ? (
              <p>Only administrators manage API keys.</p>
            ) : (
              <p>Loading…</p>
            )
          }
        />
        <Route
          path="/webhooks"
          element={
            organisation && canManageKeys ? (
              <Webhooks organisation={organisation} />
            ) : current.state === "ready" || current.state === "error" ? (
              <p>Only administrators manage webhooks.</p>
            ) : (
              <p>Loading…</p>
            )
          }
        />
        <Route
          path="/audit"
          element={
            organisation && canAudit ? (
              <Audit organisation={organisation} />
            ) : current.state === "ready" || current.state === "error" ? (
              <p>Only administrators see the audit log.</p>
            ) : (
              <p>Loading…</p>
            )
          }
        />
        <Route
          path="/notifications"
          element={
            organisation ? (
              <Notifications organisation={organisation} />
            ) : (
              <p>Loading…</p>
            )
          }
        />
        <Route
          path="/monitor"
          element={
            organisation && canSeeListings ? (
              <Monitor organisation={organisation} />
            ) : current.state === "ready" || current.state === "error" ? (
              <p>You cannot see workflows in this organisation.</p>
            ) : (
              <p>Loading…</p>
            )
          }
        />
        <Route
          path="/members"
          element={
            organisation && canSeeMembers ? (
              <Members me={me} organisation={organisation} />
            ) : current.state === "loading" ? (
              <p>Loading…</p>
            ) : (
              <p>You cannot view members of this organisation.</p>
            )
          }
        />
        <Route
          path="/profile"
          element={<Profile me={me} onChanged={onMeChanged} />}
        />
        <Route
          path="/admin"
          element={
            isPlatformAdmin ? (
              <PlatformAdmin
                organisations={options}
                onOrganisationCreated={() => void loadOptions()}
                onWorkIn={(id) => {
                  setSelected(id);
                  void navigate("/");
                }}
              />
            ) : (
              <Navigate to="/" replace />
            )
          }
        />
        <Route path="*" element={<Navigate to="/" replace />} />
      </Routes>
    </>
  );
}
