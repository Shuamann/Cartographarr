import { useEffect, useState } from "react";
import { api, useApi, type AppUser, type Setting } from "../lib/api";
import { brandingUrl, useBranding } from "../lib/useBranding";

type Section = {
  title: string;
  note?: string;
  keys: string[];
  /* Name the backend knows it by, which gives the section a Test button. */
  test?: string;
  /* Where it usually listens, so a URL can be guessed from the server the
   * rest of the stack is already on. */
  guess?: { key: string; port: number; slug: string; path?: string };
};
type Area = { area: string; blurb?: string; sections: Section[] };

/* Grouped into areas rather than one long list, because the page covers
 * unrelated jobs: connecting to things, how it behaves, who gets in, and how
 * it looks. */
const AREAS: Area[] = [
  {
    area: "Plex and Tautulli",
    blurb: "Required. Where the history, the live streams and the server details come from.",
    sections: [
      {
        title: "Tautulli",
        note: "Everything except sharing goes through Tautulli.",
        test: "tautulli",
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
        test: "plex",
        keys: ["plex_token", "plex_machine_identifier"],
      },
    ],
  },
  {
    area: "Map locations",
    blurb: "Turns an IP address into a place. Without it there are no map pins.",
    sections: [
      {
        title: "MaxMind GeoLite2",
        note: "A free account. Test downloads the databases, so it takes a few seconds.",
        test: "maxmind",
        keys: [
          "maxmind_account_id",
          "maxmind_license_key",
          "geoip_auto_update",
          "geoip_update_interval_days",
        ],
      },
    ],
  },
  {
    area: "Media apps",
    blurb: "Optional. Links a title out to the app that manages it, and shows who asked for it.",
    sections: [
      {
        title: "Radarr",
        note: "Films link straight to their Radarr page.",
        test: "radarr",
        guess: { key: "radarr_url", port: 7878, slug: "radarr" },
        keys: ["radarr_url", "radarr_api_key"],
      },
      {
        title: "Sonarr",
        note: "Shows and episodes link straight to their Sonarr page.",
        test: "sonarr",
        guess: { key: "sonarr_url", port: 8989, slug: "sonarr" },
        keys: ["sonarr_url", "sonarr_api_key"],
      },
      {
        title: "Seerr",
        note: "Shows who requested a title. Seerr is what Overseerr and Jellyseerr merged into.",
        test: "seerr",
        guess: { key: "seerr_url", port: 5055, slug: "seerr" },
        keys: ["seerr_url", "seerr_api_key"],
      },
      {
        title: "TMDB",
        note: "Puts trending film art behind the sign-in page.",
        test: "tmdb",
        keys: ["tmdb_api_key"],
      },
    ],
  },
  {
    area: "Alerts and monitoring",
    blurb: "Optional. Where rules can send a warning, and what watches the sync.",
    sections: [
      {
        title: "Notifications",
        note: "One Apprise URL per line or comma separated, covering Discord, ntfy, Gotify, Pushover, Telegram, email and most others. Test checks they are understood without sending anything.",
        test: "apprise",
        keys: ["apprise_urls"],
      },
      {
        title: "Webhook",
        note: "Receives a JSON post when a rule acts.",
        test: "webhook",
        keys: ["webhook_url"],
      },
      {
        title: "Uptime Kuma",
        note: "A push monitor pinged after each sync, so it watches the sync rather than just the container. Test sends one real ping.",
        test: "uptime_kuma",
        guess: { key: "uptime_kuma_push_url", port: 3001, slug: "uptime", path: "/api/push/" },
        keys: ["uptime_kuma_push_url"],
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

/* Where the rest of the stack probably lives.
 *
 * Self-hosted apps nearly always share a box, so whichever URL is already set
 * says where to look. Two layouts cover almost everyone:
 *
 *   http://192.168.1.10:8181      each app on its own port   -> :7878
 *   https://tautulli.example.com  a proxy, one subdomain each -> radarr.example.com
 *
 * An address with a port, an IP, or a bare hostname is the first kind. A
 * domain name with no port is the second, and its first label is swapped for
 * the app's name, since the port behind a proxy is not reachable anyway.
 */
function isDirect(url: URL): boolean {
  return (
    url.port !== "" ||
    /^\d{1,3}(\.\d{1,3}){3}$/.test(url.hostname) ||
    url.hostname.startsWith("[") ||
    !url.hostname.includes(".")
  );
}

function parse(from: string): URL | null {
  try {
    return new URL(from);
  } catch {
    return null;
  }
}

function guessUrl(url: URL, target: { port: number; slug: string; path?: string }): string {
  const suffix = target.path ?? "";
  if (isDirect(url)) return `${url.protocol}//${url.hostname}:${target.port}${suffix}`;
  const [, ...rest] = url.hostname.split(".");
  return `${url.protocol}//${[target.slug, ...rest].join(".")}${suffix}`;
}

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
      <div className="settings">
        <SettingsForm />
      </div>
    </div>
  );
}

function SettingsForm() {
  const settings = useApi<Setting[]>("/settings");
  const [draft, setDraft] = useState<Record<string, unknown>>({});
  const [saving, setSaving] = useState(false);
  // The one secret currently being looked at. Only ever the focused field, so
  // keys are never left readable on screen.
  const [revealed, setRevealed] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [saved, setSaved] = useState(false);

  const byKey = new Map((settings.data ?? []).map((s) => [s.key, s]));
  const dirty = Object.keys(draft).length > 0;

  function valueOf(key: string): string {
    const v = key in draft ? draft[key] : byKey.get(key)?.value;
    return typeof v === "string" ? v : "";
  }

  // A direct address wins over a proxied one when both are set: it is what
  // the container can most likely reach, and the port guess is the surer one.
  const candidates = ["tautulli_local_url", "tautulli_url", "radarr_url", "sonarr_url", "seerr_url"]
    .map((k) => parse(valueOf(k)))
    .filter((u): u is URL => u !== null && /^https?:$/.test(u.protocol));
  const base = candidates.find(isDirect) ?? candidates[0] ?? null;

  const guesses = new Map<string, string>();
  for (const area of AREAS) {
    for (const section of area.sections) {
      if (section.guess && base) guesses.set(section.guess.key, guessUrl(base, section.guess));
    }
  }

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
            name={`cartographarr-${key}`}
            // Browsers treat a text box next to a password box as a login form
            // and fill in saved credentials. new-password is the one value they
            // reliably respect for secrets; off covers the fields around them.
            autoComplete={isSecret ? "new-password" : "off"}
            spellCheck={false}
            type={isSecret && revealed !== key ? "password" : "text"}
            onFocus={isSecret ? () => setRevealed(key) : undefined}
            onBlur={isSecret ? () => setRevealed(null) : undefined}
            placeholder={masked ? "Unchanged" : guesses.get(key) ?? ""}
            value={masked && !(key in draft) ? "" : String(Array.isArray(value) ? value.join(", ") : value ?? "")}
            onChange={(e) => {
              const next = { ...draft, [key]: e.target.value };
              // Typing a key for an app whose address is still blank fills in
              // the guess, since the key is useless without one.
              const urlKey = key.replace(/_api_key$/, "_url");
              if (urlKey !== key && guesses.has(urlKey) && !valueOf(urlKey)) {
                next[urlKey] = guesses.get(urlKey);
              }
              setDraft(next);
            }}
          />
        )}

        {guesses.has(key) && !valueOf(key) && !locked && (
          <button
            type="button"
            className="linkish small guess"
            onClick={() => setDraft({ ...draft, [key]: guesses.get(key) })}
          >
            Use {guesses.get(key)}
          </button>
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
              <div className="row-between">
                <h3>{section.title}</h3>
                {section.test && (
                  <TestButton
                    name={section.test}
                    values={Object.fromEntries(
                      section.keys.filter((k) => k in draft).map((k) => [k, draft[k]]),
                    )}
                  />
                )}
              </div>
              {section.note && <p className="muted small">{section.note}</p>}
              <div className="grid2">{section.keys.map(field)}</div>
              {section.title === "Syncing" && <SyncNow />}
            </section>
          ))}
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

