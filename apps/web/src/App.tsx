import { useCallback, useEffect, useState } from "react";

type Health =
  | { state: "loading" }
  | { state: "ok" }
  | { state: "error"; message: string; requestId: string | null };

async function fetchHealth(): Promise<Health> {
  try {
    const response = await fetch("/api/v1/health");
    if (response.ok) return { state: "ok" };
    // Non-2xx responses use the API error envelope; a proxy failure may not be JSON.
    const body = await response.json().catch(() => null);
    return {
      state: "error",
      message:
        body?.error?.message ??
        `The API responded with status ${response.status}.`,
      requestId: response.headers.get("X-Request-ID"),
    };
  } catch {
    return {
      state: "error",
      message: "The API is not reachable.",
      requestId: null,
    };
  }
}

export function App() {
  const [health, setHealth] = useState<Health>({ state: "loading" });

  const check = useCallback(() => {
    setHealth({ state: "loading" });
    void fetchHealth().then(setHealth);
  }, []);

  useEffect(() => {
    let cancelled = false;
    void fetchHealth().then((result) => {
      if (!cancelled) setHealth(result);
    });
    return () => {
      cancelled = true;
    };
  }, []);

  return (
    <main>
      <h1>AI-Native MLS</h1>
      <p>Foundation build. Sign-in and listings arrive in later sprints.</p>
      <section aria-labelledby="status-heading">
        <h2 id="status-heading">System status</h2>
        <dl aria-live="polite">
          <dt>API and database</dt>
          <dd>
            {health.state === "loading" && "Checking…"}
            {health.state === "ok" && "Operational"}
            {health.state === "error" && (
              <span role="alert">
                Unavailable: {health.message}
                {health.requestId && ` (request ${health.requestId})`}
              </span>
            )}
          </dd>
        </dl>
        <button
          type="button"
          onClick={check}
          disabled={health.state === "loading"}
        >
          Check again
        </button>
      </section>
    </main>
  );
}
