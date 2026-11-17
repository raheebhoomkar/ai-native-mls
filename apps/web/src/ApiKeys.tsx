import { useEffect, useState, type FormEvent } from "react";

import { api, describeError, useAction, type CurrentOrganisation } from "./api";
import type { components } from "./api-schema";

type Key = components["schemas"]["ApiKeyOut"];
type Created = components["schemas"]["CreatedApiKeyOut"];

const SCOPES = [
  ["listing:read", "Read listings"],
  ["listing:write", "Create and edit listings"],
] as const;

const when = (iso: string | null | undefined) =>
  iso ? new Date(iso).toLocaleString("en-IN") : "never";

/** API keys for third-party clients. Administrators only. */
export function ApiKeys({
  organisation,
}: {
  organisation: CurrentOrganisation;
}) {
  const [keys, setKeys] = useState<Key[] | null>(null);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [created, setCreated] = useState<Created | null>(null);
  const [name, setName] = useState("");
  const [scopes, setScopes] = useState<string[]>(["listing:read"]);
  const [rate, setRate] = useState(60);
  const [reloadKey, setReloadKey] = useState(0);
  const action = useAction();

  useEffect(() => {
    let cancelled = false;
    api<Key[]>("/api-keys")
      .then((list) => {
        if (!cancelled) setKeys(list);
      })
      .catch((error) => {
        if (!cancelled) setLoadError(describeError(error));
      });
    return () => {
      cancelled = true;
    };
  }, [organisation.id, reloadKey]);

  function create(event: FormEvent) {
    event.preventDefault();
    void action.run(async () => {
      setCreated(
        await api<Created>("/api-keys", {
          method: "POST",
          body: { name, scopes, rate_limit_per_minute: rate },
        }),
      );
      setName("");
      setReloadKey((k) => k + 1);
    });
  }

  function revoke(key: Key) {
    void action.run(async () => {
      await api(`/api-keys/${key.id}`, { method: "DELETE" });
      setReloadKey((k) => k + 1);
    });
  }

  return (
    <section aria-labelledby="keys-heading">
      <h2 id="keys-heading">API keys</h2>
      <p>
        A key lets another system use the {organisation.name} API. It acts as
        you, with no more than its scopes, and stops working if you leave the
        organisation. See the developer guide in <code>docs/api</code>.
      </p>

      <form onSubmit={create} aria-label="New API key">
        <p>
          <label>
            Name{" "}
            <input
              value={name}
              onChange={(e) => setName(e.target.value)}
              required
              maxLength={100}
            />
          </label>
        </p>
        <fieldset>
          <legend>Scopes</legend>
          {SCOPES.map(([scope, label]) => (
            <label key={scope}>
              <input
                type="checkbox"
                checked={scopes.includes(scope)}
                onChange={(e) =>
                  setScopes((current) =>
                    e.target.checked
                      ? [...current, scope]
                      : current.filter((s) => s !== scope),
                  )
                }
              />{" "}
              {label} (<code>{scope}</code>)
            </label>
          ))}
        </fieldset>
        <p>
          <label>
            Requests per minute{" "}
            <input
              type="number"
              min={1}
              max={600}
              value={rate}
              onChange={(e) => setRate(Number(e.target.value))}
            />
          </label>
        </p>
        <button type="submit" disabled={action.busy || scopes.length === 0}>
          Create key
        </button>
      </form>

      {action.error && <p role="alert">{action.error}</p>}
      {created && (
        <div className="notice" role="status">
          <p>
            Copy this key now. It is not shown again:{" "}
            <code data-testid="new-key">{created.key}</code>
          </p>
        </div>
      )}

      {loadError && <p role="alert">{loadError}</p>}
      {keys?.length === 0 && <p>No keys yet.</p>}
      {keys && keys.length > 0 && (
        <div className="table-scroll">
          <table>
            <caption>Keys</caption>
            <thead>
              <tr>
                <th scope="col">Name</th>
                <th scope="col">Starts with</th>
                <th scope="col">Scopes</th>
                <th scope="col">Use</th>
                <th scope="col">Last used</th>
                <th scope="col">Actions</th>
              </tr>
            </thead>
            <tbody>
              {keys.map((key) => (
                <tr key={key.id}>
                  <td>{key.name}</td>
                  <td>
                    <code>{key.prefix}</code>
                  </td>
                  <td>{key.scopes.join(", ")}</td>
                  <td>
                    {key.requests_last_minute} of {key.rate_limit_per_minute}{" "}
                    this minute
                  </td>
                  <td>{when(key.last_used_at)}</td>
                  <td>
                    {key.revoked_at ? (
                      `Revoked ${when(key.revoked_at)}`
                    ) : (
                      <button
                        type="button"
                        disabled={action.busy}
                        onClick={() => revoke(key)}
                      >
                        Revoke
                      </button>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </section>
  );
}