/* Checks what is typed on the page, not what was last saved, so a new key can
 * be tried before committing to it. Unchanged fields fall back to the saved
 * value on the server, which is how a masked key still gets used. */
function TestButton({ name, values }: { name: string; values: Record<string, unknown> }) {
  const [busy, setBusy] = useState(false);
  const [result, setResult] = useState<{ ok: boolean; detail: string; version?: string | null } | null>(null);

  // A result describes the values it was run against, so it goes stale the
  // moment any of them change.
  const signature = JSON.stringify(values);
  useEffect(() => setResult(null), [signature]);

  async function run() {
    setBusy(true);
    setResult(null);
    try {
      setResult(await api.post(`/integrations/${name}/test`, { values }));
    } catch (err) {
      setResult({ ok: false, detail: (err as Error).message });
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="row test-result">
      {result && (
        <span className={result.ok ? "pill ok" : "pill bad"} title={result.detail}>
          {result.ok ? "OK" : "Failed"}
        </span>
      )}
      {result && (
        <span className="muted small clip">
          {result.detail}
          {result.version ? ` (${result.version})` : ""}
        </span>
      )}
      <button type="button" className="btn" onClick={run} disabled={busy}>
        {busy ? "Testing\u2026" : "Test"}
      </button>
    </div>
  );
}

/* Run both syncs now instead of waiting for the timers: users and libraries,
 * then history, metadata, devices and locations. Handy after restoring a user
 * in Tautulli, or after changing a connection. */
function SyncNow() {
  const [busy, setBusy] = useState(false);
  const [result, setResult] = useState<string | null>(null);
  const [failed, setFailed] = useState(false);

  async function run() {
    setBusy(true);
    setResult(null);
    setFailed(false);
    try {
      const r = await api.post<Record<string, number>>("/sync/run");
      setResult(
        `Done: ${r.users ?? 0} users, ${r.history ?? 0} new plays, ${r.metadata ?? 0} titles, ${r.ips ?? 0} addresses placed.`,
      );
    } catch (err) {
      setFailed(true);
      setResult((err as Error).message);
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="row sync-now">
      <button type="button" className="btn" onClick={run} disabled={busy}>
        {busy ? "Syncing…" : "Sync now"}
      </button>
      {result && <span className={failed ? "small bad-text" : "muted small"}>{result}</span>}
      {!result && (
        <span className="muted small">Users and libraries, then history. Runs by itself at startup and on the timers above.</span>
      )}
    </div>
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
