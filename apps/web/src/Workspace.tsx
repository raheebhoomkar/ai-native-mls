/** The signed-in application: navigation, organisation switcher and pages. */

import { useCallback, useEffect, useRef, useState } from "react";
import {
  Link,
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
import { Brand, Icon, initials } from "./ui";

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
  const page = useRef<HTMLDivElement>(null);

  // After navigating, close the phone menu and move focus to the new page, as a full
  // page load would; screen readers then start reading the new content.
  useEffect(() => {
    // eslint-disable-next-line react-hooks/set-state-in-effect -- follows the route
    setMenuOpen(false);
    if (pathname === firstPath.current) return;
    firstPath.current = pathname;
    document.getElementById("content")?.focus();
    // A soft entrance for the new page; skipped where motion is unwanted or unsupported.
    if (window.matchMedia?.("(prefers-reduced-motion: reduce)").matches) return;
    page.current?.animate?.(
      [
        { opacity: 0, transform: "translateY(10px)" },
        { opacity: 1, transform: "none" },
      ],
      { duration: 480, easing: "cubic-bezier(0.16, 1, 0.3, 1)" },
    );
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

  const roleText = organisation
    ? `${organisation.my_role ? ROLE_LABELS[organisation.my_role] : "Platform administrator"} · ${organisation.kind === "mls" ? "MLS" : "Brokerage"}`
    : current.state === "loading"
      ? "…"
      : "No organisation selected";
  const showAdmin =
    canSeeMembers || canManageKeys || canAudit || isPlatformAdmin;

  return (
    <div className="shell">
      <div className="topbar">
        <div className="brand">
          <Brand />
        </div>
        <button
          type="button"
          className="menu-button"
          aria-expanded={menuOpen}
          aria-controls="main-nav"
          onClick={() => setMenuOpen((open) => !open)}
        >
          <Icon name="menu" />
          Menu
        </button>
      </div>
      <div
        className={menuOpen ? "scrim open" : "scrim"}
        aria-hidden="true"
        onClick={() => setMenuOpen(false)}
      />
      <header className={menuOpen ? "sidebar open" : "sidebar"}>
        <div className="brand">
          <Brand />
        </div>
        <div className="org-card">
          {organisation && (
            <span className="org-name">{organisation.name}</span>
          )}
          <span className="org-role">{roleText}</span>
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
        </div>
        <nav id="main-nav" aria-label="Main" className="nav">
          <p className="nav-group">Workspace</p>
          <NavLink to="/" end>
            <Icon name="home" />
            Home
          </NavLink>
          {canSeeListings && (
            <NavLink to="/listings">
              <Icon name="grid" />
              Listings
            </NavLink>
          )}
          {canReview && (
            <NavLink to="/compliance">
              <Icon name="shield" />
              Review queue
            </NavLink>
          )}
          {canSeeListings && (
            <NavLink to="/monitor">
              <Icon name="activity" />
              Monitor
            </NavLink>
          )}
          {organisation && (
            <NotificationsLink organisationId={organisation.id} />
          )}
          {showAdmin && <p className="nav-group">Administration</p>}
          {canSeeMembers && (
            <NavLink to="/members">
              <Icon name="users" />
              Members
            </NavLink>
          )}
          {canManageKeys && (
            <NavLink to="/api-keys">
              <Icon name="key" />
              API keys
            </NavLink>
          )}
          {canManageKeys && (
            <NavLink to="/webhooks">
              <Icon name="link" />
              Webhooks
            </NavLink>
          )}
          {canAudit && (
            <NavLink to="/audit">
              <Icon name="file" />
              Audit
            </NavLink>
          )}
          {isPlatformAdmin && (
            <NavLink to="/admin">
              <Icon name="columns" />
              Platform
            </NavLink>
          )}
          <p className="nav-group">Account</p>
          <NavLink to="/profile">
            <Icon name="user" />
            Profile
          </NavLink>
        </nav>
        <div className="sidebar-foot">
          <span className="avatar" aria-hidden="true">
            {initials(me.user.full_name)}
          </span>
          <span className="user-meta">
            <span className="user-name">{me.user.full_name}</span>
            <small>{me.user.email}</small>
          </span>
          <button type="button" className="small" onClick={signOut}>
            <Icon name="logout" />
            Sign out
          </button>
        </div>
      </header>
      <main id="content" tabIndex={-1}>
        <h1 className="visually-hidden">AI-Native MLS</h1>
        <div className="page" ref={page}>
          {signOutError && <p role="alert">{signOutError}</p>}
          {optionsError && <p role="alert">{optionsError}</p>}
          {current.state === "error" && <p role="alert">{current.message}</p>}

          <Routes>
            <Route
              path="/"
              element={
                <Home
                  me={me}
                  current={current}
                  isPlatformAdmin={isPlatformAdmin}
                />
              }
            />
            <Route
              path="/listings"
              element={
                organisation && canSeeListings ? (
                  <Listings organisation={organisation} />
                ) : current.state === "loading" ? (
                  <p className="loading">Loading…</p>
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
                    <Route
                      path="/listings/import"
                      element={<ListingImport />}
                    />
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
              <Route
                path="/listings/*"
                element={<p className="loading">Loading…</p>}
              />
            )}
            <Route
              path="/compliance"
              element={
                organisation && canReview ? (
                  <ComplianceQueue organisation={organisation} />
                ) : current.state === "ready" || current.state === "error" ? (
                  <p>You cannot review listings in this organisation.</p>
                ) : (
                  <p className="loading">Loading…</p>
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
                  <p className="loading">Loading…</p>
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
                  <p className="loading">Loading…</p>
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
                  <p className="loading">Loading…</p>
                )
              }
            />
            <Route
              path="/notifications"
              element={
                organisation ? (
                  <Notifications organisation={organisation} />
                ) : (
                  <p className="loading">Loading…</p>
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
                  <p className="loading">Loading…</p>
                )
              }
            />
            <Route
              path="/members"
              element={
                organisation && canSeeMembers ? (
                  <Members me={me} organisation={organisation} />
                ) : current.state === "loading" ? (
                  <p className="loading">Loading…</p>
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
        </div>
      </main>
    </div>
  );
}

function greeting(): string {
  const hour = new Date().getHours();
  if (hour < 12) return "Good morning";
  return hour < 17 ? "Good afternoon" : "Good evening";
}

/** Home: who is signed in and where, then the role-aware overview. */
function Home({
  me,
  current,
  isPlatformAdmin,
}: {
  me: Me;
  current: Current;
  isPlatformAdmin: boolean;
}) {
  const organisation = current.state === "ready" ? current.organisation : null;
  const firstName = me.user.full_name.split(/\s+/)[0];
  return (
    <>
      <section
        aria-labelledby="account-heading"
        className="page-head home-head"
      >
        <div>
          <p className="eyebrow">
            {new Date().toLocaleDateString("en-IN", {
              weekday: "long",
              day: "numeric",
              month: "long",
            })}
          </p>
          <h2 id="account-heading">
            {greeting()}, {firstName}
          </h2>
          <p className="lede">
            Signed in as {me.user.full_name} ({me.user.email})
            {isPlatformAdmin && " · Platform administrator"}
          </p>
          {current.state === "loading" && (
            <p className="loading">Loading organisation…</p>
          )}
          {current.state === "none" && (
            <p className="lede">
              {isPlatformAdmin
                ? "No organisations exist yet. Create one under Platform."
                : "You do not belong to an organisation yet. Ask an administrator for an invitation link."}
            </p>
          )}
          {organisation && (
            <p className="lede">
              Working in {organisation.name} (
              {organisation.kind === "mls" ? "MLS" : "brokerage"}) as{" "}
              {organisation.my_role
                ? ROLE_LABELS[organisation.my_role]
                : "platform administrator, not a member"}
              .
            </p>
          )}
        </div>
        {organisation?.my_permissions.includes("listing:read") && (
          <div className="page-actions">
            <Link className="button-link" to="/listings">
              <Icon name="grid" />
              Browse listings
            </Link>
          </div>
        )}
      </section>
      {organisation && <Dashboard organisation={organisation} />}
      <SystemStatus />
    </>
  );
}
