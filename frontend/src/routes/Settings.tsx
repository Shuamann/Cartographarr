import { useEffect, useState } from "react";
import { api, useApi, type AppUser, type Setting } from "../lib/api";

const SECTIONS: { title: string; note?: string; keys: string[] }[] = [
  {
    title: "Tautulli",
    keys: ["tautulli_url", "tautulli_local_url", "tautulli_api_key", "tautulli_verify_ssl", "tautulli_timeout"],
  },
  {
    title: "Plex",
    note: "The server id is discovered from Tautulli, and enables the Plex deep link.",
    keys: ["plex_machine_identifier"],
  },
  {
    title: "Map locations",
    note: "A free MaxMind GeoLite2 account. Without it there are no map pins.",
    keys: ["maxmind_account_id", "maxmind_license_key", "geoip_auto_update", "geoip_update_interval_days"],
  },
  {
    title: "Syncing",
    keys: ["sync_interval_minutes", "slow_sync_interval_minutes", "sync_page_size", "metadata_concurrency"],
  },
  {
    title: "Rules and live activity",
    note: "Dry run records what rules would have done without stopping anything. Turn it off once the enforcement log looks right.",
    keys: ["enforce_enabled", "enforce_dry_run", "enforce_cooldown_seconds", "activity_poll_seconds"],
  },
  {
    title: "Reverse proxy sign in",
    note: "Only turn this on with an authenticating proxy in front. The header is honoured solely from the addresses listed here, otherwise anyone who can reach the app could claim to be anyone.",
    keys: ["auth_proxy_enabled", "trusted_proxy_ips", "proxy_user_header", "proxy_email_header", "proxy_default_role"],
  },
  {
    title: "Sessions",
    keys: ["session_ttl_hours", "session_cookie_secure"],
  },
];

const LABELS: Record<string, string> = {
  tautulli_url: "Tautulli URL",
  tautulli_local_url: "Local URL",
  tautulli_api_key: "API key",
  tautulli_verify_ssl: "Verify SSL certificate",
  tautulli_timeout: "Request timeout (seconds)",
  plex_machine_identifier: "Plex server id",
  maxmind_account_id: "MaxMind account ID",
  maxmind_license_key: "MaxMind license key",
  geoip_auto_update: "Keep databases updated",
  geoip_update_interval_days: "Update every (days)",
  sync_interval_minutes: "Sync history every (minutes)",
  slow_sync_interval_minutes: "Sync users and libraries every (minutes)",
  sync_page_size: "Rows per request",
  metadata_concurrency: "Parallel metadata lookups",
  enforce_enabled: "Run rules",
  enforce_dry_run: "Dry run",
  enforce_cooldown_seconds: "Cooldown per rule (seconds)",
  activity_poll_seconds: "Check activity every (seconds)",
  auth_proxy_enabled: "Trust a reverse proxy",
  trusted_proxy_ips: "Trusted proxy addresses",
  proxy_user_header: "Username header",
  proxy_email_header: "Email header",
  proxy_default_role: "Role for new proxy users",
  session_ttl_hours: "Stay signed in for (hours)",
  session_cookie_secure: "Only send the cookie over HTTPS",
};

export default function SettingsRoute({ isAdmin }: { isAdmin: boolean }) {
  if (!isAdmin) {
    return (
      <div className="pad">
        <h1>Settings</h1>
        <p className="note warn-note">Settings need an admin account.</p>
      </div>
    );
  }
  return (
    <div className="pad scroll">
      <SettingsForm />
      <Accounts />
      <ChangePassword />
    </div>
  );
}

function SettingsForm() {
  const settings = useApi<Setting[]>("/settings");
  const [draft, setDraft] = useState<Record<string, unknown>>({});
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [saved, setSaved] = useState(false);

  const byKey = new Map((settings.data ?? []).map((s) => [s.key, s]));
  const dirty = Object.keys(draft).length > 0;

  useEffect(() => {
    if (!saved) return;
    const timer = setTimeout(() => setSaved(false), 2500);
    return () => clearTimeout(timer);
  }, [saved]);

  async function save() {
    setSaving(true);
    setError(null);
    try {
      await api.put("/settings", draft);
      setDraft({});
      setSaved(true);
      settings.reload();
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setSaving(false);
    }
  }

  function field(key: string) {
    const setting = byKey.get(key);
    if (!setting) return null;

    const locked = !setting.editable;
    const value = key in draft ? draft[key] : setting.value;
    const isBool = typeof setting.value === "boolean";
    const isSecret = /key|token|secret|password/.test(key);
    // A masked secret must not be saved back as literal asterisks.
    const masked = isSecret && setting.value === "********";

    return (
      <label key={key} className={locked ? "locked" : undefined}>
        {LABELS[key] ?? key}
        {locked && <span className="pill">set by environment</span>}

        {isBool ? (
          <select
            disabled={locked}
            value={String(value)}
            onChange={(e) => setDraft({ ...draft, [key]: e.target.value === "true" })}
          >
            <option value="true">On</option>
            <option value="false">Off</option>
          </select>
        ) : key === "proxy_default_role" ? (
          <select
            disabled={locked}
            value={String(value)}
            onChange={(e) => setDraft({ ...draft, [key]: e.target.value })}
          >
            <option value="viewer">Viewer</option>
            <option value="admin">Admin</option>
          </select>
        ) : (
          <input
            disabled={locked}
            type={isSecret && !(key in draft) ? "password" : "text"}
            placeholder={masked ? "Unchanged" : ""}
            value={masked && !(key in draft) ? "" : String(Array.isArray(value) ? value.join(", ") : value ?? "")}
            onChange={(e) => {
              const raw = e.target.value;
              setDraft({
                ...draft,
                [key]: key === "trusted_proxy_ips" ? raw : raw,
              });
            }}
          />
        )}

        {locked && (
          <small>
            An environment variable supplies this, so it wins over anything set here. Remove it
            from your container configuration to edit it in the UI.
          </small>
        )}
        {key === "trusted_proxy_ips" && !locked && (
          <small>Comma separated. Addresses or CIDRs, for example 172.17.0.0/16.</small>
        )}
      </label>
    );
  }

  if (settings.error) return <p className="note bad-note">{settings.error}</p>;

  return (
    <>
      <div className="row-between">
        <h1>Settings</h1>
        <div className="row">
          {saved && <span className="muted small">Saved.</span>}
          <button className="btn primary" onClick={save} disabled={!dirty || saving}>
            {saving ? "Saving…" : dirty ? `Save ${Object.keys(draft).length} change(s)` : "Saved"}
          </button>
        </div>
      </div>

      {error && <p className="note bad-note">{error}</p>}

      {SECTIONS.map((section) => (
        <section key={section.title}>
          <h2 className="section-head">{section.title}</h2>
          {section.note && <p className="muted small">{section.note}</p>}
          <div className="grid2">{section.keys.map(field)}</div>
        </section>
      ))}
    </>
  );
}

