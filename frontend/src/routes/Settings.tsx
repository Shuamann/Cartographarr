import About from "../components/About";
import HomeLinks from "../components/HomeLinks";
import { ACCENTS, SCHEMES, applyAccent, contrast, setScheme, type Parts, type Scheme } from "../theme/accent";
import Tasks from "../components/Tasks";
import { useEffect, useState } from "react";
import { api, useApi, type AppUser, type Setting } from "../lib/api";
import { brandingUrl, useBranding } from "../lib/useBranding";
import BrandIcon from "../components/BrandIcon";

type Section = {
  title: string;
  note?: string;
  keys: string[];
  /* Name the backend knows it by, which gives the section a Test button. */
  test?: string;
  /* Where it usually listens, so a URL can be guessed from the server the
   * rest of the stack is already on. */
  guess?: { key: string; port: number; slug: string; path?: string; publicKey?: string };
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
        note: "Films link straight to their Radarr page. Cartographarr talks to the local URL; the buttons open the remote URL, so they work away from home.",
        test: "radarr",
        guess: { key: "radarr_url", port: 7878, slug: "radarr", publicKey: "radarr_public_url" },
        keys: ["radarr_url", "radarr_public_url", "radarr_api_key"],
      },
      {
        title: "Sonarr",
        note: "Shows and episodes link straight to their Sonarr page. Cartographarr talks to the local URL; the buttons open the remote URL.",
        test: "sonarr",
        guess: { key: "sonarr_url", port: 8989, slug: "sonarr", publicKey: "sonarr_public_url" },
        keys: ["sonarr_url", "sonarr_public_url", "sonarr_api_key"],
      },
      {
        title: "Seerr",
        note: "Shows who requested a title. Seerr is what Overseerr and Jellyseerr merged into. Cartographarr talks to the local URL; the buttons open the remote URL.",
        test: "seerr",
        guess: { key: "seerr_url", port: 5055, slug: "seerr", publicKey: "seerr_public_url" },
        keys: ["seerr_url", "seerr_public_url", "seerr_api_key"],
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
        title: "Messaging viewers",
        note: "Lets a rule message the person watching instead of stopping them. An Apprise URL with {email} (and optionally {username}) filled in from their Plex account, usually email, for example mailtos://you:app-password@gmail.com?to={email}. Leave empty to keep the action off.",
        keys: ["viewer_message_url"],
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
      {
        title: "Prometheus and dashboard tiles",
        note: "Set a token to switch on /metrics for Prometheus and /api/summary for Homepage or Homarr tiles. Send the token as a bearer token, or as ?token= on the URL. Both carry counts only (streams, plays, devices, signals, bans, last sync), never names, addresses or titles. Leave empty to keep them off.",
        keys: ["metrics_token"],
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
        title: "Library and access review",
        note: "The bitrate above which a remotely watched file counts as a problem in Library, and how long without a play before Access review says someone is not watching.",
        keys: ["library_bitrate_threshold_mbps", "access_inactive_days"],
      },
      {
        title: "Tidying files",
        note: "What tidying a file's tracks should aim for, and where this container can read the media. Languages are the three letter codes the tracks carry: eng, spa, jpn. Leave a list empty to keep every language. Nothing here happens on its own: it is what the button on a file card, and any rule you write, will do.",
        keys: ["preferred_audio_language", "keep_subtitle_languages", "keep_audio_languages"],
      },
      {
        title: "Server upload",
        note: "Your server's upload speed. Stalls that happen while the upload is nearly full are blamed on the upload rather than a viewer, and you get a notification (through Apprise, at most every half hour) when remote streams use more than the alert level. Leave at 0 to use the Internet upload speed set in Plex under Remote Access.",
        keys: ["upload_capacity_mbps", "upload_alert_percent"],
      },
      {
        title: "Reported problems",
        note: "Send word through Apprise when somebody reports something wrong, with what this app already knows about that file. Quiet unless notifications are set up.",
        keys: ["issue_alerts"],
      },
      {
        title: "Rules and live activity",
        note: "Whether rules run at all, and how often live activity is checked. Each rule, and the ban list, has its own record only switch on the Rules page.",
        keys: [
          "enforce_enabled",
          "enforce_cooldown_seconds",
          "activity_poll_seconds",
          "ban_message",
        ],
      },
    ],
  },
  {
    area: "Access",
    blurb: "Who can sign in, and how.",
    sections: [
      {
        title: "Viewer privacy",
        note: "What viewer accounts can see. Admins always see everything. Own data only hides everyone else entirely. Others anonymised keeps totals, charts and the map for the whole server, but other people appear as \"Another viewer\" with their addresses, devices and titles withheld. A viewer is matched to a Plex user by the link under Accounts, or by email or username; a viewer who matches nobody sees no personal data.",
        keys: ["viewer_privacy"],
      },
      {
        title: "Reporting problems",
        note: "Whether people who sign in as viewers can report something wrong with what they watched. They see what they reported and nothing else: not other people's reports, not who else watched the file, not where it sits on disk. Reporting from a play carries that play's details with it, so nobody has to ask what device they were on. Only an admin closes a report.",
        keys: ["viewer_reports_issues"],
      },
      {
        title: "Showing inside other dashboards",
        note: "Turn this on if you open Cartographarr inside Organizr, Homarr or another dashboard that shows apps in a frame; otherwise it shows blank there. Off, no other site can put Cartographarr in a frame, which stops a hidden page tricking a click on Ban or Unshare.",
        keys: ["allow_framing"],
      },
      {
        title: "Plex sign in",
        note: "Adds Sign in with Plex to the sign-in page. A Plex account signs in as the Cartographarr account linked to it under Accounts, or a viewer account with the same email. Usernames are never matched, and an admin account must be linked to its Plex account first. With new viewers allowed, anyone the server is shared with gets a viewer account the first time they sign in, seeing other people anonymised whatever the viewer privacy setting; change that per account under Accounts. Nobody becomes an admin through Plex, and Cartographarr does not keep their Plex token.",
        keys: ["plex_signin_enabled", "plex_signin_new_viewers"],
      },
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

/* One page per job, in a sidebar, the way Radarr and Sonarr lay settings out.
 * Connections first, since nothing works until those are set. */
type Page = {
  id: string;
  title: string;
  group: (typeof NAV_GROUPS)[number];
  blurb?: string;
  sections?: Section[];
  keys?: string[];
};

const NAV_GROUPS = ["Connections", "Cartographarr"] as const;

const slug = (text: string) => text.toLowerCase().replace(/[^a-z0-9]+/g, "-").replace(/(^-|-$)/g, "");

const PAGES: Page[] = [
  ...AREAS.map((a): Page => ({
    id: slug(a.area),
    title: a.area,
    group: ["Behaviour", "Access"].includes(a.area) ? "Cartographarr" : "Connections",
    blurb: a.blurb,
    sections: a.sections,
    keys: a.sections.flatMap((x) => x.keys),
  })),
  {
    id: "appearance",
    title: "Appearance",
    group: "Cartographarr",
    blurb: "The name, the colours and the marks shown around the app.",
    keys: ["app_name", "accent_color", "theme_colors"],
  },
  { id: "accounts", title: "Accounts", group: "Cartographarr", blurb: "Who can sign in to Cartographarr." },
  { id: "home", title: "Home page", group: "Cartographarr", blurb: "The links everyone lands on, and who sees each one." },
  { id: "tasks", title: "Tasks", group: "Cartographarr", blurb: "Background jobs: how often each runs, how the last run went, and any errors. Open one for its recent runs." },
  {
    id: "about",
    title: "About",
    group: "Cartographarr",
    blurb: "This version, whether a newer one is out, and what changed.",
    sections: [
      {
        title: "Update checks",
        note: "Twice a day Cartographarr asks GitHub for the newest version. Nothing about this server is sent. A private repository needs a token that can read it.",
        keys: ["update_check_enabled", "update_repository", "update_github_token"],
      },
    ],
    keys: ["update_check_enabled", "update_repository", "update_github_token"],
  },
];

/* URLs that carry a credential. The server sends them with the secret parts
 * masked, and puts the originals back on save for any URL left masked. */
const SECRET_URLS = new Set(["apprise_urls", "webhook_url", "uptime_kuma_push_url", "viewer_message_url"]);

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
  ban_message: "Message shown to a banned device",
  upload_capacity_mbps: "Upload capacity (Mbps)",
  library_bitrate_threshold_mbps: "Problem file bitrate (Mbps)",
  preferred_audio_language: "Audio language to put first",
  keep_subtitle_languages: "Subtitle languages to keep",
  keep_audio_languages: "Audio languages to keep",
  media_path_map: "Where this container sees the media",
  media_roots: "Mounted media directories",
  access_inactive_days: "Not watching after (days)",
  viewer_message_url: "Viewer message address",
  upload_alert_percent: "Warn when upload passes (%)",
  issue_alerts: "Tell me when something is reported",
  auth_proxy_enabled: "Trust a reverse proxy",
  allow_framing: "Allow showing inside other dashboards",
  plex_signin_enabled: "Offer Sign in with Plex",
  plex_signin_new_viewers: "Let people you share with sign in as viewers",
  trusted_proxy_ips: "Trusted proxy addresses",
  proxy_user_header: "Username header",
  proxy_email_header: "Email header",
  proxy_default_role: "Role for new proxy users",
  viewer_privacy: "Viewers can see",
  viewer_reports_issues: "Viewers can report problems",
  radarr_url: "Local URL",
  radarr_public_url: "Remote URL, for buttons",
  radarr_api_key: "API key",
  sonarr_url: "Local URL",
  sonarr_public_url: "Remote URL, for buttons",
  sonarr_api_key: "API key",
  app_name: "App name",
  tmdb_api_key: "TMDB API key",
  uptime_kuma_push_url: "Uptime Kuma push URL",
  seerr_url: "Local URL",
  seerr_public_url: "Remote URL, for buttons",
  seerr_api_key: "API key",
  apprise_urls: "Apprise URLs",
  webhook_url: "Webhook URL",
  metrics_token: "Metrics token",
  impossible_kmh: "Flag faster than (km/h)",
  impossible_min_km: "Ignore closer than (km)",
  impossible_max_accuracy_km: "Ignore vaguer than (km)",
  session_ttl_hours: "Stay signed in for (hours)",
  session_cookie_secure: "Only send the cookie over HTTPS",
  update_check_enabled: "Check for updates",
  update_repository: "GitHub repository",
  update_github_token: "GitHub token",
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
    <div className="scroll settings-scroll">
      <SettingsForm />
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

  const updateStatus = useApi<{ version: string; status: string | null }>("/about/status");
  const updateAvailable = updateStatus.data?.status === "update_available";
  const [page, setPage] = useState<string>(() => {
    try {
      return localStorage.getItem("settings.page") ?? PAGES[0].id;
    } catch {
      return PAGES[0].id;
    }
  });
  function open(id: string) {
    setPage(id);
    try {
      localStorage.setItem("settings.page", id);
    } catch {
      /* remembering the page is a convenience only */
    }
    document.querySelector(".settings-scroll")?.scrollTo({ top: 0 });
  }

  const byKey = new Map((settings.data ?? []).map((s) => [s.key, s]));
  const dirty = Object.keys(draft).length > 0;

  function valueOf(key: string): string {
    const v = key in draft ? draft[key] : byKey.get(key)?.value;
    return typeof v === "string" ? v : "";
  }

  // Two guesses from what is already set. Local URLs come from a direct
  // address (an IP or a port), which the container can reach. Remote URLs come
  // from a proxied domain, which a browser away from home can reach. A local
  // guess falls back to a domain when that is all there is; a remote guess
  // is only offered when there is a domain to base it on.
  const candidates = [
    "tautulli_local_url",
    "tautulli_url",
    "radarr_url",
    "sonarr_url",
    "seerr_url",
    "radarr_public_url",
    "sonarr_public_url",
    "seerr_public_url",
  ]
    .map((k) => parse(valueOf(k)))
    .filter((u): u is URL => u !== null && /^https?:$/.test(u.protocol));
  const localBase = candidates.find(isDirect) ?? candidates[0] ?? null;
  const remoteBase = candidates.find((u) => !isDirect(u)) ?? null;

  const guesses = new Map<string, string>();
  for (const area of AREAS) {
    for (const section of area.sections) {
      if (!section.guess) continue;
      if (localBase) guesses.set(section.guess.key, guessUrl(localBase, section.guess));
      if (section.guess.publicKey && remoteBase) {
        guesses.set(section.guess.publicKey, guessUrl(remoteBase, section.guess));
      }
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
    const isSecret = /key|token|secret|password/.test(key) && !SECRET_URLS.has(key);
    // A masked secret must not be saved back as literal asterisks.
    const masked = isSecret && setting.value === "********";

    return (
      <label key={key} className={locked ? "locked" : undefined}>
        {LABELS[key] ?? key}
        {locked && <span className="pill">set by environment</span>}

        {key === "plex_machine_identifier" ? (
          <PlexServerSelect
            value={String(value ?? "")}
            locked={locked}
            token={"plex_token" in draft ? String(draft.plex_token ?? "") : null}
            hasSavedToken={Boolean(byKey.get("plex_token")?.value)}
            onChange={(v) => setDraft({ ...draft, [key]: v })}
          />
        ) : isBool ? (
          <select
            disabled={locked}
            value={String(value)}
            onChange={(e) => setDraft({ ...draft, [key]: e.target.value === "true" })}
          >
            <option value="true">On</option>
            <option value="false">Off</option>
          </select>
        ) : key === "viewer_privacy" ? (
          <select
            disabled={locked}
            value={String(value ?? "all")}
            onChange={(e) => setDraft({ ...draft, [key]: e.target.value })}
          >
            <option value="all">Everything on the server</option>
            <option value="own">Only their own data</option>
            <option value="anonymised">Everything, with other people anonymised</option>
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
        {SECRET_URLS.has(key) && !locked && Boolean(setting.value) && (
          <small>Parts shown as **** stay as saved. To change one, replace that whole URL.</small>
        )}
        {key === "trusted_proxy_ips" && !locked && (
          <small>Comma separated. Addresses or CIDRs, for example 172.17.0.0/16.</small>
        )}
      </label>
    );
  }

  if (settings.error) return <p className="note bad-note pad">{settings.error}</p>;

  const current = PAGES.find((x) => x.id === page) ?? PAGES[0];
  const unsaved = (p: Page) => (p.keys ?? []).some((k) => k in draft);

  return (
    <div className="settings-layout">
      <nav className="settings-nav" aria-label="Settings sections">
        <h1>Settings</h1>
        {NAV_GROUPS.map((group) => (
          <div key={group} className="settings-nav-group">
            <span className="settings-nav-label">{group}</span>
            {PAGES.filter((x) => x.group === group).map((x) => (
              <button
                key={x.id}
                className={x.id === current.id ? "settings-nav-item on" : "settings-nav-item"}
                onClick={() => open(x.id)}
                aria-current={x.id === current.id ? "page" : undefined}
              >
                <span>{x.title}</span>
                {unsaved(x) && <span className="unsaved-dot" title="Unsaved changes" />}
                {x.id === "about" && updateAvailable && <span className="update-dot" title="Update available" />}
              </button>
            ))}
          </div>
        ))}
      </nav>

      <div className="settings-page">
        <header className="settings-page-head">
          <h2>{current.title}</h2>
          {current.blurb && <p className="muted">{current.blurb}</p>}
        </header>

        {error && <p className="note bad-note">{error}</p>}

        {current.id === "about" && <About />}

        {current.sections?.map((section) => (
          <section key={section.title} className="card-section">
            <div className="row-between">
              <h3 className="section-title">
                <BrandIcon name={section.title.toLowerCase()} size={16} />
                {section.title}
              </h3>
              {section.test && (
                <TestButton
                  name={section.test}
                  values={Object.fromEntries(section.keys.filter((k) => k in draft).map((k) => [k, draft[k]]))}
                />
              )}
            </div>
            {section.note && <p className="muted small">{section.note}</p>}
            <div className="grid2">{section.keys.map(field)}</div>
            {section.title === "Syncing" && <SyncNow />}
            {section.title === "Tidying files" && (
              <MediaPaths
                roots={String(draft.media_roots ?? byKey.get("media_roots")?.value ?? "")}
                map={String(draft.media_path_map ?? byKey.get("media_path_map")?.value ?? "")}
                onRoots={(value) => setDraft({ ...draft, media_roots: value })}
                onMap={(value) => setDraft({ ...draft, media_path_map: value })}
              />
            )}
            {section.title === "Library and access review" && (
              <BitrateAdvice
                onUse={(mbps) => setDraft({ ...draft, library_bitrate_threshold_mbps: mbps })}
              />
            )}
            {section.title === "Server upload" && <UploadSource />}
          </section>
        ))}

        {current.id === "appearance" && (
          <>
            <section className="card-section">
              <h3>Name</h3>
              <div className="grid2">{field("app_name")}</div>
            </section>
            <AccentPicker
              value={String(draft.accent_color ?? settings.data?.find((x) => x.key === "accent_color")?.value ?? "")}
              onChange={(colour) => setDraft({ ...draft, accent_color: colour })}
            />
            <ThemeEditor
              value={String(draft.theme_colors ?? settings.data?.find((x) => x.key === "theme_colors")?.value ?? "")}
              onChange={(colours) => setDraft({ ...draft, theme_colors: colours })}
            />
            <BrandingImages />
          </>
        )}

        {current.id === "home" && <HomeLinks />}

        {current.id === "tasks" && <Tasks />}

        {current.id === "accounts" && (
          <>
            <Accounts />
            <ChangePassword />
          </>
        )}

        {/* Changes are kept while moving between pages, so this bar follows
            you rather than living at the top of one page. */}
        {(dirty || saved) && (
          <div className={dirty ? "save-bar" : "save-bar done"} role="status">
            <span>
              {dirty
                ? `${Object.keys(draft).length} unsaved change${Object.keys(draft).length === 1 ? "" : "s"}` +
                  (PAGES.filter((x) => x.id !== current.id && unsaved(x)).length
                    ? `, some on ${PAGES.filter((x) => x.id !== current.id && unsaved(x)).map((x) => x.title).join(", ")}`
                    : "")
                : "Saved."}
            </span>
            {dirty && (
              <div className="row">
                <button className="btn" onClick={() => setDraft({})} disabled={saving}>
                  Discard
                </button>
                <button className="btn primary" onClick={save} disabled={saving}>
                  {saving ? "Saving\u2026" : "Save"}
                </button>
              </div>
            )}
          </div>
        )}
      </div>
    </div>
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
/* The Plex server, picked from the ones the token can see rather than
 * pasted. Uses the token typed on the page if there is one, so the server can
 * be chosen before saving. With nothing picked, the id Tautulli reports is
 * used, which is right for anyone with a single server. */
function PlexServerSelect({
  value,
  locked,
  token,
  hasSavedToken,
  onChange,
}: {
  value: string;
  locked: boolean;
  token: string | null;
  hasSavedToken: boolean;
  onChange: (value: string) => void;
}) {
  type Server = { id: string; name: string; owned: boolean; version: string | null; online: string | null };
  const [servers, setServers] = useState<Server[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const usable = token !== null ? token.trim().length > 0 : hasSavedToken;

  useEffect(() => {
    if (!usable) {
      setServers(null);
      setError(null);
      return;
    }
    // Waits for typing to stop before asking Plex.
    const timer = setTimeout(async () => {
      setBusy(true);
      try {
        const r = await api.post<{ servers: Server[]; error: string | null }>("/sharing/servers", {
          values: token !== null ? { plex_token: token } : {},
        });
        setServers(r.servers);
        setError(r.error);
      } catch (err) {
        setError((err as Error).message);
      } finally {
        setBusy(false);
      }
    }, 600);
    return () => clearTimeout(timer);
  }, [token, usable]);

  const known = servers?.some((x) => x.id === value);

  return (
    <>
      <select disabled={locked || !usable || busy} value={value} onChange={(e) => onChange(e.target.value)}>
        <option value="">{usable ? "The server Tautulli reports (automatic)" : "Add a Plex token to choose"}</option>
        {servers?.map((x) => (
          <option key={x.id} value={x.id}>
            {x.name}
            {x.owned ? "" : " (shared with you)"}
            {x.version ? ` · ${x.version}` : ""}
          </option>
        ))}
        {value && !known && <option value={value}>{value}</option>}
      </select>
      <small>
        {busy
          ? "Asking Plex…"
          : error
            ? error
            : servers
              ? `${servers.length} server${servers.length === 1 ? "" : "s"} on this Plex account.`
              : "Pick which server sharing changes apply to."}
      </small>
    </>
  );
}

/* Which upload figure is in use: this page's, or the one set in Plex. */
function UploadSource() {
  const info = useApi<{
    capacity_mbps: number | null;
    source: "settings" | "plex" | "unknown";
    plex_upload_mbps: number | null;
    plex_stream_limit_mbps: number | null;
  }>("/library/upload");
  const d = info.data;
  if (!d) return null;
  const plex =
    d.plex_upload_mbps === null
      ? "Plex's upload speed has not been read yet (it is read every hour)."
      : d.plex_upload_mbps === 0
        ? "Plex has no Internet upload speed set (Settings, Remote Access)."
        : `Plex's Internet upload speed is ${d.plex_upload_mbps.toLocaleString()} Mbps.`;
  const limit =
    d.plex_stream_limit_mbps ? ` Remote streams are limited to ${d.plex_stream_limit_mbps} Mbps each.` : "";
  const using =
    d.source === "settings"
      ? `Using ${d.capacity_mbps} Mbps from this page.`
      : d.source === "plex"
        ? `Using Plex's figure, since upload capacity here is 0.`
        : "No upload figure yet, so stalls are not blamed on the upload.";
  return (
    <p className="note">
      {plex}
      {limit} {using}
    </p>
  );
}

/* What this server's remote viewers actually manage.
 *
 * The problem bitrate out of the box is a round number that knows nothing
 * about this house. Every remote stream is recorded with the file's bitrate
 * and whether it stalled, so the answer is already here: it is offered rather
 * than applied, because a stall can be a bad evening on somebody else's line
 * as easily as a file that is too big.
 */
type Advice = {
  days: number;
  clean_streams: number;
  stalled_streams: number;
  clean_typical: number | null;
  clean_high: number | null;
  stalled_typical: number | null;
  stalled_high: number | null;
  suggestion: number | null;
  why: string | null;
};

function BitrateAdvice({ onUse }: { onUse: (mbps: number) => void }) {
  const advice = useApi<Advice>("/library/bitrate-advice");
  if (advice.error || !advice.data) return null;
  const a = advice.data;
  if (!a.why) return null;
  return (
    <div className="row sync-now">
      {a.suggestion != null && (
        <button type="button" className="btn" onClick={() => onUse(a.suggestion as number)}>
          Use {a.suggestion} Mbps
        </button>
      )}
      <span className="muted small">
        {a.why}
        {a.clean_streams > 0
          ? ` Read from ${a.clean_streams + a.stalled_streams} remote streams over ${a.days} days.`
          : ""}
      </span>
    </div>
  );
}

/* Whether tidying can work here, answered by trying rather than by telling
 * somebody what to read. Two things have to be true: ffmpeg in the image, and
 * the media readable at the paths Plex reports.
 */
type TidyStatusRow = {
  checked: number;
  visible: number;
  libraries: {
    library: string;
    here: string | null;
    found: boolean;
    files: number;
    mapped: boolean;
    example: string;
  }[];
  missing_roots: string[];
  example: string | null;
  tools: { ready: boolean; ffmpeg: { version: string | null } };
  path_map: [string, string][];
  roots: string[];
};

/* Where the media is, asked as two questions rather than as one text box.
 *
 * First: which directories are mounted in this container. Usually one, often
 * two when libraries are split across shares, so it is a list you add rows to.
 * The app then looks for each Plex library underneath them and says what it
 * found, and only a library it could not find needs a path typed in by hand.
 * That is the path map, built from the table rather than written as pairs.
 */
function MediaPaths({
  roots,
  map,
  onRoots,
  onMap,
}: {
  roots: string;
  map: string;
  onRoots: (value: string) => void;
  onMap: (value: string) => void;
}) {
  const status = useApi<TidyStatusRow>("/library/tidy/status");
  // Held here as well as in the draft so that emptying a row leaves the box on
  // screen instead of taking it out from under the cursor.
  const [rows, setRows] = useState<string[]>(() => {
    const given = roots.split(",").map((x) => x.trim()).filter(Boolean);
    return given.length > 0 ? given : [""];
  });

  function push(next: string[]) {
    setRows(next.length > 0 ? next : [""]);
    onRoots(next.map((x) => x.trim()).filter(Boolean).join(", "));
  }

  const pairs = new Map<string, string>(
    map
      .split(",")
      .map((part) => part.split("="))
      .filter((bits) => bits.length === 2 && bits[0].trim() && bits[1].trim())
      .map((bits) => [bits[0].trim(), bits[1].trim()] as [string, string]),
  );

  function setPair(library: string, here: string) {
    const next = new Map(pairs);
    if (here.trim()) next.set(library, here.trim());
    else next.delete(library);
    onMap([...next].map(([a, b]) => a + "=" + b).join(", "));
  }

  const s = status.data;
  const libraries = s?.libraries ?? [];
  const lost = libraries.filter((x) => !x.found);
  const ready = Boolean(s?.tools.ready) && libraries.length > 0 && lost.length === 0;

  return (
    <div className="media-paths">
      <div className="row-between">
        <h4 className="section-title">Where the media is mounted</h4>
        <span className={ready ? "pill ok" : "pill warn"}>{ready ? "ready" : "not ready"}</span>
      </div>
      <p className="muted small">
        {s && !s.tools.ready
          ? "ffmpeg is not in this image, so nothing can be tidied whatever is mounted here."
          : "The directories this container can read, usually the one share that holds every library. Each library is looked for underneath them."}
      </p>

      <div className="path-rows">
        {rows.map((row, index) => (
          <div key={index} className="row">
            <input
              value={row}
              spellCheck={false}
              placeholder={index === 0 ? "/media" : "/media2"}
              onChange={(e) => push(rows.map((old, n) => (n === index ? e.target.value : old)))}
            />
            <button
              className="btn"
              disabled={rows.length === 1 && !rows[0]}
              onClick={() => push(rows.filter((_, n) => n !== index))}
            >
              Remove
            </button>
          </div>
        ))}
        <div className="row wrap">
          <button className="btn" onClick={() => setRows([...rows, ""])}>
            Add another directory
          </button>
          <button className="btn" onClick={status.reload} disabled={status.loading}>
            {status.loading ? "Looking" : "Check again"}
          </button>
          <span className="muted small">Save, then check again.</span>
        </div>
      </div>

      {libraries.length === 0 ? (
        <p className="muted small">
          No file paths known yet. The library scan fills these in, and this table then says where each one was
          found.
        </p>
      ) : (
        <table className="table media-libraries">
          <thead>
            <tr>
              <th>Library, as Plex reports it</th>
              <th>Found at</th>
              <th>Or set it by hand</th>
            </tr>
          </thead>
          <tbody>
            {libraries.map((row) => (
              <tr key={row.library}>
                <td>
                  <span className={row.found ? "pill ok" : "pill warn"}>{row.found ? "found" : "missing"}</span>{" "}
                  {row.library}
                </td>
                <td className="muted small">
                  {row.found ? row.here : "Not readable here. For example " + row.example}
                </td>
                <td>
                  <input
                    value={pairs.get(row.library) ?? ""}
                    spellCheck={false}
                    placeholder={row.found ? (row.here ?? "") : "/media/something"}
                    onChange={(e) => setPair(row.library, e.target.value)}
                  />
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      )}

      {s && s.checked > 0 && (
        <p className="muted small">
          {s.visible} of the {s.checked} most recent files can be opened from inside this container.
        </p>
      )}
    </div>
  );
}

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
  // Plex users to link accounts to, for viewer privacy.
  const plexUsers = useApi<{ user_id: number; username: string | null; friendly_name: string | null; email: string | null }[]>("/users");
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
              <td>
                <select
                  title="Which Plex user this is, for viewer privacy. Automatic matches by email or username."
                  value={u.plex_user_id ?? ""}
                  onChange={(e) => change(u, { plex_user_id: e.target.value ? Number(e.target.value) : null })}
                >
                  <option value="">Plex user: automatic</option>
                  {(plexUsers.data ?? []).map((p) => (
                    <option key={p.user_id} value={p.user_id}>
                      {p.friendly_name || p.username || p.user_id}
                    </option>
                  ))}
                </select>
              </td>
              <td>
                {u.role === "viewer" ? (
                  <select
                    title="What this viewer can see. Server setting follows Viewer privacy above."
                    value={u.privacy ?? ""}
                    onChange={(e) => change(u, { privacy: e.target.value || null })}
                  >
                    <option value="">Sees: server setting</option>
                    <option value="all">Sees: everything</option>
                    <option value="anonymised">Sees: others anonymised</option>
                    <option value="own">Sees: only their own</option>
                  </select>
                ) : (
                  <span className="muted small">sees everything</span>
                )}
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


/* One colour, and the app is built around it.
 *
 * Everything else that a theme usually asks for (the hover colour, the ink on
 * top of a button, the wash behind a selection) is worked out from this, light
 * and dark alike, and the map takes it too. Choosing four colours is four
 * chances to make something unreadable. */
/* The page, the panels, the top bar and the text, for whichever theme is on.
 *
 * Four colours, not fourteen: everything else is worked out from them in
 * theme/accent.ts. Each theme keeps its own set, because a colour that works
 * on a dark page is unreadable on a light one, and the light theme is left
 * alone unless somebody is looking at it.
 */
const PARTS: { key: keyof Parts; label: string; hint: string }[] = [
  { key: "bg", label: "Page", hint: "Behind everything" },
  { key: "surface", label: "Panels and menus", hint: "Cards, tables, dropdowns" },
  { key: "bar", label: "Top bar", hint: "The strip with the tabs" },
  { key: "ink", label: "Text", hint: "Quieter text is worked out from it" },
];

function ThemeEditor({ value, onChange }: { value: string; onChange: (colours: string) => void }) {
  const mode = (document.documentElement.dataset.theme ?? "light") as "dark" | "light";
  const scheme: Scheme = (() => {
    try {
      return value ? (JSON.parse(value) as Scheme) : {};
    } catch {
      return {};
    }
  })();
  const mine = scheme[mode] ?? {};
  const shown = getComputedStyle(document.documentElement);
  const showing = (key: keyof Parts) => mine[key] ?? shown.getPropertyValue(`--${key}`).trim() ?? "#000000";

  // The one thing a colour picker can do that cannot be undone by looking:
  // text nobody can read, on a page nobody can then find the picker on.
  const worst = [contrast(showing("ink"), showing("bg")), contrast(showing("ink"), showing("surface"))]
    .filter((n): n is number => n != null);
  const faint = worst.length && Math.min(...worst) < 4.5 ? Math.min(...worst) : null;

  function put(next: Parts) {
    const kept = Object.fromEntries(Object.entries(next).filter(([, v]) => v)) as Parts;
    const whole: Scheme = { ...scheme, [mode]: kept };
    if (!Object.keys(kept).length) delete whole[mode];
    const text = Object.keys(whole).length ? JSON.stringify(whole) : "";
    onChange(text);
    // Shown at once, like the accent. Saving is still the Save button.
    setScheme(text);
  }

  return (
    <section className="card-section">
      <h3>The {mode} theme</h3>
      <p className="muted small">
        Four colours, and the rest follows: raised panels, borders and quieter text are worked out a step at a time
        from the panel and the text. Switch the theme in the top bar to set the other one.
      </p>
      <div className="row wrap accent-row">
        {SCHEMES.map((preset) => (
          <button
            key={preset.name}
            className="tab"
            title={preset.blurb}
            onClick={() => put(mode === "dark" ? preset.dark : {})}
            disabled={mode !== "dark"}
          >
            {preset.name}
          </button>
        ))}
        {Object.keys(mine).length > 0 && (
          <button className="tab" onClick={() => put({})}>
            Back to the usual
          </button>
        )}
      </div>
      {mode !== "dark" && (
        <p className="muted small">
          The presets are dark schemes. On the light theme, pick the four colours yourself.
        </p>
      )}
      {faint && (
        <p className="note bad-note">
          This text is hard to read on these colours ({faint.toFixed(1)} to 1, and text wants 4.5). Move the text and
          the page further apart.
        </p>
      )}
      <div className="grid2 theme-parts">
        {PARTS.map((part) => (
          <label key={part.key}>
            {part.label}
            <span className="row">
              <input
                type="color"
                className="accent-input"
                value={showing(part.key) || "#000000"}
                onChange={(e) => put({ ...mine, [part.key]: e.target.value })}
              />
              <small className="muted">{part.hint}</small>
            </span>
          </label>
        ))}
      </div>
    </section>
  );
}

function AccentPicker({ value, onChange }: { value: string; onChange: (colour: string) => void }) {
  const current = value || "";

  function choose(colour: string) {
    onChange(colour);
    // Shown at once, so the choice is made by looking rather than guessing.
    // Saving is still the Save button, like every other setting.
    applyAccent(colour || null);
  }

  return (
    <section className="card-section">
      <h3>Colour</h3>
      <p className="muted small">
        Buttons, links, map pins and charts follow this. Light and dark are worked out from it, so it only has to look
        right once.
      </p>
      <div className="row wrap accent-row">
        {ACCENTS.map((a) => (
          <button
            key={a.value}
            className={current.toLowerCase() === a.value.toLowerCase() ? "accent-chip on" : "accent-chip"}
            style={{ background: a.value }}
            title={a.name}
            aria-label={a.name}
            onClick={() => choose(a.value)}
          />
        ))}
        <input
          type="color"
          className="accent-input"
          value={current || "#22d3ee"}
          onChange={(e) => choose(e.target.value)}
          title="Any colour"
        />
        {current && (
          <button className="tab" onClick={() => choose("")}>
            Back to the usual
          </button>
        )}
      </div>
    </section>
  );
}
