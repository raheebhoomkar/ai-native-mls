/** Pages opened from a one-time link. They work whether or not anyone is signed in. */

import { type FormEvent, useEffect, useState } from "react";
import { Link, useSearchParams } from "react-router";

import { api, describeError, ROLE_LABELS, type Role, useAction } from "./api";

type Preview = {
  organisation_name: string;
  email: string;
  role: Role;
  account_exists: boolean;
};

const PASSWORD_HINT = "At least 12 characters.";

function SignInLink() {
  // A full reload so the sign-in page starts from a clean state.
  return <a href={window.location.pathname}>Go to sign in</a>;
}

export function AcceptInvite() {
  const token = useSearchParams()[0].get("token") ?? "";
  const [preview, setPreview] = useState<Preview | null>(null);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [fullName, setFullName] = useState("");
  const [password, setPassword] = useState("");
  const [joined, setJoined] = useState<string | null>(null);
  const accept = useAction();

  useEffect(() => {
    let cancelled = false;
    api<Preview>("/invitations/preview", { method: "POST", body: { token } })
      .then((result) => !cancelled && setPreview(result))
      .catch((error) => !cancelled && setLoadError(describeError(error)));
    return () => {
      cancelled = true;
    };
  }, [token]);

  function submit(event: FormEvent) {
    event.preventDefault();
    void accept.run(async () => {
      const body = preview?.account_exists
        ? { token }
        : { token, full_name: fullName, password };
      const result = await api<{ organisation_name: string }>(
        "/invitations/accept",
        { method: "POST", body },
      );
      setJoined(result.organisation_name);
    });
  }

  if (joined)
    return (
      <section>
        <h2>Invitation accepted</h2>
        <p>You are now a member of {joined}. Sign in to continue.</p>
        <SignInLink />
      </section>
    );
  if (loadError)
    return (
      <section>
        <h2>Invitation</h2>
        <p role="alert">{loadError}</p>
        <p>Ask the person who invited you for a new link.</p>
      </section>
    );
  if (!preview) return <p className="loading">Loading…</p>;

  return (
    <form onSubmit={submit} aria-labelledby="invite-heading">
      <h2 id="invite-heading">Join {preview.organisation_name}</h2>
      <p>
        {preview.email} is invited as {ROLE_LABELS[preview.role]}.
      </p>
      {preview.account_exists ? (
        <p>
          This email already has an account. Accepting adds the organisation to
          it; your password stays the same.
        </p>
      ) : (
        <>
          <label htmlFor="invite-name">Your full name</label>
          <input
            id="invite-name"
            required
            maxLength={200}
            autoComplete="name"
            value={fullName}
            onChange={(e) => setFullName(e.target.value)}
          />
          <label htmlFor="invite-password">Choose a password</label>
          <input
            id="invite-password"
            type="password"
            required
            minLength={12}
            maxLength={128}
            autoComplete="new-password"
            aria-describedby="invite-password-hint"
            value={password}
            onChange={(e) => setPassword(e.target.value)}
          />
          <small id="invite-password-hint">{PASSWORD_HINT}</small>
        </>
      )}
      {accept.error && <p role="alert">{accept.error}</p>}
      <button type="submit" disabled={accept.busy}>
        {accept.busy ? "Accepting…" : "Accept invitation"}
      </button>
    </form>
  );
}

export function ResetPassword() {
  const token = useSearchParams()[0].get("token") ?? "";
  const [password, setPassword] = useState("");
  const [done, setDone] = useState(false);
  const reset = useAction();

  function submit(event: FormEvent) {
    event.preventDefault();
    void reset.run(async () => {
      await api("/auth/password-reset", {
        method: "POST",
        body: { token, new_password: password },
      });
      setDone(true);
    });
  }

  if (done)
    return (
      <section>
        <h2>Password changed</h2>
        <p>
          You have been signed out everywhere. Sign in with the new password.
        </p>
        <SignInLink />
      </section>
    );

  return (
    <form onSubmit={submit} aria-labelledby="reset-heading">
      <h2 id="reset-heading">Set a new password</h2>
      <label htmlFor="reset-password">New password</label>
      <input
        id="reset-password"
        type="password"
        required
        minLength={12}
        maxLength={128}
        autoComplete="new-password"
        aria-describedby="reset-password-hint"
        value={password}
        onChange={(e) => setPassword(e.target.value)}
      />
      <small id="reset-password-hint">{PASSWORD_HINT}</small>
      {reset.error && <p role="alert">{reset.error}</p>}
      <button type="submit" disabled={reset.busy}>
        {reset.busy ? "Saving…" : "Set password"}
      </button>
      <Link to="/">Cancel</Link>
    </form>
  );
}
