import { useCallback, useEffect, useState } from "react";

import { api, ApiError, describeError, type Me } from "./api";
import { LoginForm } from "./LoginForm";
import { SystemStatus } from "./SystemStatus";

type Session =
  | { state: "loading" }
  | { state: "signed-out" }
  | { state: "signed-in"; me: Me }
  | { state: "error"; message: string };

const ROLE_LABELS: Record<Me["memberships"][number]["role"], string> = {
  mls_admin: "MLS administrator",
  brokerage_admin: "Brokerage administrator",
  broker: "Broker",
  agent: "Agent",
  api_consumer: "API consumer",
};

async function loadSession(): Promise<Session> {
  try {
    return { state: "signed-in", me: await api<Me>("/auth/me") };
  } catch (error) {
    if (error instanceof ApiError && error.status === 401)
      return { state: "signed-out" };
    return { state: "error", message: describeError(error) };
  }
}

export function App() {
  const [session, setSession] = useState<Session>({ state: "loading" });
  const [signOutError, setSignOutError] = useState<string | null>(null);

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
    setSession({ state: "signed-out" });
  }

  return (
    <main>
      <h1>AI-Native MLS</h1>

      {session.state === "loading" && <p>Loading…</p>}

      {session.state === "error" && (
        <section>
          <p role="alert">Could not load your session: {session.message}</p>
          <button type="button" onClick={retry}>
            Try again
          </button>
        </section>
      )}

      {session.state === "signed-out" && (
        <LoginForm
          onSignedIn={(me) => setSession({ state: "signed-in", me })}
        />
      )}

      {session.state === "signed-in" && (
        <section aria-labelledby="account-heading">
          <h2 id="account-heading">Your account</h2>
          <p>
            Signed in as {session.me.user.full_name} ({session.me.user.email})
            {session.me.user.is_platform_admin && " · Platform administrator"}
          </p>
          <h3>Organisations</h3>
          {session.me.memberships.length === 0 ? (
            <p>You do not belong to an organisation yet.</p>
          ) : (
            <ul>
              {session.me.memberships.map((membership) => (
                <li key={membership.organisation_id}>
                  {membership.organisation_name} —{" "}
                  {ROLE_LABELS[membership.role]}
                </li>
              ))}
            </ul>
          )}
          {signOutError && <p role="alert">{signOutError}</p>}
          <button type="button" onClick={signOut}>
            Sign out
          </button>
        </section>
      )}

      <SystemStatus />
    </main>
  );
}
