import { askConfirm } from "../components/Ask";
import About from "../components/About";
import HomeLinks from "../components/HomeLinks";
import { ACCENTS, SCHEMES, applyAccent, contrast, setScheme, type Parts, type Scheme } from "../theme/accent";
import Tasks from "../components/Tasks";
import { type ReactNode, useEffect, useState } from "react";
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
type Area = { area: string; group: (typeof NAV_GROUPS)[number]; blurb?: string; sections: Section[] };

/* Grouped into areas rather than one long list, because the page covers
 * unrelated jobs: connecting to things, how it behaves, who gets in, and how
 * it looks. */
const AREAS: Area[] = [
  {
    area: "Plex and Tautulli",
    group: "Connections",
    blurb: "Plex for everything happening now. Tautulli for plays from before this app was watching.",
    sections: [
      {
        title: "Plex",
        note: "A token lets this app talk to Plex directly, for live streams, the library, stopping streams and sharing. Find servers looks up the address and keeps it, which saves about twenty seconds on every connection.",
        test: "plex",
        keys: ["plex_token", "plex_url", "plex_machine_identifier"],
      },
      {
        title: "Where the live data comes from",
        note: "Plex answers faster and with more detail, and gives the address, device and account. Tautulli only has what it already recorded, so old history comes from it either way.",
        keys: ["activity_source", "library_source"],
      },
      {
        title: "Tautulli: bring in your history",
        note: "Optional once Plex is connected. Plex keeps no record of where a play came from or how it went, so plays from before this app was watching exist only in Tautulli. History, the map, Endpoints and the list of users are still read from it for now, so they stay empty without it.",
        test: "tautulli",
        keys: [
          "tautulli_url",
          "tautulli_local_url",
          "tautulli_api_key",
          "tautulli_verify_ssl",
          "tautulli_timeout",
        ],
      },
    ],
  },
  {
    area: "Map locations",
    group: "Connections",
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
    group: "Connections",
    blurb: "Optional. Links a title out to the app that manages it, and shows who asked for it.",
    sections: [
      {
        title: "Radarr",
        note: "Films link straight to their Radarr page. The app uses the local URL; buttons open the remote one, so they work away from home.",
        test: "radarr",
        guess: { key: "radarr_url", port: 7878, slug: "radarr", publicKey: "radarr_public_url" },
        keys: ["radarr_url", "radarr_public_url", "radarr_api_key"],
      },
      {
        title: "Sonarr",
        note: "Shows and episodes link straight to their Sonarr page. The app uses the local URL; buttons open the remote one.",
        test: "sonarr",
        guess: { key: "sonarr_url", port: 8989, slug: "sonarr", publicKey: "sonarr_public_url" },
        keys: ["sonarr_url", "sonarr_public_url", "sonarr_api_key"],
      },
      {
        title: "Seerr",
        note: "Shows who requested a title. Seerr is what Overseerr and Jellyseerr became. The app uses the local URL; buttons open the remote one.",
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
    group: "Connections",
    blurb: "Optional. Where rules can send a warning, and what watches the sync.",
    sections: [
      {
        title: "Notifications",
        note: "One Apprise URL per line, or comma separated. Discord, ntfy, Gotify, Pushover, Telegram, email and most others. Test checks them without sending anything.",
        test: "apprise",
        keys: ["apprise_urls"],
      },
      {
        title: "Weekly digest",
        note: "One message a week: hours watched, new devices, new signals, reported problems, where the library stands, and any job that has stopped. Goes to the Apprise targets above, so it needs those set up.",
        keys: ["weekly_digest", "digest_weekday", "digest_hour"],
      },
      {
        title: "Messaging viewers",
        note: "Lets a rule message the person watching instead of stopping them. An Apprise URL with {email}, and optionally {username}, filled in from their Plex account. For example mailtos://user:app-password@smtp.example.com?to={email}. Empty keeps the action off.",
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
        note: "A heartbeat pinged after each sync, so it watches the sync and not just the container. Test sends one real ping.",
        test: "uptime_kuma",
        guess: { key: "uptime_kuma_push_url", port: 3001, slug: "uptime", path: "/api/push/" },
        keys: ["uptime_kuma_push_url"],
      },
      {
        title: "Prometheus and dashboard tiles",
        note: "A token switches on /metrics for Prometheus and /api/summary for dashboard tiles. Send it as a bearer token, or as ?token= on the URL. Counts only, never names, addresses or titles. Empty keeps them off.",
        keys: ["metrics_token"],
      },
    ],
  },
  {
    area: "Syncing",
    group: "Cartographarr",
    blurb: "How often Cartographarr reads from Tautulli, and how hard it reads when it does.",
    sections: [
      {
        title: "Schedule",
        note: "History is read often because everything is built from it. Users and libraries change rarely, so they get a slower round.",
        keys: ["sync_interval_minutes", "slow_sync_interval_minutes"],
      },
      {
        title: "How hard it reads",
        note: "Raise these on a strong box to finish the first sync sooner. Lower them if Tautulli or Plex start timing out.",
        keys: ["sync_page_size", "metadata_concurrency"],
      },
      {
        title: "Backups",
        note: "One file holds everything this app has worked out: stall causes, signals, bans, rules, reports, keep decisions and every setting. Tautulli can rebuild the raw history and nothing else. Snapshots are taken without stopping anything and land in the appdata volume. Keep 0 to switch it off.",
        keys: ["backup_keep", "backup_hour"],
      },
      {
        title: "When a job stops working",
        note: "A broken background job does not announce itself, it just stops having the right answer. Three failures in a row sends one message, then nothing until it works again. Needs notifications set up.",
        keys: ["task_alerts"],
      },
    ],
  },
  {
    area: "Live and rules",
    group: "Cartographarr",
    blurb: "Watching streams as they happen, what rules may do about them, and how much upload there is to go round.",
    sections: [
      {
        title: "Live activity",
        note: "How often the list of who is watching is refreshed. Each check is one request.",
        keys: ["activity_poll_seconds"],
      },
      {
        title: "Rules",
        note: "Whether rules run at all, and how long a rule waits before acting on the same stream again. Each rule, and the ban list, has its own record only switch on the Rules page.",
        keys: ["enforce_enabled", "enforce_cooldown_seconds", "automation_daily_cap", "automation_download_cap"],
      },
      {
        title: "What a stopped viewer sees",
        note: "Plex wraps your words in its own sentence: \"<account> asked to stop your playback from this server: <your message>\". A banned device, a banned address and a blocked country each get their own. Leave the address one empty to use the device wording for both.",
        keys: ["ban_message", "address_ban_message", "geo_block_message"],
      },
      {
        title: "Server upload",
        note: "Your server's upload speed. A stall while the upload is nearly full is blamed on the upload, not on a viewer. You get a notification, at most every half hour, when remote streams pass the alert level. 0 uses the speed set in Plex under Remote Access.",
        keys: ["upload_capacity_mbps", "upload_alert_percent"],
      },
    ],
  },
  {
    area: "Library and files",
    group: "Cartographarr",
    blurb: "What counts as a problem file, what tidying one should aim for, and where this container can read the media.",
    sections: [
      {
        title: "Problem files",
        note: "The average bitrate above which a remotely watched file is listed as a problem in Library. Set it near what one remote stream can comfortably use.",
        keys: ["library_bitrate_threshold_mbps"],
      },
      {
        title: "Tidying files",
        note: "What tidying a file's tracks should aim for. Languages are the three letter codes the tracks carry: eng, spa, jpn. An empty list keeps every language. Nothing happens on its own: this is what the button on a file card, and any rule you write, will do. Tidying rewrites the whole file, so a queued job waits for the streams to stop by default.",
        keys: ["preferred_audio_language", "keep_subtitle_languages", "keep_audio_languages", "tidy_when_quiet"],
      },
      {
        title: "Storage",
        note: "How much of a file's path names the disk it is on. One part (/movies, /tv) is usually right. Raise it where libraries share a mount (/mnt/user/movies, /mnt/user/tv), or Library, Storage counts them as one.",
        keys: ["library_store_depth"],
      },
    ],
  },
  {
    area: "People and privacy",
    group: "Cartographarr",
    blurb: "What viewers can see, when somebody counts as no longer watching, and when one account in two places is worth flagging.",
    sections: [
      {
        title: "Viewer privacy",
        note: "What viewer accounts can see. Admins always see everything. Own data only hides everyone else. Others anonymised keeps the totals, charts and map, but other people show as \"Another viewer\" without their addresses, devices or titles. A viewer is matched to a Plex user by the link under Accounts, or by email or username.",
        keys: ["viewer_privacy"],
      },
      {
        title: "Reported problems",
        note: "Whether viewers can report something wrong with what they watched, and whether you hear about it. They see their own reports and nothing else. A report carries the play's details with it, so nobody has to ask what device they were on. Only an admin closes one.",
        keys: ["viewer_reports_issues", "issue_alerts"],
      },
      {
        title: "Shared account detection",
        note: "How eagerly to flag one account being used in two places. Locations are only accurate to a city, so a pair is ignored when either fix is vaguer than the accuracy limit, or they are closer than the minimum distance. A sync can send word when it finds a new device or signal.",
        keys: ["impossible_kmh", "impossible_min_km", "impossible_max_accuracy_km", "watch_alerts"],
      },
      {
        title: "Access review",
        note: "How long without a play before Access review says somebody is not watching any more.",
        keys: ["access_inactive_days"],
      },
    ],
  },
  {
    area: "Sign-in",
    group: "Cartographarr",
    blurb: "How people get in, how long they stay, and where the app may be shown.",
    sections: [
      {
        title: "Plex sign in",
        note: "Adds Sign in with Plex. A Plex account signs in as the account linked to it under Accounts, or a viewer with the same email. Usernames are never matched, and an admin must be linked first. With new viewers allowed, anyone the server is shared with gets a viewer account on first sign-in. Nobody becomes an admin this way, and no Plex token is kept.",
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
      {
        title: "Sessions",
        note: "How long a sign-in lasts, and whether the cookie may travel over plain HTTP. Turn the HTTPS lock on once the app is behind TLS.",
        keys: ["session_ttl_hours", "session_cookie_secure"],
      },
      {
        title: "Showing inside other dashboards",
        note: "Turn this on to open Cartographarr inside Organizr, Homarr or another dashboard, or it shows blank there. Off, no other site can frame it, which stops a hidden page tricking a click on Ban or Unshare.",
        keys: ["allow_framing"],
      },
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

/* Everything about a setting that somebody might type looking for it: the
 * name on screen, the key it is stored under, the words around it, and the
 * page and section it lives on. "upload" should find the upload capacity
 * whether you know it as that, as upload_capacity_mbps, or only that it was
 * somewhere near the alert level.
 */
function wordsOf(section: Section): string {
  const parts: (string | undefined)[] = [section.title, section.note];
  for (const key of section.keys) parts.push(key, LABELS[key]);
  return parts.filter(Boolean).join(" ").toLowerCase();
}

/* A page is a match when its name says so, or when one of its sections is a
 * match on its own.
 *
 * Asking whether the page as a whole contains every word is not the same
 * question and gives a worse answer: "ban message" would find a page with
 * "ban" in one section and "message" in another, land you on it, and show you
 * neither. Pages without sections are matched on their name and their keys,
 * since their contents are built by hand.
 */
function pageHits(page: Page, query: string): boolean {
  const name = [page.title, page.blurb].filter(Boolean).join(" ").toLowerCase();
  if (hits(name, query)) return true;
  if (page.sections?.some((s) => hits(wordsOf(s), query))) return true;
  const keys = (page.keys ?? []).flatMap((k) => [k, LABELS[k] ?? ""]).join(" ").toLowerCase();
  return !page.sections && hits(keys, query);
}

/* Every word typed has to appear somewhere, in any order, so "upload warn"
 * finds the alert level without needing the phrase exactly. */
function hits(words: string, query: string): boolean {
  const terms = query.toLowerCase().split(/\s+/).filter(Boolean);
  return terms.every((term) => words.includes(term));
}

const slug = (text: string) => text.toLowerCase().replace(/[^a-z0-9]+/g, "-").replace(/(^-|-$)/g, "");

const PAGES: Page[] = [
  ...AREAS.map((a): Page => ({
    id: slug(a.area),
    title: a.area,
    group: a.group,
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
  library_store_depth: "Path parts that name the disk",
  automation_download_cap: "All rules together may queue",
  automation_daily_cap: "A rule may act at most",
  tautulli_url: "Tautulli URL",
  plex_url: "Plex address",
  activity_source: "Live streams from",
  library_source: "The library from",
  tautulli_local_url: "Local URL",
  tautulli_api_key: "API key",
  tautulli_verify_ssl: "Verify SSL certificate",
  tautulli_timeout: "Request timeout",
  plex_token: "Plex token",
  plex_machine_identifier: "Plex server id",
  maxmind_account_id: "MaxMind account ID",
  maxmind_license_key: "MaxMind license key",
  geoip_auto_update: "Keep databases updated",
  geoip_update_interval_days: "Update every",
  sync_interval_minutes: "Sync history every",
  slow_sync_interval_minutes: "Sync users and libraries every",
  sync_page_size: "Rows per request",
  metadata_concurrency: "Metadata lookups at once",
  enforce_enabled: "Run rules",
  enforce_dry_run: "Dry run",
  enforce_cooldown_seconds: "Cooldown per rule",
  activity_poll_seconds: "Check activity every",
  ban_message: "A banned device",
  address_ban_message: "A banned address",
  geo_block_message: "A blocked country",
  upload_capacity_mbps: "Upload capacity",
  library_bitrate_threshold_mbps: "Problem file bitrate",
  preferred_audio_language: "Audio language to put first",
  keep_subtitle_languages: "Subtitle languages to keep",
  keep_audio_languages: "Audio languages to keep",
  media_path_map: "Where this container sees the media",
  media_roots: "Mounted media directories",
  tidy_when_quiet: "Wait until nobody is watching",
  access_inactive_days: "Not watching after",
  viewer_message_url: "Viewer message address",
  upload_alert_percent: "Warn when upload passes",
  issue_alerts: "Tell me when something is reported",
  task_alerts: "Tell me when a job keeps failing",
  weekly_digest: "Send a weekly digest",
  digest_weekday: "On",
  digest_hour: "At",
  watch_alerts: "Tell me about new devices and signals",
  backup_keep: "Snapshots to keep",
  backup_hour: "Taken at",
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
  impossible_kmh: "Flag faster than",
  impossible_min_km: "Ignore closer than",
  impossible_max_accuracy_km: "Ignore vaguer than",
  session_ttl_hours: "Stay signed in for",
  session_cookie_secure: "Only send the cookie over HTTPS",
  update_check_enabled: "Check for updates",
  update_repository: "GitHub repository",
  update_github_token: "GitHub token",
};

/* What a box should be, where the value alone does not say.
 *
 * A number wants its unit beside it rather than in brackets after its name,
 * and wants bounds so a stray keystroke cannot set the sync interval to eight
 * thousand. A comma separated list wants to be a list. Everything not named
 * here is a plain box, which is right for a URL or a key.
 */
type FieldShape = { unit?: string; min?: number; max?: number; step?: number; kind?: "chips" | "lines" };

const SHAPES: Record<string, FieldShape> = {
  tautulli_timeout: { unit: "seconds", min: 1, max: 300, step: 1 },
  geoip_update_interval_days: { unit: "days", min: 1, max: 90, step: 1 },
  sync_interval_minutes: { unit: "minutes", min: 1, max: 1440, step: 1 },
  slow_sync_interval_minutes: { unit: "minutes", min: 1, max: 10080, step: 1 },
  sync_page_size: { unit: "rows", min: 50, max: 5000, step: 50 },
  metadata_concurrency: { unit: "", min: 1, max: 32, step: 1 },
  enforce_cooldown_seconds: { unit: "seconds", min: 0, max: 86400, step: 10 },
  automation_daily_cap: { unit: "times a day", min: 1, max: 1000, step: 1 },
  automation_download_cap: { unit: "downloads a day", min: 0, max: 100, step: 1 },
  activity_poll_seconds: { unit: "seconds", min: 1, max: 600, step: 1 },
  upload_capacity_mbps: { unit: "Mbps", min: 0, max: 10000, step: 1 },
  upload_alert_percent: { unit: "%", min: 0, max: 100, step: 5 },
  library_bitrate_threshold_mbps: { unit: "Mbps", min: 0, max: 500, step: 0.5 },
  library_store_depth: { unit: "", min: 1, max: 6, step: 1 },
  access_inactive_days: { unit: "days", min: 1, max: 3650, step: 1 },
  impossible_kmh: { unit: "km/h", min: 1, max: 5000, step: 10 },
  impossible_min_km: { unit: "km", min: 0, max: 5000, step: 10 },
  impossible_max_accuracy_km: { unit: "km", min: 0, max: 5000, step: 10 },
  session_ttl_hours: { unit: "hours", min: 1, max: 8760, step: 1 },
  backup_keep: { unit: "snapshots", min: 0, max: 60, step: 1 },
  backup_hour: { unit: "o'clock", min: 0, max: 23, step: 1 },
  digest_hour: { unit: "o'clock", min: 0, max: 23, step: 1 },
  keep_subtitle_languages: { kind: "chips" },
  keep_audio_languages: { kind: "chips" },
  trusted_proxy_ips: { kind: "chips" },
  apprise_urls: { kind: "lines" },
};

/* Finding the Plex address, once.
 *
 * Letting the library discover it costs twenty seconds every time, because
 * Plex advertises addresses that are unreachable from outside the house and
 * each one has to be waited out. Done here, stored, and never done again.
 * Local addresses are offered first because they are the quick ones from
 * inside the house, and a relay last because it is the slow one. */
function FindServers({ onPick }: { onPick: (url: string, machineId: string) => void }) {
  const [looking, setLooking] = useState(false);
  const [found, setFound] = useState<
    { name: string; machine_identifier: string; owned: boolean; addresses: { uri: string; local: boolean; relay: boolean }[] }[]
  >([]);
  const [error, setError] = useState<string | null>(null);

  async function look() {
    setLooking(true);
    setError(null);
    try {
      const r = await api.get<{ servers: typeof found }>("/plex/servers");
      setFound(r.servers);
      if (r.servers.length === 0) setError("That token can see no servers.");
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setLooking(false);
    }
  }

  return (
    <div className="plex-find">
      <button className="btn" onClick={look} disabled={looking}>
        {looking ? "Looking, this takes a moment…" : "Find servers"}
      </button>
      {error && <p className="note bad-note" role="alert">{error}</p>}
      {found.map((s) => (
        <div key={s.machine_identifier} className="mini">
          <div className="min0">
            <strong>{s.name}</strong> {s.owned ? <span className="pill ok">yours</span> : <span className="pill">shared with you</span>}
            <div className="row wrap" style={{ gap: "6px", marginTop: "6px" }}>
              {s.addresses.map((a) => (
                <button
                  key={a.uri}
                  className="ms-btn"
                  title={a.uri}
                  onClick={() => onPick(a.uri, s.machine_identifier)}
                >
                  {a.relay ? "Relay" : a.local ? "On the network" : "Remote"}
                </button>
              ))}
            </div>
            <p className="muted small">
              Pick the one this container can reach. On the same machine as Plex that is usually the network one.
              Nothing is saved until you press Save.
            </p>
          </div>
        </div>
      ))}
    </div>
  );
}

/* A heading, with its explanation folded away behind an information icon.
 *
 * Every section has a paragraph saying what it is for. They are worth reading
 * once, after which they are the bulk of the page and the controls are the
 * reason anybody opened it. The heading owns the note because a paragraph
 * cannot sit inside a heading, so the icon and the words it reveals have to be
 * drawn by the same thing to share one piece of state.
 *
 * Remembered per heading: somebody working through a page with the notes open
 * should not have to open each one twice.
 */
function Head({
  what,
  note,
  section,
  brand,
  right,
}: {
  what: string;
  note?: string;
  /* A section heading sits in a row with whatever acts on it. A page heading
   * is just the title. */
  section?: boolean;
  /* A section named after a service gets its logo. One named Colour has
   * nothing to show. */
  brand?: boolean;
  right?: ReactNode;
}) {
  const remembered = `settings.explain.${what}`;
  const [open, setOpen] = useState(() => {
    try {
      return localStorage.getItem(remembered) === "on";
    } catch {
      // A private window, or storage turned off. Closed is the right default
      // and the page works either way.
      return false;
    }
  });

  function toggle() {
    const next = !open;
    setOpen(next);
    try {
      localStorage.setItem(remembered, next ? "on" : "off");
    } catch {
      // Nothing depends on it sticking.
    }
  }

  const icon = note ? (
    <button
      className={open ? "explain-toggle on" : "explain-toggle"}
      aria-expanded={open}
      aria-label={open ? `Hide what ${what} is for` : `What ${what} is for`}
      title={open ? "Hide this" : "What this is for"}
      onClick={toggle}
    >
      i
    </button>
  ) : null;

  if (!section) {
    return (
      <>
        <h2>
          {what}
          {icon}
        </h2>
        {note && open && <p className="muted explain-note">{note}</p>}
      </>
    );
  }

  return (
    <>
      <div className="row-between">
        <h3 className="section-title">
          {brand && <BrandIcon name={what.toLowerCase()} size={16} />}
          {what}
          {icon}
        </h3>
        {right}
      </div>
      {note && open && <p className="muted small explain-note">{note}</p>}
    </>
  );
}

/* The cookie's HTTPS lock is off by default, which is right on a LAN and
 * wrong the moment the app is reachable over TLS. Nothing noticed the
 * difference, and the browser is the one that knows: it is the scheme it
 * loaded this page over that decides whether the lock costs anything. */
function HttpsHint({ on }: { on: boolean }) {
  if (on || typeof window === "undefined" || window.location.protocol !== "https:") return null;
  return (
    <p className="note">
      You are reading this over HTTPS and the lock above is off, so the session cookie would also travel over plain
      HTTP. Turn it on unless something still reaches this app without TLS.
    </p>
  );
}


/* A list typed one value at a time, kept as the comma separated string the
 * settings store expects. Enter or a comma commits what is in the box, which
 * is what everyone tries first; leaving the box commits it too, because a
 * value typed and abandoned is a value meant to be there.
 */
function Chips({
  value,
  locked,
  placeholder,
  onChange,
}: {
  value: string;
  locked: boolean;
  placeholder?: string;
  onChange: (next: string) => void;
}) {
  const [typing, setTyping] = useState("");
  const parts = value.split(",").map((x) => x.trim()).filter(Boolean);

  function add(text: string) {
    const wanted = text.trim().replace(/,$/, "").trim();
    setTyping("");
    if (!wanted || parts.includes(wanted)) return;
    onChange([...parts, wanted].join(", "));
  }

  return (
    <div className="chip-field">
      <div className="row chips">
        {parts.map((part) => (
          <button
            key={part}
            type="button"
            className="chip on"
            disabled={locked}
            title="Remove"
            onClick={() => onChange(parts.filter((x) => x !== part).join(", "))}
          >
            {part} &times;
          </button>
        ))}
      </div>
      <input
        disabled={locked}
        spellCheck={false}
        autoComplete="off"
        placeholder={parts.length === 0 ? (placeholder ?? "Add one, then Enter") : "Add another"}
        value={typing}
        onChange={(e) => (e.target.value.includes(",") ? add(e.target.value) : setTyping(e.target.value))}
        onBlur={() => add(typing)}
        onKeyDown={(e) => {
          if (e.key === "Enter") {
            e.preventDefault();
            add(typing);
          } else if (e.key === "Backspace" && !typing && parts.length > 0) {
            onChange(parts.slice(0, -1).join(", "));
          }
        }}
      />
    </div>
  );
}

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

export default function SettingsRoute({
  isAdmin,
  jumpTo,
  onJumped,
}: {
  isAdmin: boolean;
  /* A page id, when something elsewhere in the app sent the person here
   * rather than telling them where to go and leaving them to find it. */
  jumpTo?: string | null;
  onJumped?: () => void;
}) {
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
      <SettingsForm jumpTo={jumpTo} onJumped={onJumped} />
    </div>
  );
}

function SettingsForm({ jumpTo, onJumped }: { jumpTo?: string | null; onJumped?: () => void }) {
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
  const [query, setQuery] = useState("");

  // Cleared as soon as it is used, so coming back to Settings later lands
  // where you left it rather than where you were once sent.
  useEffect(() => {
    if (!jumpTo) return;
    open(jumpTo);
    onJumped?.();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [jumpTo]);

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
    const shape: FieldShape = SHAPES[key] ?? {};

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
          /* A switch rather than an On/Off list: one click, and its state is
             legible without reading the word in it. */
          <button
            type="button"
            role="switch"
            aria-checked={value === true}
            disabled={locked}
            className={value === true ? "switch on" : "switch"}
            onClick={() => setDraft({ ...draft, [key]: value !== true })}
          >
            <span className="knob" />
            <span className="switch-word">{value === true ? "On" : "Off"}</span>
          </button>
        ) : shape.kind === "chips" ? (
          <Chips
            value={String(Array.isArray(value) ? value.join(", ") : value ?? "")}
            locked={locked}
            placeholder={key.includes("language") ? "eng, then Enter" : undefined}
            onChange={(next) => setDraft({ ...draft, [key]: next })}
          />
        ) : shape.kind === "lines" ? (
          /* Many addresses in one setting. One per line is how people paste
             them, and the store already splits on newlines as well as commas. */
          <textarea
            disabled={locked}
            spellCheck={false}
            rows={Math.min(8, Math.max(3, String(value ?? "").split(/[\n,]/).length + 1))}
            placeholder={masked ? "Unchanged" : "One per line"}
            value={masked && !(key in draft) ? "" : String(value ?? "").split(",").map((x) => x.trim()).join("\n")}
            onChange={(e) => setDraft({ ...draft, [key]: e.target.value })}
          />
        ) : key === "activity_source" || key === "library_source" ? (
          <select
            disabled={locked}
            value={String(value ?? "tautulli")}
            onChange={(e) => setDraft({ ...draft, [key]: e.target.value })}
          >
            <option value="tautulli">Tautulli</option>
            <option value="plex">Plex, directly</option>
          </select>
        ) : key === "digest_weekday" ? (
          <select
            disabled={locked}
            value={String(value ?? 0)}
            onChange={(e) => setDraft({ ...draft, [key]: Number(e.target.value) })}
          >
            {["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"].map((day, i) => (
              <option key={day} value={i}>
                {day}
              </option>
            ))}
          </select>
        ) : typeof setting.value === "number" ? (
          <span className="number-field">
            <input
              disabled={locked}
              type="number"
              inputMode="decimal"
              min={shape.min}
              max={shape.max}
              step={shape.step}
              autoComplete="off"
              value={String(value ?? "")}
              onChange={(e) => {
                const text = e.target.value;
                const parsed = Number(text);
                setDraft({ ...draft, [key]: text === "" || Number.isNaN(parsed) ? text : parsed });
              }}
            />
            {shape.unit && <span className="unit">{shape.unit}</span>}
          </span>
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
          <small>One address or CIDR at a time, for example 172.17.0.0/16.</small>
        )}
      </label>
    );
  }

  if (settings.error) return <p className="note bad-note pad" role="alert">{settings.error}</p>;

  const searching = query.trim().length > 0;
  const found = searching ? PAGES.filter((x) => pageHits(x, query)) : PAGES;
  // Searching onto a page with no matches would show an empty page and look
  // broken, so the first page that does have one is opened instead.
  const current =
    (searching && !found.some((x) => x.id === page) ? found[0] : PAGES.find((x) => x.id === page)) ?? PAGES[0];
  // Only the sections that match, unless the page's own name is what matched:
  // typing a page name asks for that page, not for one section of it. Its
  // blurb is not enough, or searching "upload" on a page whose blurb mentions
  // upload would hand back every section it has.
  const wholePage = searching && hits(current.title.toLowerCase(), query);
  const shownSections = (current.sections ?? []).filter(
    (s) => !searching || wholePage || hits(wordsOf(s), query),
  );
  const unsaved = (p: Page) => (p.keys ?? []).some((k) => k in draft);

  return (
    <div className="settings-layout">
      <nav className="settings-nav" aria-label="Settings sections">
        <h1>Settings</h1>
        <div className="settings-search">
          <input
            type="search"
            value={query}
            spellCheck={false}
            placeholder="Search settings"
            aria-label="Search settings"
            onChange={(e) => setQuery(e.target.value)}
            onKeyDown={(e) => e.key === "Escape" && setQuery("")}
          />
        </div>
        {searching && found.length === 0 && <p className="muted small pad-s">Nothing matches.</p>}
        {NAV_GROUPS.map((group) => (
          <div key={group} className="settings-nav-group">
            {found.some((x) => x.group === group) && <span className="settings-nav-label">{group}</span>}
            {found.filter((x) => x.group === group).map((x) => (
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
          <Head key={current.title} what={current.title} note={current.blurb} />
        </header>

        {error && <p className="note bad-note" role="alert">{error}</p>}

        {current.id === "about" && <About />}

        {searching && shownSections.length === 0 && (current.sections?.length ?? 0) > 0 && (
          <p className="muted">Nothing on this page matches. The pages that do match are listed on the left.</p>
        )}

        {shownSections.map((section) => (
          <section key={section.title} className="card-section">
            <Head
              key={section.title}
              what={section.title}
              note={section.note}
              section
              brand
              right={
                section.test && (
                  <TestButton
                    name={section.test}
                    values={Object.fromEntries(section.keys.filter((k) => k in draft).map((k) => [k, draft[k]]))}
                  />
                )
              }
            />
            <div className="grid2">{section.keys.map(field)}</div>
            {section.title === "Schedule" && <SyncNow />}
            {section.title === "Backups" && <ServerTime />}
            {section.title === "Rules" && <ServerTime />}
            {section.title === "Tidying files" && (
              <MediaPaths
                roots={String(draft.media_roots ?? byKey.get("media_roots")?.value ?? "")}
                map={String(draft.media_path_map ?? byKey.get("media_path_map")?.value ?? "")}
                dirty={dirty}
                onRoots={(value) => setDraft({ ...draft, media_roots: value })}
                onMap={(value) => setDraft({ ...draft, media_path_map: value })}
                onSave={save}
              />
            )}
            {section.title === "Problem files" && (
              <BitrateAdvice
                onUse={(mbps) => setDraft({ ...draft, library_bitrate_threshold_mbps: mbps })}
              />
            )}
            {section.title === "Server upload" && <UploadSource />}
            {section.title === "Plex" && (
              <FindServers onPick={(url, id) => setDraft({ ...draft, plex_url: url, plex_machine_identifier: id })} />
            )}
            {section.title === "Sessions" && (
              <HttpsHint on={Boolean(draft.session_cookie_secure ?? byKey.get("session_cookie_secure")?.value)} />
            )}
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
      <Head
        what="Logos and icon"
        note="Stored on the server rather than linked, so they keep working on their own. PNG, JPEG, WebP, SVG, GIF or ICO, up to 4 MB."
        section
      />
      {error && <p className="note bad-note" role="alert">{error}</p>}

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
type Listing = {
  path: string;
  parent: string | null;
  directories: { name: string; path: string }[];
  error: string | null;
};

/* A path typed with the container looking over your shoulder.
 *
 * Which directories exist inside a container is a question only the container
 * can answer, so the box asks it: opening it lists what is there, typing
 * filters the list, Tab completes the one match, and clicking a name goes into
 * it. The value stays a plain string, because that is what gets saved.
 */
function PathBox({
  value,
  placeholder,
  disabled,
  onChange,
}: {
  value: string;
  placeholder?: string;
  disabled?: boolean;
  onChange: (next: string) => void;
}) {
  const [open, setOpen] = useState(false);
  // The directory being listed, which trails the value: typing /media/mo lists
  // /media and filters on "mo".
  const cut = value.lastIndexOf("/");
  const at = !value ? "/" : cut <= 0 ? "/" : value.slice(0, cut);
  const typed = cut < 0 ? value : value.slice(cut + 1);
  const listing = useApi<Listing>(open ? `/library/tidy/directories?path=${encodeURIComponent(at)}` : null, [at, open]);

  const shown = (listing.data?.directories ?? []).filter((row) =>
    row.name.toLowerCase().startsWith(typed.toLowerCase()),
  );

  function go(path: string) {
    onChange(path);
    setOpen(true);
  }

  return (
    <div className="path-box">
      <input
        value={value}
        disabled={disabled}
        spellCheck={false}
        autoComplete="off"
        placeholder={placeholder}
        onFocus={() => setOpen(true)}
        onClick={() => setOpen(true)}
        onChange={(e) => {
          onChange(e.target.value);
          setOpen(true);
        }}
        onKeyDown={(e) => {
          if (e.key === "Tab" && open && shown.length > 0) {
            // One match completes it. Several complete as far as they agree,
            // which is what a shell does and what fingers expect.
            const names = shown.map((row) => row.name);
            let common = names[0];
            for (const name of names) {
              while (!name.toLowerCase().startsWith(common.toLowerCase())) common = common.slice(0, -1);
            }
            if (common.length > typed.length || names.length === 1) {
              e.preventDefault();
              const base = at === "/" ? "" : at;
              onChange(`${base}/${names.length === 1 ? names[0] : common}`);
            }
          } else if (e.key === "Escape") {
            setOpen(false);
          }
        }}
        // A click on a name in the list must land before the blur closes it.
        onBlur={() => window.setTimeout(() => setOpen(false), 150)}
      />
      {open && (
        <div className="path-list">
          {listing.loading && <p className="muted small">Looking</p>}
          {listing.data?.error && <p className="muted small">{listing.data.error}</p>}
          {listing.data && !listing.data.error && (
            <>
              <p className="muted small path-where">{listing.data.path}</p>
              {listing.data.parent && (
                <button type="button" className="path-item" onMouseDown={() => go(listing.data!.parent!)}>
                  .. up
                </button>
              )}
              {shown.map((row) => (
                <button key={row.path} type="button" className="path-item" onMouseDown={() => go(row.path)}>
                  {row.name}
                </button>
              ))}
              {shown.length === 0 && <p className="muted small">Nothing here the container can read.</p>}
            </>
          )}
        </div>
      )}
    </div>
  );
}

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
  root_status: { path: string; exists: boolean; contains: string[]; error: string | null }[];
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
  dirty,
  onRoots,
  onMap,
  onSave,
}: {
  roots: string;
  map: string;
  dirty: boolean;
  onRoots: (value: string) => void;
  onMap: (value: string) => void;
  onSave: () => Promise<void>;
}) {
  const status = useApi<TidyStatusRow>("/library/tidy/status");
  // Held here as well as in the draft so that emptying a row leaves the box on
  // screen instead of taking it out from under the cursor.
  const [checking, setChecking] = useState(false);
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
            <PathBox
              value={row}
              placeholder={index === 0 ? "/media" : "/media2"}
              onChange={(next) => push(rows.map((old, n) => (n === index ? next : old)))}
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
        {/* What is in each mount. A root that is empty or unreadable is a
            different problem from one whose names do not match Plex, and this
            is the only place that difference shows. */}
        {(s?.root_status ?? []).map((root) => (
          <p key={root.path} className="muted small root-contents">
            <code>{root.path}</code>{" "}
            {root.error
              ? `cannot be read: ${root.error}`
              : !root.exists
                ? "is not mounted in this container"
                : root.contains.length === 0
                  ? "is empty"
                  : `holds ${root.contains.join(", ")}`}
          </p>
        ))}
        <div className="row wrap">
          <button className="btn" onClick={() => setRows([...rows, ""])}>
            Add another directory
          </button>
          {/* Checking the value the server still has helps nobody, so this
              saves first when there is anything to save. */}
          <button
            className="btn"
            disabled={status.loading || checking}
            onClick={async () => {
              setChecking(true);
              try {
                if (dirty) await onSave();
                status.reload();
              } finally {
                setChecking(false);
              }
            }}
          >
            {status.loading || checking ? "Looking" : dirty ? "Save and check" : "Check again"}
          </button>
        </div>
      </div>

      {libraries.length === 0 ? (
        <p className="muted small">
          {s && s.checked > 0
            ? "This build of the app does not report the libraries yet. Rebuild the image and this table fills in."
            : "No file paths known yet. The library scan fills these in, and this table then says where each one was found."}
        </p>
      ) : (
        <table className="table media-libraries">
          <thead>
            <tr>
              <th>Library, as Plex reports it</th>
              <th>Found at</th>
              <th className="set-by-hand">Or set it by hand</th>
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
                  {row.found ? (
                    row.here
                  ) : (
                    <>
                      Not readable here
                      {/* The whole path is too long to read and too useful to
                          drop, so it is shortened and kept on hover. */}
                      <span className="path-example" title={row.example}>
                        {row.example}
                      </span>
                    </>
                  )}
                </td>
                <td>
                  <PathBox
                    value={pairs.get(row.library) ?? ""}
                    placeholder={row.found ? (row.here ?? "") : "Pick where it is"}
                    onChange={(next) => setPair(row.library, next)}
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

/* What the server believes the time is.
 *
 * The backup hour and every time-of-day rule read the container's clock, which
 * is whatever TZ says, and a wrong one shifts them silently and for ever.
 * Showing it where those settings are is the whole fix.
 */
function ServerTime() {
  const when = useApi<{ now: string; hour: number; zone: string }>("/server-time");
  if (when.error || !when.data) return null;
  const shown = new Date(when.data.now).toLocaleString();
  return (
    <p className="muted small">
      The server thinks it is <strong>{shown}</strong> ({when.data.zone}). Times here and in rules mean that clock,
      so if it is wrong, set TZ on the container.
    </p>
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
    if (!(await askConfirm({
      title: `Delete the account "${user.username}"?`,
      body: "They are signed out everywhere and cannot sign in again.",
      confirm: "Delete",
      danger: true,
    }))) return;
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
      <Head
        what="Accounts"
        note="Viewers see the map, history and statistics. Admins also get rules, stopping streams and these settings."
        section
        right={
          <button className="btn" onClick={() => setAdding(!adding)}>
            {adding ? "Cancel" : "Add account"}
          </button>
        }
      />

      {error && <p className="note bad-note" role="alert">{error}</p>}

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
      {error && <p className="note bad-note" role="alert">{error}</p>}
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
      <Head
        key={mode}
        what={`The ${mode} theme`}
        note="Four colours, and the rest follows: panels, borders and quieter text are worked out from the panel and the text. Switch the theme in the top bar to set the other one."
        section
      />
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
        <p className="note bad-note" role="alert">
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
      <Head
        what="Colour"
        note="Buttons, links, map pins and charts follow this. Light and dark are worked out from it."
        section
      />
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
