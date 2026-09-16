import { useState } from "react";
import type { Enforcement } from "../lib/api";

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
  const by = e.actor ?? (e.rule_name === "(manual)" ? "Someone, manually" : e.rule_name);

  return (
    <article className={open ? "log-entry open" : "log-entry"}>
      <button className="log-summary" onClick={onToggle} aria-expanded={open}>
        <span className="log-when muted small">{when(e.acted_at)}</span>
        <span className="log-what clip">
          <strong>{e.full_title ?? "Unknown title"}</strong>
          <span className="muted small clip">
            {[e.username, e.player].filter(Boolean).join(" · ") || "Stream details not recorded"}
          </span>
        </span>
        <span className="log-by muted small clip">{by}</span>
        <span className="log-result">
          <span className={e.dry_run ? "pill" : "pill warn"}>{e.dry_run ? "dry run" : "acted"}</span>
          <span className="small">{e.result}</span>
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
  const where = [e.city, e.region, e.country].filter(Boolean).join(", ");
  const progress = e.progress_percent ?? null;

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
        <dl className="kv">
          <Field label="Title">
            {e.full_title}
            {e.year ? ` (${e.year})` : ""}
          </Field>
          <Field label="Type">
            {[e.media_type, e.library_name].filter(Boolean).join(" · ") || null}
          </Field>
          <Field label="Who">
            {e.username && e.user_id && onOpenUser ? (
              <button className="linkish" onClick={() => onOpenUser(e.user_id as number)}>
                {e.username}
              </button>
            ) : (
              e.username
            )}
          </Field>
          <Field label="Device">
            {[e.player, e.platform].filter(Boolean).join(" · ") || null}
          </Field>
          <Field label="App">{e.product}</Field>
          <Field label="Device id">
            {e.machine_id ? <code className="small">{e.machine_id}</code> : null}
          </Field>
          <Field label="Where">
            {where || null}
            {e.location && <span className="pill">{e.location}</span>}
            {e.is_hosting && <span className="pill vpn">VPN / hosting</span>}
          </Field>
          <Field label="Address">
            {e.ip_address}
            {e.asn_org ? ` · ${e.asn_org}` : ""}
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
          <Field label="Stopped by">{by}</Field>
          <Field label="Rule">{e.source === "manual" ? "None, done by hand" : e.rule_name}</Field>
          <Field label="Action">
            {e.action}
            {e.dry_run ? " (dry run, nothing was stopped)" : ""}
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
