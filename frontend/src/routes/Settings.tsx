import { useEffect, useState } from "react";
import { api, useApi, type AppUser, type IntegrationStatus, type Setting } from "../lib/api";
import { brandingUrl, useBranding } from "../lib/useBranding";

type Section = { title: string; note?: string; keys: string[] };
type Area = { area: string; blurb?: string; sections: Section[] };

/* Grouped into areas rather than one long list, because the page covers four
 * unrelated jobs: connecting to things, how it behaves, who gets in, and how
 * it looks. */
const AREAS: Area[] = [
  {
    area: "Connections",
    blurb: "Where Cartographarr gets its data, and what it can link out to.",
    sections: [
      {
        title: "Tautulli",
        note: "Required. Everything except sharing goes through Tautulli.",
        keys: [
          "tautulli_url",
          "tautulli_local_url",
          "tautulli_api_key",
          "tautulli_verify_ssl",
          "tautulli_timeout",
        ],
      },
      {
        title: "Plex",
        note: "The server id comes from Tautulli and enables the Plex link. A token is only needed to manage sharing.",
        keys: ["plex_token", "plex_machine_identifier"],
      },
      {
        title: "Map locations",
        note: "A free MaxMind GeoLite2 account. Without it there are no map pins.",
        keys: [
          "maxmind_account_id",
          "maxmind_license_key",
          "geoip_auto_update",
          "geoip_update_interval_days",
        ],
      },
      {
        title: "Radarr and Sonarr",
        note: "Optional. Links a title straight to it. Films go to Radarr, anything episodic to Sonarr.",
        keys: ["radarr_url", "radarr_api_key", "sonarr_url", "sonarr_api_key"],
      },
      {
        title: "Seerr",
        note: "Optional. Shows who requested a title. Seerr is what Overseerr and Jellyseerr merged into.",
        keys: ["seerr_url", "seerr_api_key"],
      },
      {
        title: "Notifications",
        note: "One Apprise URL per line or comma separated, covering Discord, ntfy, Gotify, Pushover, Telegram, email and most others. Rules can then warn you instead of stopping a stream.",
        keys: ["apprise_urls", "webhook_url"],
      },
      {
        title: "Artwork and monitoring",
        note: "A TMDB key puts trending film art behind the sign-in page. The Uptime Kuma URL is pinged after each sync, monitoring the sync rather than just the container.",
        keys: ["tmdb_api_key", "uptime_kuma_push_url"],
      },
    ],
  },
  {
    area: "Behaviour",
    blurb: "How often it looks, and what it does when a rule matches.",
    sections: [
      {
        title: "Syncing",
        keys: [
          "sync_interval_minutes",
          "slow_sync_interval_minutes",
          "sync_page_size",
          "metadata_concurrency",
        ],
      },
      {
        title: "Shared account detection",
        note: "How eagerly to flag one account being used in two places. Locations are only accurate to a city, so these guard against crying wolf: pairs are ignored when either fix is vaguer than the accuracy limit, or they are closer together than the minimum distance.",
        keys: ["impossible_kmh", "impossible_min_km", "impossible_max_accuracy_km"],
      },
      {
        title: "Rules and live activity",
        note: "Dry run records what rules would have done without stopping anything. Turn it off once the enforcement log looks right.",
        keys: [
          "enforce_enabled",
          "enforce_dry_run",
          "enforce_cooldown_seconds",
          "activity_poll_seconds",
        ],
      },
    ],
  },
  {
    area: "Access",
    blurb: "Who can sign in, and how.",
    sections: [
      {
        title: "Reverse proxy sign in",
        note: "Only turn this on with an authenticating proxy in front. The header is honoured solely from the addresses listed here, otherwise anyone who can reach the app could claim to be anyone.",
        keys: [
          "auth_proxy_enabled",
          "trusted_proxy_ips",
          "proxy_user_header",
          "proxy_email_header",
          "proxy_default_role",
        ],
      },
      { title: "Sessions", keys: ["session_ttl_hours", "session_cookie_secure"] },
    ],
  },
];

const LABELS: Record<string, string> = {
  tautulli_url: "Tautulli URL",
  tautulli_local_url: "Local URL",
  tautulli_api_key: "API key",
  tautulli_verify_ssl: "Verify SSL certificate",
  tautulli_timeout: "Request timeout (seconds)",
  plex_token: "Plex token",
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
  radarr_url: "Radarr URL",
  radarr_api_key: "Radarr API key",
  sonarr_url: "Sonarr URL",
  sonarr_api_key: "Sonarr API key",
  app_name: "App name",
  tmdb_api_key: "TMDB API key",
  uptime_kuma_push_url: "Uptime Kuma push URL",
  seerr_url: "Seerr URL",
  seerr_api_key: "Seerr API key",
  apprise_urls: "Apprise URLs",
  webhook_url: "Webhook URL",
  impossible_kmh: "Flag faster than (km/h)",
  impossible_min_km: "Ignore closer than (km)",
  impossible_max_accuracy_km: "Ignore vaguer than (km)",
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
    <div className="pad scroll settings">
      <SettingsForm />
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

      {AREAS.map((area) => (
        <Area key={area.area} title={area.area} blurb={area.blurb}>
          {area.sections.map((section) => (
            <section key={section.title} className="card-section">
              <h3>{section.title}</h3>
              {section.note && <p className="muted small">{section.note}</p>}
              <div className="grid2">{section.keys.map(field)}</div>
            </section>
          ))}
          {area.area === "Connections" && <Integrations />}
        </Area>
      ))}

      <Area title="Appearance" blurb="The name and marks shown around the app.">
        <section className="card-section">
          <h3>Name</h3>
          <div className="grid2">{field("app_name")}</div>
        </section>
        <BrandingImages />
      </Area>

      <Area title="Accounts" blurb="Who can sign in to Cartographarr.">
        <Accounts />
        <ChangePassword />
      </Area>
    </>
  );
}

