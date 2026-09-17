import { displayTitle, episodeLabel } from "../lib/titles";
import { useState } from "react";
import { useApi, type Enforcement, type MediaDetail } from "../lib/api";
import { useNav } from "../lib/nav";
import BrandIcon from "./BrandIcon";

/* The enforcement log, one expandable record per action.
 *
 * Everything about the stream is a snapshot taken when it was acted on, since
 * the session is gone a moment later. Records from before snapshots existed
 * only know a few fields, so a missing value says so rather than showing a
 * blank that looks like a bug.
 */
export default function EnforcementLog({
  entries,
  onOpenUser,
  empty = "Nothing yet.",
}: {
  entries: Enforcement[];
  onOpenUser?: (userId: number) => void;
  empty?: string;
}) {
  const [open, setOpen] = useState<number | null>(null);

  if (entries.length === 0) return <p className="muted">{empty}</p>;

  return (
    <div className="log-list">
      {entries.map((e) => (
        <StreamEntry
          key={e.id}
          entry={e}
          open={open === e.id}
          onToggle={() => setOpen(open === e.id ? null : e.id)}
          onOpenUser={onOpenUser}
        />
      ))}
    </div>
  );
}

export function StreamEntry({
  entry: e,
  open,
  onToggle,
  onOpenUser,
}: {
  entry: Enforcement;
  open: boolean;
  onToggle: () => void;
  onOpenUser?: (userId: number) => void;
}) {
  const by = e.actor ?? (e.rule_name === "(manual)" ? "Someone, by hand" : e.rule_name);
  const outcome = outcomeOf(e);

  return (
    <article className={open ? "log-entry open" : "log-entry"}>
      <button className="log-summary" onClick={onToggle} aria-expanded={open}>
        <span className="log-when muted small">{when(e.acted_at)}</span>
        <span className="log-what clip">
          <strong>{e.full_title ? displayTitle(e) : "Unknown title"}</strong>
          <span className="muted small clip">
            {[e.username, e.player].filter(Boolean).join(" · ") || "Stream details not recorded"}
          </span>
        </span>
        <span className="log-by muted small clip">{by}</span>
        <span className="log-result">
          <span className={outcome.tone}>{outcome.label}</span>
        </span>
        <span className="log-caret" aria-hidden="true">
          {open ? "▴" : "▾"}
        </span>
      </button>

      {open && <Detail entry={e} by={by} onOpenUser={onOpenUser} />}
    </article>
  );
}

function Detail({
  entry: e,
  by,
  onOpenUser,
}: {
  entry: Enforcement;
  by: string | null;
  onOpenUser?: (userId: number) => void;
}) {
  const nav = useNav();
  const where = [e.city, e.region, e.country].filter(Boolean).join(", ");
  const progress = e.progress_percent ?? null;
  const media = useApi<MediaDetail>(e.rating_key ? `/media/${e.rating_key}` : null, [e.rating_key]);
  const links = media.data ? LINKS.filter((l) => media.data?.links[l.key]) : [];
  const openUser = onOpenUser ?? nav.openUser;

  return (
    <div className="log-detail">
      {e.rating_key ? (
        <img
          className="log-poster"
          src={`/api/media/${e.rating_key}/image?width=200&height=300`}
          alt=""
          onError={(ev) => ((ev.currentTarget as HTMLImageElement).style.display = "none")}
        />
      ) : null}

      <div className="min0">
        {links.length > 0 && (
          <div className="row wrap linkrow">
            {links.map((l) => (
              <a key={l.key} className="ms-btn" href={media.data?.links[l.key]} target="_blank" rel="noreferrer">
                <BrandIcon name={l.key} />
                {l.label}
              </a>
            ))}
          </div>
        )}
        <dl className="kv">
          <Field label="Title">
            {displayTitle(e)}
            {e.year ? ` (${e.year})` : ""}
          </Field>
          {episodeLabel(e) && <Field label="Episode">{episodeLabel(e)}</Field>}
          <Field label="Type">
            {[e.media_type, e.library_name].filter(Boolean).join(" · ") || null}
          </Field>
          <Field label="Who">
            {e.username && e.user_id && openUser ? (
              <button className="linkish" onClick={() => openUser(e.user_id as number)}>
                {e.username}
              </button>
            ) : (
              e.username
            )}
          </Field>
          <Field label="Device">
            {e.machine_id && nav.openDevice ? (
              <button className="linkish" onClick={() => nav.openDevice?.(e.machine_id as string)}>
                {[e.player, e.platform].filter(Boolean).join(" · ") || "Unknown"}
              </button>
            ) : (
              [e.player, e.platform].filter(Boolean).join(" · ") || null
            )}
          </Field>
          <Field label="App">{e.product}</Field>
          <Field label="Device id">
            {e.machine_id ? <code className="small">{e.machine_id}</code> : null}
          </Field>
          <Field label="Where">
            {where && e.ip_address && nav.filterTo ? (
              <button
                className="linkish"
                title="Show plays from this address on the map"
                onClick={() => nav.filterTo?.("Map", { ip_address: [e.ip_address as string] })}
              >
                {where}
              </button>
            ) : (
              where || null
            )}
            {e.location && <span className="pill">{e.location}</span>}
            {e.is_hosting && <span className="pill vpn">VPN / hosting</span>}
          </Field>
          <Field label="Address">
            {e.ip_address && nav.openAddress ? (
              <button className="linkish" onClick={() => nav.openAddress?.(e.ip_address as string)}>
                <code>{e.ip_address}</code>
              </button>
            ) : (
              e.ip_address
            )}
            {e.asn_org ? <span className="muted small">{e.asn_org}</span> : null}
          </Field>
          <Field label="Playback">
            {[
              e.state,
              e.transcode_decision,
              e.video_resolution,
              e.quality_profile,
              e.bandwidth ? `${(e.bandwidth / 1000).toFixed(1)} Mbps` : null,
            ]
              .filter(Boolean)
              .join(" · ") || null}
          </Field>
          <Field label="When">{e.acted_at ? when(e.acted_at, true) : null}</Field>
          <Field label="Triggered by">{by}</Field>
          <Field label="Rule">
            {e.source === "manual" ? (
              "None, done by hand"
            ) : nav.goTo ? (
              <button className="linkish" onClick={() => nav.goTo?.("Rules")}>
                {e.rule_name}
              </button>
            ) : (
              e.rule_name
            )}
          </Field>
          <Field label="Actions">
            {actionNames(e.action)}
            {e.dry_run ? " (rule set to record only, nothing was done)" : ""}
          </Field>
          <Field label="Result">{e.result}</Field>
        </dl>

        {progress !== null && (
          <div className="log-progress">
            <div className="progress">
              <div className="progress-fill" style={{ width: `${Math.min(progress, 100)}%` }} />
            </div>
            <span className="muted small">
              {e.view_offset != null && e.duration
                ? `${clock(e.view_offset)} of ${clock(e.duration)} (${progress}%)`
                : `${progress}%`}
            </span>
          </div>
        )}

        {e.message && (
          <div className="log-message">
            <span className="muted small">Message shown to the viewer</span>
            <p>{e.message}</p>
          </div>
        )}
      </div>
    </div>
  );
}

