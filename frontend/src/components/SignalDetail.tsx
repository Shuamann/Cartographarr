import Loading from "./Loading";
import { displayTitle } from "../lib/titles";
import { useState } from "react";
import { api, useApi } from "../lib/api";
import { useBans } from "../lib/bans";
import { useNav } from "../lib/nav";

type Play = {
  row_id: number;
  rating_key: number | null;
  full_title: string | null;
  started: number | null;
  stopped: number | null;
  play_duration: number | null;
  player: string | null;
  platform: string | null;
  product: string | null;
  machine_id: string | null;
  transcode_decision: string | null;
  location: string | null;
};

type Place = {
  city: string | null;
  region: string | null;
  country: string | null;
  accuracy_km: number | null;
  asn_org: string | null;
  is_hosting: boolean | null;
};

type Side = { play: Play | null; place: Place | null };

export type SignalData = {
  id: number;
  user_id: number;
  user_name: string;
  kind: "concurrent" | "travel";
  status: "new" | "reviewed" | "ignored";
  km: number | null;
  hours: number | null;
  kmh: number | null;
  hosting_involved: boolean;
  from_ip: string | null;
  to_ip: string | null;
  from: Side;
  to: Side;
  gap_seconds: number | null;
  pattern_label: string;
  similar: number;
  /** Networks at either end that have put this account in several cities, and
   *  which ones. A connection that moves explains a signal on its own. */
  roaming?: Record<string, { cities: string[]; count: number }>;
  ignore: { id: number; label: string | null; reason: string | null; created_by: string | null } | null;
};

/* Everything behind one sharing signal.
 *
 * Both plays side by side, what separates them, and what Reviewed and Ignore
 * would each do, spelled out, since they do different things: Reviewed closes
 * this one, Ignore treats the pair of places as normal for this person from now
 * on.
 */
