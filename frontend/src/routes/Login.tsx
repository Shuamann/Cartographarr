import { useEffect, useState } from "react";
import { api, useApi, type AuthState } from "../lib/api";
import { brandingUrl, useBranding } from "../lib/useBranding";

/* Trending film art, slowly crossfading behind the form.
 *
 * Trending rather than this library: the sign-in page is public, so anything
 * feeding it is too, and serving the server's own artwork would tell a visitor
 * what is in the library. TMDB's image CDN needs no key and allows direct
 * loading, so these come straight from it.
 */
function Backdrop() {
  const backdrops = useApi<{ images: string[] }>("/auth/backdrops");
  const images = backdrops.data?.images ?? [];
  const [index, setIndex] = useState(0);

  useEffect(() => {
    if (images.length < 2) return;
    const timer = setInterval(() => setIndex((i) => (i + 1) % images.length), 9000);
    return () => clearInterval(timer);
  }, [images.length]);

  if (images.length === 0) return null;

  return (
    <div className="backdrop" aria-hidden="true">
      {images.map((src, i) => (
        <img key={src} src={src} alt="" className={i === index ? "on" : ""} />
      ))}
      <div className="backdrop-veil" />
    </div>
  );
}

/* One screen, two jobs.
 *
 * On a brand new install nobody has an account yet, so it offers to create the
 * admin one and then closes for good. After that it is a plain sign in. Same
 * shape as Radarr and Seerr, and it keeps a password out of your docker
 * configuration.
 */
export default function Login({ state, onDone }: { state: AuthState; onDone: () => void }) {
  const claiming = state.needs_claim;
  const branding = useBranding();
  const name = branding.data?.app_name ?? "Cartographarr";
  const hasLogo = branding.data?.images.login_logo;

  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [confirm, setConfirm] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const mismatch = claiming && confirm.length > 0 && password !== confirm;
  const ready =
    username.trim().length > 0 && password.length > 0 && (!claiming || (!mismatch && confirm));

  async function submit(event: React.FormEvent) {
    event.preventDefault();
    setBusy(true);
    setError(null);
    try {
      await api.post(claiming ? "/auth/claim" : "/auth/login", { username, password });
      onDone();
    } catch (err) {
      setError((err as Error).message);
      setBusy(false);
    }
  }

  return (
    <div className="setup login">
      <Backdrop />
      <form className="setup-card" onSubmit={submit}>
        <header>
          {hasLogo ? (
            <img className="brand-logo" src={brandingUrl("login_logo")} alt={name} />
          ) : (
            <h1>{name}</h1>
          )}
          <p className="muted">
            {claiming
              ? "Create the admin account. This is offered once, then the app is locked."
              : "Sign in to continue."}
          </p>
        </header>

        <section>
          <label>
            Username
            <input
              value={username}
              autoFocus
              autoComplete="username"
              onChange={(e) => setUsername(e.target.value)}
            />
          </label>

          <label>
            Password
            <input
              type="password"
              value={password}
              autoComplete={claiming ? "new-password" : "current-password"}
              onChange={(e) => setPassword(e.target.value)}
            />
            {claiming && <small>At least 10 characters.</small>}
          </label>

          {claiming && (
            <label>
              Confirm password
              <input
                type="password"
                value={confirm}
                autoComplete="new-password"
                onChange={(e) => setConfirm(e.target.value)}
              />
              {mismatch && <small className="danger-text">These do not match.</small>}
            </label>
          )}

          {error && <p className="note bad-note">{error}</p>}

          <button className="btn primary" type="submit" disabled={!ready || busy}>
            {busy ? "Working…" : claiming ? "Create account" : "Sign in"}
          </button>
        </section>

        {state.proxy_enabled && !claiming && (
          <p className="muted small">
            A reverse proxy can sign you in automatically. This form stays available so a proxy
            misconfiguration cannot lock you out.
          </p>
        )}
      </form>
    </div>
  );
}