const ACTION_NAMES: Record<string, string> = {
  terminate: "Stop the stream",
  notify: "Send a notification",
  webhook: "Post to a webhook",
  message_viewer: "Message the viewer",
  log_only: "Record it",
};

function actionNames(action: string | null): string | null {
  if (!action) return null;
  return action
    .split(",")
    .map((a) => ACTION_NAMES[a.trim()] ?? a.trim())
    .join(", ");
}

/* What happened, in a word. A rule can match without stopping anything:
 * set to record only, or with recording or a notification as its action. */
function outcomeOf(e: Enforcement): { label: string; tone: string } {
  const actions = (e.action ?? "").split(",").map((a) => a.trim());
  const result = (e.result ?? "").toLowerCase();
  if (e.dry_run) return { label: "recorded only", tone: "pill" };
  if (result.startsWith("refused") || result.includes("failed")) return { label: "refused", tone: "pill bad" };
  if (actions.includes("terminate") && result.includes("terminated")) return { label: "stopped", tone: "pill banned" };
  if (actions.length === 1 && actions[0] === "log_only") return { label: "logged", tone: "pill" };
  if (actions.includes("notify") || actions.includes("webhook") || actions.includes("message_viewer"))
    return { label: "notified", tone: "pill warn" };
  return { label: e.result || "acted", tone: "pill warn" };
}

const LINKS: { key: string; label: string }[] = [
  { key: "plex", label: "Plex" },
  { key: "imdb", label: "IMDb" },
  { key: "tmdb", label: "TMDB" },
  { key: "trakt", label: "Trakt" },
  { key: "radarr", label: "Radarr" },
  { key: "sonarr", label: "Sonarr" },
  { key: "seerr", label: "Seerr" },
];

function Field({ label, children }: { label: string; children: React.ReactNode }) {
  const empty =
    children === null ||
    children === undefined ||
    children === "" ||
    (Array.isArray(children) && children.every((c) => c === null || c === undefined || c === "" || c === false));
  return (
    <div>
      <dt>{label}</dt>
      <dd>{empty ? <span className="muted small">Not recorded</span> : children}</dd>
    </div>
  );
}

/* Stored as UTC without a zone marker, which a browser would otherwise read
 * as local time and show hours out. */
export function when(value: string | null, long = false): string {
  if (!value) return "";
  const iso = /[zZ]|[+-]\d\d:?\d\d$/.test(value) ? value : `${value}Z`;
  const date = new Date(iso);
  return long
    ? date.toLocaleString(undefined, { dateStyle: "full", timeStyle: "medium" })
    : date.toLocaleString();
}

export function clock(ms: number): string {
  const total = Math.floor(ms / 1000);
  const h = Math.floor(total / 3600);
  const m = Math.floor((total % 3600) / 60);
  const s = total % 60;
  const mm = String(m).padStart(h ? 2 : 1, "0");
  const ss = String(s).padStart(2, "0");
  return h ? `${h}:${mm}:${ss}` : `${mm}:${ss}`;
}