export default function SignalDetail({ id, onChanged }: { id: number; onChanged?: () => void }) {
  const nav = useNav();
  const bans = useBans();
  const detail = useApi<SignalData>(`/travel-flags/${id}`);
  const [busy, setBusy] = useState(false);
  const [note, setNote] = useState<string | null>(null);

  if (detail.error) return <p className="note bad-note" role="alert">{detail.error}</p>;
  if (!detail.data) return <Loading compact />;
  const s = detail.data;

  async function setStatus(status: "new" | "reviewed" | "ignored") {
    let reason = "";
    if (status === "ignored") {
      const answer = window.prompt(
        `Ignore signals for ${s.user_name} between ${s.pattern_label}?\n\n` +
          `This one closes, so do ${s.similar} similar signal${s.similar === 1 ? "" : "s"} already found, ` +
          `and new ones are recorded as ignored. You can undo it.\n\nWhy is this expected (optional)?`,
        "",
      );
      if (answer === null) return;
      reason = answer;
    }
    setBusy(true);
    setNote(null);
    try {
      const r = await api.patch<{ closed_too: number }>(`/travel-flags/${id}`, { status, reason });
      if (status === "ignored" && r.closed_too) setNote(`Also closed ${r.closed_too} matching signal${r.closed_too === 1 ? "" : "s"}.`);
      detail.reload();
      onChanged?.();
    } catch (err) {
      setNote((err as Error).message);
    } finally {
      setBusy(false);
    }
  }

  async function stopIgnoring() {
    if (!s.ignore) return;
    if (!window.confirm(`Stop ignoring ${s.pattern_label} for ${s.user_name}? Signals it closed reopen.`)) return;
    setBusy(true);
    try {
      const r = await api.del<{ reopened: number }>(`/signal-ignores/${s.ignore.id}`);
      setNote(`Reopened ${r.reopened} signal${r.reopened === 1 ? "" : "s"}.`);
      detail.reload();
      onChanged?.();
    } finally {
      setBusy(false);
    }
  }

  const accuracy = Math.max(s.from.place?.accuracy_km ?? 0, s.to.place?.accuracy_km ?? 0);
  const gap = s.gap_seconds ?? 0;
  const firstDay = s.from.play?.started ? day(s.from.play.started) : "";
  const lastDay = s.to.play?.started ? day(s.to.play.started) : firstDay;

  return (
    <div className="signal-detail">
      <dl className="stats">
        <Stat label="Distance" value={s.km != null ? `${Math.round(s.km).toLocaleString()} km` : "?"} />
        <Stat
          label={gap < 0 ? "Overlap" : "Time between"}
          value={s.gap_seconds == null ? "?" : span(Math.abs(gap))}
        />
        <Stat
          label="Speed needed"
          value={s.kind === "concurrent" ? "at once" : s.kmh != null ? `${Math.round(s.kmh).toLocaleString()} km/h` : "?"}
        />
        <Stat label="Location accuracy" value={accuracy ? `±${accuracy} km` : "unknown"} />
      </dl>
      <p className="muted small">
        {s.kind === "concurrent"
          ? gap < 0
            ? `The second play started ${span(-gap)} before the first one finished, ${Math.round(s.km ?? 0).toLocaleString()} km away.`
            : `The second play started ${span(gap)} after the first finished, ${Math.round(s.km ?? 0).toLocaleString()} km away. Too soon to be a journey, so it counts as at once.`
          : `Getting from one to the other in ${span(gap)} means about ${Math.round(s.kmh ?? 0).toLocaleString()} km/h.`}
        {" "}Locations are city level, accurate to about {accuracy || "an unknown number of"} km.
        {s.hosting_involved && " A VPN or hosting network is involved, which can explain this without anyone sharing a password."}
      </p>

      {Object.entries(s.roaming ?? {}).map(([network, seen]) => (
        <p key={network} className="note" title="Worked out from this account's own plays over the last six months">
          <strong>{network}</strong> has put {s.user_name} in {seen.count} different{" "}
          {seen.count === 1 ? "city" : "cities"} lately: {seen.cities.join(", ")}. A connection that lands in a
          different place each time, which a mobile network usually does, explains this without anyone sharing
          anything.
        </p>
      ))}

      <div className="signal-sides">
        <SideCard title="First play" side={s.from} ip={s.from_ip} banned={bans.ids} />
        <SideCard title="Second play" side={s.to} ip={s.to_ip} banned={bans.ids} />
      </div>

      <div className="signal-pattern">
        {s.ignore ? (
          <p className="small">
            <span className="pill">ignored pattern</span> {s.user_name} between {s.pattern_label} is treated as expected
            {s.ignore.reason ? `: ${s.ignore.reason}` : ""}
            {s.ignore.created_by ? `, set by ${s.ignore.created_by}` : ""}.
          </p>
        ) : (
          <p className="muted small">
            {s.similar > 0
              ? `${s.similar} other signal${s.similar === 1 ? "" : "s"} for ${s.user_name} between ${s.pattern_label}.`
              : `No other signals for ${s.user_name} between ${s.pattern_label}.`}
          </p>
        )}
      </div>

      {note && <p className="note">{note}</p>}

      <div className="row wrap signal-actions">
        {nav.filterTo && (
          <button
            className="btn"
            onClick={() => nav.filterTo?.("Map", { user_id: [s.user_id], start: firstDay, end: lastDay })}
          >
            Show on map
          </button>
        )}
        {nav.openUser && (
          <button className="btn" onClick={() => nav.openUser?.(s.user_id)}>
            Open {s.user_name}
          </button>
        )}
        {nav.isAdmin && (
          <span className="row signal-review">
            {s.status !== "reviewed" && (
              <button className="btn" onClick={() => setStatus("reviewed")} disabled={busy} title="Close this one signal. Nothing else changes.">
                Reviewed
              </button>
            )}
            {s.status !== "ignored" && (
              <button
                className="btn"
                onClick={() => setStatus("ignored")}
                disabled={busy}
                title={`Treat ${s.pattern_label} as normal for ${s.user_name}: closes matching signals now and in future.`}
              >
                Ignore this pattern
              </button>
            )}
            {s.ignore && (
              <button className="btn" onClick={stopIgnoring} disabled={busy}>
                Stop ignoring
              </button>
            )}
            {s.status !== "new" && !s.ignore && (
              <button className="btn" onClick={() => setStatus("new")} disabled={busy}>
                Reopen
              </button>
            )}
          </span>
        )}
      </div>
    </div>
  );
}

