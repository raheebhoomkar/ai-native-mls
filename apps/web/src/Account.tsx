/** Profile (every user) and platform administration (platform administrators). */

import { type FormEvent, useState } from "react";

import { api, type Me, type Organisation, tokenLink, useAction } from "./api";
import { OneTimeLink } from "./OneTimeLink";

export function Profile({
  me,
  onChanged,
}: {
  me: Me;
  onChanged: (me: Me) => void;
}) {
  const [fullName, setFullName] = useState(me.user.full_name);
  const [current, setCurrent] = useState("");
  const [next, setNext] = useState("");
  const [saved, setSaved] = useState<"name" | "password" | null>(null);
  const name = useAction();
  const password = useAction();

  function saveName(event: FormEvent) {
    event.preventDefault();
    setSaved(null);
    void name.run(async () => {
      onChanged(
        await api<Me>("/auth/me", {
          method: "PATCH",
          body: { full_name: fullName },
        }),
      );
      setSaved("name");
    });
  }

  function savePassword(event: FormEvent) {
    event.preventDefault();
    setSaved(null);
    void password.run(async () => {
      await api("/auth/password", {
        method: "POST",
        body: { current_password: current, new_password: next },
      });
      setCurrent("");
      setNext("");
      setSaved("password");
    });
  }

  return (
    <section aria-labelledby="profile-heading">
      <h2 id="profile-heading">Your profile</h2>
      <p>Email: {me.user.email}</p>
      <form onSubmit={saveName} aria-label="Change name">
        <label htmlFor="profile-name">Full name</label>
        <input
          id="profile-name"
          required
          maxLength={200}
          autoComplete="name"
          value={fullName}
          onChange={(e) => setFullName(e.target.value)}
        />
        {name.error && <p role="alert">{name.error}</p>}
        {saved === "name" && <p role="status">Name saved.</p>}
        <button type="submit" disabled={name.busy}>
          Save name
        </button>
      </form>

      <form onSubmit={savePassword} aria-labelledby="password-heading">
        <h3 id="password-heading">Change password</h3>
        <label htmlFor="current-password">Current password</label>
        <input
          id="current-password"
          type="password"
          required
          autoComplete="current-password"
          value={current}
          onChange={(e) => setCurrent(e.target.value)}
        />
        <label htmlFor="new-password">New password</label>
        <input
          id="new-password"
          type="password"
          required
          minLength={12}
          maxLength={128}
          autoComplete="new-password"
          aria-describedby="new-password-hint"
          value={next}
          onChange={(e) => setNext(e.target.value)}
        />
        <small id="new-password-hint">
          At least 12 characters. Your other devices will be signed out.
        </small>
        {password.error && <p role="alert">{password.error}</p>}
        {saved === "password" && <p role="status">Password changed.</p>}
        <button type="submit" disabled={password.busy}>
          Change password
        </button>
      </form>
    </section>
  );
}

export function PlatformAdmin({
  organisations,
  onOrganisationCreated,
  onWorkIn,
}: {
  /** Loaded by the workspace for the organisation menu; null while loading. */
  organisations: Organisation[] | null;
  onOrganisationCreated: () => void;
  onWorkIn: (organisationId: string) => void;
}) {
  const [name, setName] = useState("");
  const [kind, setKind] = useState<"brokerage" | "mls">("brokerage");
  const [created, setCreated] = useState<string | null>(null);
  const [email, setEmail] = useState("");
  const [link, setLink] = useState<{ email: string; url: string } | null>(null);
  const create = useAction();
  const reset = useAction();

  function createOrganisation(event: FormEvent) {
    event.preventDefault();
    setCreated(null);
    void create.run(async () => {
      const organisation = await api<{ name: string }>("/organisations", {
        method: "POST",
        body: { name, kind },
      });
      setCreated(organisation.name);
      setName("");
      onOrganisationCreated();
    });
  }

  function issueReset(event: FormEvent) {
    event.preventDefault();
    setLink(null);
    void reset.run(async () => {
      const issued = await api<{ email: string; token: string }>(
        "/auth/password-reset-links",
        { method: "POST", body: { email } },
      );
      setLink({
        email: issued.email,
        url: tokenLink("reset-password", issued.token),
      });
      setEmail("");
    });
  }

  return (
    <section aria-labelledby="admin-heading">
      <h2 id="admin-heading">Platform administration</h2>

      <h3 id="orgs-heading">Organisations</h3>
      {organisations === null ? (
        <p>Loading…</p>
      ) : organisations.length === 0 ? (
        <p>No organisations yet. Create one below.</p>
      ) : (
        <div className="table-scroll">
          <table aria-labelledby="orgs-heading">
            <thead>
              <tr>
                <th scope="col">Name</th>
                <th scope="col">Kind</th>
                <th scope="col">
                  <span className="visually-hidden">Actions</span>
                </th>
              </tr>
            </thead>
            <tbody>
              {organisations.map((o) => (
                <tr key={o.id}>
                  <th scope="row">{o.name}</th>
                  <td>{o.kind === "mls" ? "MLS" : "Brokerage"}</td>
                  <td>
                    <button
                      type="button"
                      aria-label={`Work in ${o.name}`}
                      onClick={() => onWorkIn(o.id)}
                    >
                      Work in it
                    </button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      <form onSubmit={createOrganisation} aria-labelledby="create-org-heading">
        <h3 id="create-org-heading">Create an organisation</h3>
        <label htmlFor="org-name">Name</label>
        <input
          id="org-name"
          required
          maxLength={200}
          value={name}
          onChange={(e) => setName(e.target.value)}
        />
        <label htmlFor="org-kind">Kind</label>
        <select
          id="org-kind"
          value={kind}
          onChange={(e) => setKind(e.target.value as "brokerage" | "mls")}
        >
          <option value="brokerage">Brokerage</option>
          <option value="mls">MLS</option>
        </select>
        {create.error && <p role="alert">{create.error}</p>}
        {created && (
          <p role="status">
            Created {created}. Select it in the organisation menu, then invite
            its first administrator from Members.
          </p>
        )}
        <button type="submit" disabled={create.busy}>
          Create organisation
        </button>
      </form>

      <form onSubmit={issueReset} aria-labelledby="reset-link-heading">
        <h3 id="reset-link-heading">Issue a password reset link</h3>
        <label htmlFor="reset-email">User's email</label>
        <input
          id="reset-email"
          type="email"
          required
          value={email}
          onChange={(e) => setEmail(e.target.value)}
        />
        {reset.error && <p role="alert">{reset.error}</p>}
        <button type="submit" disabled={reset.busy}>
          Create reset link
        </button>
      </form>
      {link && (
        <OneTimeLink
          label={`Reset link for ${link.email} created. It expires in 24 hours.`}
          link={link.url}
        />
      )}
    </section>
  );
}
