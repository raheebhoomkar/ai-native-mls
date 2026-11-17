import { useCallback, useEffect, useState } from "react";

import { api, describeError } from "./api";

type Health =
  { state: "loading" } | { state: "ok" } | { state: "error"; message: string };

async function fetchHealth(): Promise<Health> {
  try {
    await api("/health");
    return { state: "ok" };
  } catch (error) {
    return { state: "error", message: describeError(error) };
  }
}

export function SystemStatus() {
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
    <section
      aria-labelledby="status-heading"
      className="system-status"
      data-health={health.state}
    >
      <h2 id="status-heading">System status</h2>
      <dl aria-live="polite">
        <dt>API and database</dt>
        <dd>
          {health.state === "loading" && "Checking…"}
          {health.state === "ok" && "Operational"}
          {health.state === "error" && (
            <span role="alert">Unavailable: {health.message}</span>
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
  );
}
