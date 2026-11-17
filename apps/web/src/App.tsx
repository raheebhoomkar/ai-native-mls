import { type ReactNode, useCallback, useEffect, useState } from "react";
import { HashRouter, Route, Routes } from "react-router";

import { api, ApiError, describeError, type Me } from "./api";
import { LoginForm } from "./LoginForm";
import { OfflineBanner } from "./Offline";
import { AcceptInvite, ResetPassword } from "./PublicLinks";
import { SystemStatus } from "./SystemStatus";
import { Arches, Brand, BrandMark } from "./ui";
import { Workspace } from "./Workspace";

/** Sign-in and one-time link pages: an editorial panel beside a single card. */
function AuthFrame({
  lede = "Sign in to your brokerage or MLS workspace.",
  children,
}: {
  lede?: string;
  children: ReactNode;
}) {
  return (
    <div className="auth">
      <div className="auth-aside">
        <div className="brand">
          <Brand sub="Multiple listing service" />
        </div>
        <div className="auth-statement">
          <p>
            Every property, presented with <em>intent</em>.
          </p>
          <p>
            Listings, photographs, AI review and workflows for brokerages and
            MLS teams, in one considered workspace.
          </p>
        </div>
        <ul className="auth-facts">
          <li>
            <strong>AI-assisted</strong> photo reading and policy checks
          </li>
          <li>
            <strong>Role-aware</strong> for agents, brokers and administrators
          </li>
          <li>
            <strong>Networked</strong> listings shared across organisations
          </li>
        </ul>
        <Arches />
      </div>
      <main id="content" tabIndex={-1} className="auth-main">
        <div className="auth-card">
          <h1>AI-Native MLS</h1>
          <p className="lede">{lede}</p>
          {children}
        </div>
      </main>
    </div>
  );
}

const LINK_LEDE = "Complete the step this one-time link was made for.";

type Session =
  | { state: "loading" }
  | { state: "signed-out" }
  | { state: "signed-in"; me: Me }
  | { state: "error"; message: string };

async function loadSession(): Promise<Session> {
  try {
    return { state: "signed-in", me: await api<Me>("/auth/me") };
  } catch (error) {
    if (error instanceof ApiError && error.status === 401)
      return { state: "signed-out" };
    return { state: "error", message: describeError(error) };
  }
}

function Main() {
  const [session, setSession] = useState<Session>({ state: "loading" });
  const signedIn = (me: Me) => setSession({ state: "signed-in", me });

  const retry = useCallback(() => {
    setSession({ state: "loading" });
    void loadSession().then(setSession);
  }, []);

  useEffect(() => {
    let cancelled = false;
    void loadSession().then((result) => {
      if (!cancelled) setSession(result);
    });
    return () => {
      cancelled = true;
    };
  }, []);

  if (session.state === "loading")
    return (
      <main id="content" tabIndex={-1} className="splash">
        <h1 className="visually-hidden">AI-Native MLS</h1>
        <BrandMark />
        <p className="loading">Loading…</p>
      </main>
    );
  if (session.state === "error")
    return (
      <AuthFrame>
        <section>
          <p role="alert">Could not load your session: {session.message}</p>
          <button type="button" onClick={retry}>
            Try again
          </button>
        </section>
      </AuthFrame>
    );
  if (session.state === "signed-out")
    return (
      <AuthFrame>
        <LoginForm onSignedIn={signedIn} />
        <SystemStatus />
      </AuthFrame>
    );
  return (
    <Workspace
      me={session.me}
      onMeChanged={signedIn}
      onSignedOut={() => setSession({ state: "signed-out" })}
    />
  );
}

export function App() {
  return (
    // Hash routing: deep links work on any static host, and one-time link tokens stay in
    // the URL fragment, which browsers do not send to servers.
    <HashRouter>
      {/* A plain #content link would change the hash route, so focus the target directly. */}
      <a
        className="skip-link"
        href="#content"
        onClick={(event) => {
          event.preventDefault();
          document.getElementById("content")?.focus();
        }}
      >
        Skip to main content
      </a>
      <OfflineBanner />
      <Routes>
        <Route
          path="/accept-invite"
          element={
            <AuthFrame lede={LINK_LEDE}>
              <AcceptInvite />
            </AuthFrame>
          }
        />
        <Route
          path="/reset-password"
          element={
            <AuthFrame lede={LINK_LEDE}>
              <ResetPassword />
            </AuthFrame>
          }
        />
        <Route path="*" element={<Main />} />
      </Routes>
    </HashRouter>
  );
}
