import { useEffect, useState, type FormEvent } from "react";
import { api, ApiError, type DemoUser, type Me } from "./api";
import { ROLE_LABEL } from "./roles";

export default function Login({ onLoggedIn }: { onLoggedIn: (me: Me) => void }) {
  const [demo, setDemo] = useState<{ password: string; users: DemoUser[] } | null>(null);
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [busy, setBusy] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    api.demoUsers().then(setDemo).catch(() => setDemo(null));
  }, []);

  async function signIn(userEmail: string, userPassword: string) {
    setBusy(userEmail);
    setError(null);
    try {
      await api.login(userEmail, userPassword);
      onLoggedIn(await api.me());
    } catch (e) {
      setError(e instanceof ApiError ? e.message : "Sign-in failed");
    } finally {
      setBusy(null);
    }
  }

  function onSubmit(e: FormEvent) {
    e.preventDefault();
    signIn(email.trim(), password);
  }

  return (
    <main className="login">
      <section className="login-intro">
        <div className="brand">
          <span className="brand-mark" aria-hidden>
            XYZ
          </span>
          <span>PM Assistant</span>
        </div>
        <h1>Ask your projects anything — and only what you're allowed to see.</h1>
        <p className="muted">
          Pick a demo user. Each one has a different role and project access, so the same question gets different
          answers. Permissions are enforced in the backend and the database before the AI sees anything.
        </p>
      </section>

      {demo && (
        <section aria-label="Demo users">
          <h2 className="section-label">Sign in as</h2>
          <div className="user-grid">
            {demo.users.map((u) => (
              <button
                key={u.id}
                className="user-card"
                disabled={busy !== null}
                onClick={() => signIn(u.email, demo.password)}
              >
                <span className={`avatar role-${u.role}`} aria-hidden>
                  {u.name[0]}
                </span>
                <span className="user-card-body">
                  <span className="user-card-name">
                    {u.name}
                    {busy === u.email && <span className="spinner" aria-label="Signing in" />}
                  </span>
                  <span className={`role-badge role-${u.role}`}>{ROLE_LABEL[u.role] ?? u.role}</span>
                  <span className="user-card-scope">
                    {u.role === "ceo"
                      ? "All projects"
                      : u.projects.length
                        ? u.projects.join(", ")
                        : "Explicit document grants only"}
                    {u.organization ? ` · ${u.organization}` : ""}
                  </span>
                </span>
              </button>
            ))}
          </div>
        </section>
      )}

      <details className="manual-login" open={!demo}>
        <summary>Sign in with email and password</summary>
        <form onSubmit={onSubmit}>
          <label>
            Email
            <input type="email" autoComplete="username" value={email} onChange={(e) => setEmail(e.target.value)} required />
          </label>
          <label>
            Password
            <input
              type="password"
              autoComplete="current-password"
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              required
            />
          </label>
          <button className="btn-primary" type="submit" disabled={busy !== null}>
            Sign in
          </button>
        </form>
      </details>

      {error && (
        <p className="error-text" role="alert">
          {error}
        </p>
      )}
    </main>
  );
}