/* One titled card per area, so the page reads as four jobs rather than one
 * long list of unrelated switches. */
function Area({
  title,
  blurb,
  children,
}: {
  title: string;
  blurb?: string;
  children: React.ReactNode;
}) {
  return (
    <section className="area">
      <header>
        <h2>{title}</h2>
        {blurb && <p className="muted small">{blurb}</p>}
      </header>
      <div className="area-body">{children}</div>
    </section>
  );
}

const MARKS: { kind: "login_logo" | "logo" | "icon"; label: string; hint: string }[] = [
  { kind: "login_logo", label: "Sign-in logo", hint: "Shown large above the sign-in form" },
  { kind: "logo", label: "Interface logo", hint: "Small, in the top bar. Often a different crop" },
  { kind: "icon", label: "Icon", hint: "Browser tab and any installed shortcut" },
];

function BrandingImages() {
  const branding = useBranding();
  const [busy, setBusy] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  // Bumped after an upload so the browser refetches rather than showing the
  // old logo from cache.
  const [version, setVersion] = useState(0);

  async function upload(kind: string, file: File) {
    setBusy(kind);
    setError(null);
    const body = new FormData();
    body.append("file", file);
    try {
      const response = await fetch(`/api/branding/${kind}`, { method: "PUT", body });
      if (!response.ok) {
        const detail = await response.json().catch(() => ({}));
        throw new Error(detail.detail ?? response.statusText);
      }
      setVersion((v) => v + 1);
      branding.reload();
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setBusy(null);
    }
  }

  async function clear(kind: string) {
    await api.del(`/branding/${kind}`).catch(() => {});
    setVersion((v) => v + 1);
    branding.reload();
  }

  return (
    <section className="card-section">
      <h3>Logos and icon</h3>
      <p className="muted small">
        Stored on the server rather than linked, so they keep working without depending on
        anywhere else. PNG, JPEG, WebP, SVG, GIF or ICO, up to 4 MB.
      </p>
      {error && <p className="note bad-note">{error}</p>}

      <div className="mini-list">
        {MARKS.map((mark) => {
          const isSet = branding.data?.images[mark.kind];
          return (
            <div key={mark.kind} className="mini">
              <div className="row">
                {isSet ? (
                  <img
                    className="brand-preview"
                    src={`${brandingUrl(mark.kind)}?v=${version}`}
                    alt=""
                  />
                ) : (
                  <div className="brand-preview empty" />
                )}
                <div>
                  <strong>{mark.label}</strong>
                  <p className="muted small">{mark.hint}</p>
                </div>
              </div>

              <div className="row">
                <label className="tab file-button">
                  {busy === mark.kind ? "Uploading…" : isSet ? "Replace" : "Upload"}
                  <input
                    type="file"
                    accept="image/*"
                    hidden
                    onChange={(e) => {
                      const file = e.target.files?.[0];
                      if (file) upload(mark.kind, file);
                      e.target.value = "";
                    }}
                  />
                </label>
                {isSet && (
                  <button className="tab danger-text" onClick={() => clear(mark.kind)}>
                    Remove
                  </button>
                )}
              </div>
            </div>
          );
        })}
      </div>
    </section>
  );
}

function Integrations() {
  const list = useApi<IntegrationStatus[]>("/integrations");
  const [testing, setTesting] = useState<string | null>(null);

  async function test(name: string) {
    setTesting(name);
    try {
      await api.post(`/integrations/${name}/test`);
    } finally {
      setTesting(null);
      list.reload();
    }
  }

  return (
    <section className="card-section">
      <h3>Reachability</h3>
      <div className="mini-list">
        {list.data?.map((i) => (
          <div key={i.name} className="mini">
            <div>
              <strong>{i.label}</strong>
              <p className="muted small">
                {i.detail}
                {i.version ? ` (${i.version})` : ""}
              </p>
            </div>
            <div className="row">
              <span className={i.ok ? "pill ok" : i.configured ? "pill warn" : "pill"}>
                {i.ok ? "connected" : i.configured ? "not reachable" : "not set up"}
              </span>
              <button
                className="tab"
                disabled={!i.configured || testing === i.name}
                onClick={() => test(i.name)}
              >
                {testing === i.name ? "Testing…" : "Test"}
              </button>
            </div>
          </div>
        ))}
      </div>
    </section>
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
    <section className="card-section">
      <div className="row-between">
        <h3>People</h3>
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
    <section className="card-section">
      <h3>Your password</h3>
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
