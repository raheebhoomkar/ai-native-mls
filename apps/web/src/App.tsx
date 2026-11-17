import { useCallback, useEffect, useState } from "react";
import { HashRouter, Route, Routes } from "react-router";

import { api, ApiError, describeError, type Me } from "./api";
import { LoginForm } from "./LoginForm";
import { OfflineBanner } from "./Offline";
import { AcceptInvite, ResetPassword } from "./PublicLinks";
import { SystemStatus } from "./SystemStatus";
import { Workspace } from "./Workspace";

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

  if (session.state === "loading") return <p>Loading…</p>;
  if (session.state === "error")
    return (
      <section>
        <p role="alert">Could not load your session: {session.message}</p>
        <button type="button" onClick={retry}>
          Try again
        </button>
      </section>
    );
  if (session.state === "signed-out")
    return (
      <>
        <LoginForm onSignedIn={signedIn} />
        <SystemStatus />
      </>
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
      <main id="content" tabIndex={-1}>
        <h1>AI-Native MLS</h1>
        <Routes>
          <Route path="/accept-invite" element={<AcceptInvite />} />
          <Route path="/reset-password" element={<ResetPassword />} />
          <Route path="*" element={<Main />} />
        </Routes>
      </main>
    </HashRouter>
  );
}