function SideCard({ title, side, ip, banned }: { title: string; side: Side; ip: string | null; banned: Set<string> }) {
  const nav = useNav();
  const p = side.play;
  const where = side.place ? [side.place.city, side.place.region, side.place.country].filter(Boolean).join(", ") : null;

  return (
    <section className="signal-side">
      <h4>{title}</h4>
      {!p ? (
        <p className="muted small">This play is no longer in the history.</p>
      ) : (
        <div className="signal-side-body">
          {p.rating_key ? (
            <img
              className="signal-poster"
              src={`/api/media/${p.rating_key}/image?width=120&height=180`}
              alt=""
              onError={(e) => ((e.currentTarget as HTMLImageElement).style.visibility = "hidden")}
            />
          ) : (
            <div className="signal-poster" />
          )}
          <dl className="spec">
            <dt>Watched</dt>
            <dd>{p.full_title ? displayTitle(p) : "Unknown"}</dd>
            <dt>When</dt>
            <dd>
              {p.started ? new Date(p.started * 1000).toLocaleString() : "?"}
              {p.stopped
                ? ` to ${
                    p.started && day(p.started) === day(p.stopped)
                      ? new Date(p.stopped * 1000).toLocaleTimeString()
                      : new Date(p.stopped * 1000).toLocaleString()
                  }`
                : ""}
              {/* Open far longer than it was watched: left paused, not played. */}
              {p.started && p.stopped && p.play_duration != null && p.stopped - p.started > p.play_duration + 3600 && (
                <span className="pill" title="The session stayed open long after anyone was watching it">
                  left paused {span(p.stopped - p.started - p.play_duration)}
                </span>
              )}
            </dd>
            <dt>Device</dt>
            <dd>
              {p.machine_id && nav.openDevice ? (
                <button className="linkish" onClick={() => nav.openDevice?.(p.machine_id as string)}>
                  {[p.player, p.platform].filter(Boolean).join(" · ") || "Unknown"}
                </button>
              ) : (
                [p.player, p.platform].filter(Boolean).join(" · ") || "Unknown"
              )}
              {p.machine_id && banned.has(p.machine_id) && <span className="pill banned">banned</span>}
            </dd>
            <dt>Where</dt>
            <dd>
              {where ?? "Unknown"}
              {side.place?.accuracy_km ? <span className="muted small">±{side.place.accuracy_km} km</span> : null}
            </dd>
            <dt>Address</dt>
            <dd>
              {ip ?? "?"}
              {p.location && <span className="pill">{p.location.toUpperCase()}</span>}
            </dd>
            <dt>Network</dt>
            <dd>
              {side.place?.asn_org ?? "Unknown"}
              {side.place?.is_hosting && <span className="pill vpn">VPN</span>}
            </dd>
            <dt>Playback</dt>
            <dd>
              {[p.transcode_decision, p.play_duration ? span(p.play_duration) : null].filter(Boolean).join(" · ") || "?"}
            </dd>
          </dl>
        </div>
      )}
      {p?.machine_id && nav.blockDevice && !banned.has(p.machine_id) && (
        <button className="btn danger small-btn" onClick={() => nav.blockDevice?.(p.machine_id as string, p.player || "this device")}>
          Ban this device
        </button>
      )}
    </section>
  );
}

function Stat({ label, value }: { label: string; value: string }) {
  return (
    <div className="stat">
      <dt>{label}</dt>
      <dd>{value}</dd>
    </div>
  );
}

function span(seconds: number): string {
  if (seconds < 60) return `${Math.round(seconds)} s`;
  if (seconds < 3600) return `${Math.round(seconds / 60)} min`;
  if (seconds < 86400) return `${(seconds / 3600).toFixed(1)} h`;
  return `${(seconds / 86400).toFixed(1)} days`;
}

function day(epoch: number): string {
  const d = new Date(epoch * 1000);
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`;
}
