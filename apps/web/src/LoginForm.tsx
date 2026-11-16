import { type FormEvent, useState } from "react";

import { api, describeError, type Me } from "./api";

export function LoginForm({ onSignedIn }: { onSignedIn: (me: Me) => void }) {
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function submit(event: FormEvent) {
    event.preventDefault();
    setSubmitting(true);
    setError(null);
    try {
      onSignedIn(
        await api<Me>("/auth/login", {
          method: "POST",
          body: { email, password },
        }),
      );
    } catch (caught) {
      setError(describeError(caught));
      setSubmitting(false);
    }
  }

  return (
    <form onSubmit={submit} aria-labelledby="sign-in-heading">
      <h2 id="sign-in-heading">Sign in</h2>
      <label htmlFor="email">Email</label>
      <input
        id="email"
        type="email"
        autoComplete="username"
        required
        value={email}
        onChange={(event) => setEmail(event.target.value)}
      />
      <label htmlFor="password">Password</label>
      <input
        id="password"
        type="password"
        autoComplete="current-password"
        required
        value={password}
        onChange={(event) => setPassword(event.target.value)}
      />
      {error && <p role="alert">{error}</p>}
      <button type="submit" disabled={submitting}>
        {submitting ? "Signing in…" : "Sign in"}
      </button>
    </form>
  );
}