function Accounts() {
  const users = useApi<AppUser[]>("/auth/users");
  const [adding, setAdding] = useState(false);
  const [form, setForm] = useState({ username: "", password: "", role: "viewer", email: "" });
  const [error, setError] = useState<string | null>(null);

  async function add() {
    setError(null);
    try {
      await api.post("/auth/users", form);
      setForm({ username: "", password: "", role: "viewer", email: "" });
      setAdding(false);
      users.reload();
    } catch (err) {
      setError((err as Error).message);
    }
  }

  async function change(user: AppUser, values: Record<string, unknown>) {
    setError(null);
    try {
      await api.put(`/auth/users/${user.id}`, values);
      users.reload();
    } catch (err) {
      setError((err as Error).message);
    }
  }

  async function remove(user: AppUser) {
    if (!confirm(`Delete the account "${user.username}"?`)) return;
    setError(null);
    try {
      await api.del(`/auth/users/${user.id}`);
      users.reload();
    } catch (err) {
      setError((err as Error).message);
    }
  }

  return (
    <section>
      <div className="row-between">
        <h2 className="section-head">Accounts</h2>
        <button className="btn" onClick={() => setAdding(!adding)}>
          {adding ? "Cancel" : "Add account"}
        </button>
      </div>
      <p className="muted small">
        Viewers see the map, history and statistics. Admins also get rules, stopping streams and
        these settings.
      </p>

      {error && <p className="note bad-note">{error}</p>}

      {adding && (
        <div className="editor">
          <div className="grid2">
            <label>
              Username
              <input value={form.username} onChange={(e) => setForm({ ...form, username: e.target.value })} />
            </label>
            <label>
              Password
              <input
                type="password"
                value={form.password}
                onChange={(e) => setForm({ ...form, password: e.target.value })}
              />
              <small>At least 10 characters.</small>
            </label>
            <label>
              Role
              <select value={form.role} onChange={(e) => setForm({ ...form, role: e.target.value })}>
                <option value="viewer">Viewer</option>
                <option value="admin">Admin</option>
              </select>
            </label>
            <label>
              Email (optional)
              <input value={form.email} onChange={(e) => setForm({ ...form, email: e.target.value })} />
            </label>
          </div>
          <button className="btn primary" onClick={add} disabled={!form.username || !form.password}>
            Create
          </button>
        </div>
      )}

      <table className="table">
        <tbody>
          {users.data?.map((u) => (
            <tr key={u.id}>
              <td>
                {u.username}
                {u.auth_source !== "local" && <span className="pill">{u.auth_source}</span>}
                {!u.is_active && <span className="pill warn">disabled</span>}
              </td>
              <td className="muted">{u.email}</td>
              <td>
                <select value={u.role} onChange={(e) => change(u, { role: e.target.value })}>
                  <option value="viewer">Viewer</option>
                  <option value="admin">Admin</option>
                </select>
              </td>
              <td className="muted small">
                {u.last_login ? new Date(u.last_login).toLocaleString() : "never signed in"}
              </td>
              <td>
                <button className="tab" onClick={() => change(u, { is_active: !u.is_active })}>
                  {u.is_active ? "Disable" : "Enable"}
                </button>
                <button className="tab danger-text" onClick={() => remove(u)}>
                  Delete
                </button>
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </section>
  );
}

function ChangePassword() {
  const [current, setCurrent] = useState("");
  const [next, setNext] = useState("");
  const [message, setMessage] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  async function submit() {
    setError(null);
    setMessage(null);
    try {
      await api.post("/auth/me/password", { current_password: current, new_password: next });
      setCurrent("");
      setNext("");
      setMessage("Password changed. Other sessions were signed out.");
    } catch (err) {
      setError((err as Error).message);
    }
  }

  return (
    <section>
      <h2 className="section-head">Your password</h2>
      <div className="grid2">
        <label>
          Current password
          <input type="password" value={current} onChange={(e) => setCurrent(e.target.value)} />
        </label>
        <label>
          New password
          <input type="password" value={next} onChange={(e) => setNext(e.target.value)} />
        </label>
      </div>
      {message && <p className="note ok-note">{message}</p>}
      {error && <p className="note bad-note">{error}</p>}
      <button className="btn" onClick={submit} disabled={!current || !next}>
        Change password
      </button>
    </section>
  );
}
