import { useEffect, useMemo, useState } from "react";
import { api, useApi, type Activity, type Dashboard, type LiveSession } from "../lib/api";
import { useIsAvailable } from "../components/Gated";
import TravelFlags from "../components/TravelFlags";
import EnforcementLog from "../components/EnforcementLog";
import FilterBar from "../components/FilterBar";
import { toQuery, type FilterState } from "../lib/filters";

/* The landing screen.
 *
 * What goes here is still being worked out, so this reads from ONE endpoint
 * (/api/dashboard) that composes every source: local database, live Tautulli
 * activity, capabilities, and integrations once they exist. Rearranging the
 * layout, or adding a panel, doesn't mean touching the data path.
 */
export default function DashboardRoute({
  onNavigate,
  isAdmin,
  onOpenUser,
  onBlockDevice,
  onShowOnMap,
  filters,
  onFilters,
}: {
  onNavigate: (tab: string) => void;
  isAdmin?: boolean;
  onOpenUser?: (userId: number) => void;
  onBlockDevice?: (machineId: string, label: string) => void;
  onShowOnMap?: (session: LiveSession) => void;
  filters: FilterState;
  onFilters: (next: FilterState) => void;
}) {
  const query = useMemo(() => toQuery(filters), [filters]);
  const data = useApi<Dashboard>(`/dashboard${query}`);
  // Streams move faster than the rest of the page, and /dashboard is a much
  // heavier query, so live activity gets its own quicker poll instead of
  // dragging every count and chart along with it.
  const activity = useApi<Activity>("/activity");

  useEffect(() => {
    const slow = setInterval(data.reload, 15000);
    const fast = setInterval(activity.reload, 5000);
    return () => {
      clearInterval(slow);
      clearInterval(fast);
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  if (data.error) return <div className="pad"><p className="note bad-note">{data.error}</p></div>;
  if (!data.data) return <div className="pad muted">Loading…</div>;

  const d = data.data;
  const live = activity.data ?? d.live;

  return (
    <div className="dash-page">
      <FilterBar value={filters} onChange={onFilters} />

      <div className="pad scroll dash">
      <div className="row-between">
        <h1>{d.capabilities.server.name ?? "Cartographarr"}</h1>
        <span className="muted small">
          Plex {d.capabilities.server.version}
          {d.capabilities.plex_pass.active === false && " · no Plex Pass"}
        </span>
      </div>

      {live.error && <p className="note bad-note">{live.error}</p>}

      <NowPlaying
        sessions={live.sessions}
        transcoding={live.transcode_count}
        onChanged={activity.reload}
        onBlockDevice={onBlockDevice}
        onOpenUser={onOpenUser}
        onShowOnMap={onShowOnMap}
      />

      <section className="cards">
        <Card
          big={live.stream_count ?? 0}
          label={live.stream_count === 1 ? "stream now" : "streams now"}
          sub={live.transcode_count ? `${live.transcode_count} transcoding` : "all direct"}
          accent
        />
        <Card
          big={d.totals.plays}
          label="plays"
          sub={d.filtered ? "matching filters" : "all time"}
          onClick={() => onNavigate("Map")}
        />
        <Card big={d.totals.users} label="users" sub={`${d.totals.devices} devices`} />
        <Card
          big={d.totals.hosting_ips}
          label="VPN origins"
          sub={`of ${d.totals.ip_locations} addresses`}
          warn={d.totals.hosting_ips > 0}
          onClick={() => onNavigate("Map")}
        />
        <Card
          big={d.totals.new_devices}
          label="new devices"
          sub="not yet reviewed"
          warn={d.totals.new_devices > 0}
          onClick={() => onNavigate("Devices")}
        />
        <Card
          big={d.totals.travel_flags}
          label="sharing signals"
          sub="unreviewed"
          warn={d.totals.travel_flags > 0}
        />
      </section>

      <div className="dash-cols">
        <section>
          <h2 className="section-head">Last 30 days</h2>
          <Sparkline points={d.plays_by_day} />
        </section>

        <section>
          <h2 className="section-head">Most plays</h2>
          <div className="mini-list">
            {d.top_users.map((u) => (
              <div key={u.user_id} className="mini">
                <span>{u.name}</span>
                <span className="muted">{u.plays.toLocaleString()}</span>
              </div>
            ))}
          </div>
        </section>
      </div>

      <TravelFlags isAdmin={Boolean(isAdmin)} onOpenUser={onOpenUser} />

      <section>
        <div className="row-between">
          <h2 className="section-head">Recent stream actions</h2>
          {isAdmin && (
            <button className="tab" onClick={() => onNavigate("Log")}>
              Full log
            </button>
          )}
        </div>
        {d.settings.enforce_dry_run && (
          <p className="muted small">Dry run is on, so rules record but don't act.</p>
        )}
        <EnforcementLog entries={d.recent_enforcement} onOpenUser={onOpenUser} />
      </section>
      </div>
    </div>
  );
}

const VISIBLE = 4;

/* Live streams as their own strip across the top.
 *
 * Collapsed to a single row when there are more than fit, because a busy
 * evening should not push the rest of the dashboard off the screen.
 */
/* Every live stream, and everything you can do to one.
 *
 * This used to be a tab of its own. Splitting a handful of sessions across two
 * screens meant the dashboard could only ever be a teaser for the real page,
 * so the real page moved in here.
 */
function NowPlaying({
  sessions,
  transcoding,
  onChanged,
  onBlockDevice,
  onOpenUser,
  onShowOnMap,
}: {
  sessions: LiveSession[];
  transcoding: number | null;
  onChanged: () => void;
  onBlockDevice?: (machineId: string, label: string) => void;
  onOpenUser?: (userId: number) => void;
  onShowOnMap?: (session: LiveSession) => void;
}) {
  const [expanded, setExpanded] = useState(false);
  const [open, setOpen] = useState<string | null>(null);

  if (sessions.length === 0) {
    return (
      <section className="now-playing empty">
        <h2 className="section-head">Now playing</h2>
        <p className="muted">
          Nothing streaming right now. Sessions appear within a few seconds of playback starting.
        </p>
      </section>
    );
  }

  const shown = expanded ? sessions : sessions.slice(0, VISIBLE);
  const hidden = sessions.length - shown.length;
  const current = sessions.find((s) => s.session_key === open) ?? null;

  return (
    <section className="now-playing">
      <div className="row-between">
        <h2 className="section-head">
          Now playing
          <span className="pill">{sessions.length}</span>
        </h2>
        <div className="row">
          <span className="muted small">
            {transcoding ? `${transcoding} transcoding` : "all direct play"}
          </span>
          {sessions.length > VISIBLE && (
            <button className="tab" onClick={() => setExpanded(!expanded)}>
              {expanded ? "Show fewer" : `Show all ${sessions.length}`}
            </button>
          )}
        </div>
      </div>

      <div className="stream-strip">
        {shown.map((s) => (
          <StreamCard
            key={s.session_key}
            session={s}
            selected={s.session_key === open}
            onClick={() => setOpen(open === s.session_key ? null : s.session_key)}
          />
        ))}
        {!expanded && hidden > 0 && (
          <button className="stream-card more" onClick={() => setExpanded(true)}>
            <span className="card-big">+{hidden}</span>
            <span className="card-sub">more streaming</span>
          </button>
        )}
      </div>

      {current && (
        <StreamDetail
          session={current}
          onClose={() => setOpen(null)}
          onChanged={onChanged}
          onBlockDevice={onBlockDevice}
          onOpenUser={onOpenUser}
          onShowOnMap={onShowOnMap}
        />
      )}
    </section>
  );
}

function StreamCard({
  session,
  selected,
  onClick,
}: {
  session: LiveSession;
  selected: boolean;
  onClick: () => void;
}) {
  const progress = Math.min(Number(session.progress_percent ?? 0), 100);
  const who = session.friendly_name || session.username || "Unknown";

  return (
    <button className={selected ? "stream-card on" : "stream-card"} onClick={onClick}>
      {session.rating_key ? (
        <img
          className="stream-poster"
          src={`/api/media/${session.rating_key}/image?width=120&height=180`}
          alt=""
          onError={(e) => ((e.currentTarget as HTMLImageElement).style.visibility = "hidden")}
        />
      ) : (
        <div className="stream-poster" />
      )}
      <span className="stream-body">
        <strong className="clip">{session.full_title}</strong>
        <span className="muted small clip">{who}</span>
        <span className="muted small clip">
          {session.player}
          {session.transcode_decision === "transcode" && (
            <span className="pill warn">transcode</span>
          )}
          {session.geo?.is_hosting && <span className="pill warn">VPN</span>}
        </span>
        <span className="progress">
          <span className="progress-fill" style={{ width: `${progress}%` }} />
        </span>
      </span>
    </button>
  );
}

function StreamDetail({
  session,
  onClose,
  onChanged,
  onBlockDevice,
  onOpenUser,
  onShowOnMap,
}: {
  session: LiveSession;
  onClose: () => void;
  onChanged: () => void;
  onBlockDevice?: (machineId: string, label: string) => void;
  onOpenUser?: (userId: number) => void;
  onShowOnMap?: (session: LiveSession) => void;
}) {
  const [stopping, setStopping] = useState(false);
  const [fullSummary, setFullSummary] = useState(false);

  const who = session.friendly_name || session.username || "Unknown";
  const where = session.geo
    ? [session.geo.city, session.geo.region, session.geo.country].filter(Boolean).join(", ")
    : null;
  const progress = Math.min(Number(session.progress_percent ?? 0), 100);
  const offset = Number(session.view_offset ?? 0);
  const duration = Number(session.duration ?? 0);

  // An episode reads as the show on top and the episode beneath, which is how
  // everyone looks for it, rather than one long "Show - Episode" string.
  const episodic = session.media_type === "episode";
  const heading = episodic ? session.grandparent_title : session.title || session.full_title;
  const subheading = episodic
    ? [session.parent_title, session.title].filter(Boolean).join(" \u00b7 ")
    : null;

  return (
    <article className="stream-detail">
      <button className="icon-btn stream-close" onClick={onClose} aria-label="Close">
        &times;
      </button>

      <div className="stream-detail-body">
        {session.rating_key ? (
          <img
            className="stream-detail-poster"
            src={`/api/media/${session.rating_key}/image?width=300&height=450`}
            alt=""
            onError={(e) => ((e.currentTarget as HTMLImageElement).style.visibility = "hidden")}
          />
        ) : (
          <div className="stream-detail-poster" />
        )}

        <div className="min0 stream-detail-main">
          <h3>{heading ?? session.full_title}</h3>
          {subheading && <p className="stream-sub">{subheading}</p>}
          <p className="muted small">
            {[session.year, session.content_rating, session.library_name]
              .filter(Boolean)
              .join(" \u00b7 ")}
          </p>

          {session.summary && (
            <p
              className={fullSummary ? "stream-summary" : "stream-summary clamp"}
              onClick={() => setFullSummary((v) => !v)}
              title={fullSummary ? "Show less" : "Show more"}
            >
              {session.summary}
            </p>
          )}

          <dl className="spec">
            <Spec label="User">
              {session.user_id && onOpenUser ? (
                <button className="linkish" onClick={() => onOpenUser(session.user_id as number)}>
                  {who}
                </button>
              ) : (
                who
              )}
            </Spec>
            <Spec label="Player">
              {session.player}
              {session.platform ? ` (${session.platform})` : ""}
            </Spec>
            <Spec label="Product">{session.product}</Spec>
            <Spec label="Quality">
              {session.quality_profile}
              {session.stream_bitrate ? ` \u00b7 ${mbps(session.stream_bitrate)}` : ""}
            </Spec>
            <Spec label="Stream">{decision(session.transcode_decision)}</Spec>
            <Spec label="Container">
              {arrow(session.container, session.stream_container, session.transcode_decision)}
            </Spec>
            <Spec label="Video">
              {decision(session.video_decision)}
              {" \u00b7 "}
              {arrow(
                fmt(session.video_codec, session.video_full_resolution),
                fmt(session.stream_video_codec, session.stream_video_full_resolution),
                session.video_decision,
              )}
            </Spec>
            <Spec label="Audio">
              {decision(session.audio_decision)}
              {" \u00b7 "}
              {arrow(
                fmt(session.audio_codec, session.audio_channel_layout),
                fmt(session.stream_audio_codec, session.audio_channel_layout),
                session.audio_decision,
              )}
            </Spec>
            {session.subtitle_decision && (
              <Spec label="Subtitles">{decision(session.subtitle_decision)}</Spec>
            )}
            <Spec label="Location">
              <span className="pill">{(session.location || "").toUpperCase() || "?"}</span>
              {session.ip_address}
              {where ? ` \u00b7 ${where}` : ""}
              {session.geo?.is_hosting && <span className="pill warn">VPN</span>}
            </Spec>
            <Spec label="Network">
              {session.geo?.asn_org ?? "Unknown"}
              {session.relayed && Number(session.relayed) ? " \u00b7 relayed" : ""}
              {session.secure !== null && session.secure !== undefined
                ? Number(session.secure)
                  ? " \u00b7 secure"
                  : " \u00b7 not secure"
                : ""}
            </Spec>
            <Spec label="Bandwidth">{session.bandwidth ? mbps(session.bandwidth) : null}</Spec>
          </dl>
        </div>
      </div>

      <div className="stream-progress">
        <div className="progress">
          <div className="progress-fill" style={{ width: `${progress}%` }} />
        </div>
        <div className="row-between small">
          <span>
            <span className={session.state === "playing" ? "pill ok" : "pill"}>
              {session.state ?? "unknown"}
            </span>{" "}
            {duration ? `${clock(offset)} / ${clock(duration)}` : `${progress}%`}
          </span>
          <span className="muted">
            {duration ? `${clock(Math.max(duration - offset, 0))} left \u00b7 ${progress}%` : ""}
          </span>
        </div>
      </div>

      {/* Show on map sits apart on the left: it only looks, while the two on
          the right act on someone's stream. */}
      <div className="stream-actions">
        {onShowOnMap && session.geo?.lat != null ? (
          <button className="btn" onClick={() => onShowOnMap(session)}>
            Show on map
          </button>
        ) : (
          <span />
        )}
        <div className="row">
          <button className="btn" onClick={() => setStopping((v) => !v)}>
            {stopping ? "Cancel" : "Stop stream"}
          </button>
          {onBlockDevice && session.machine_id && (
            <button
              className="btn danger"
              onClick={() =>
                onBlockDevice(
                  session.machine_id as string,
                  session.player || (session.machine_id as string).slice(0, 8),
                )
              }
            >
              Ban device
            </button>
          )}
        </div>
      </div>

      {stopping && (
        <StopForm
          session={session}
          onDone={() => {
            setStopping(false);
            onChanged();
          }}
        />
      )}
    </article>
  );
}

function Spec({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <>
      <dt>{label}</dt>
      <dd>{children}</dd>
    </>
  );
}

function decision(value: string | null | undefined): string {
  if (!value) return "Unknown";
  if (value === "copy") return "Direct stream";
  if (value === "direct play") return "Direct play";
  return value.charAt(0).toUpperCase() + value.slice(1);
}

function fmt(codec: string | null | undefined, extra: string | null | undefined): string {
  return [codec?.toUpperCase(), extra].filter(Boolean).join(" ");
}

/* "H264 1080 \u2192 HEVC 720" when it is being converted, just the source when not. */
function arrow(source: string | null | undefined, stream: string | null | undefined, how: string | null | undefined) {
  const src = (source || "").toString();
  const out = (stream || "").toString();
  if (how === "transcode" && out && out.toLowerCase() !== src.toLowerCase()) {
    return `${src.toUpperCase() || "?"} \u2192 ${out.toUpperCase()}`;
  }
  return src.toUpperCase() || "Unknown";
}

function mbps(kbps: string | number): string {
  return `${(Number(kbps) / 1000).toFixed(1)} Mbps`;
}

function clock(ms: number): string {
  const total = Math.floor(ms / 1000);
  const h = Math.floor(total / 3600);
  const m = Math.floor((total % 3600) / 60);
  const sec = String(total % 60).padStart(2, "0");
  return h ? `${h}:${String(m).padStart(2, "0")}:${sec}` : `${m}:${sec}`;
}

const DEFAULT_MESSAGE = "This device is not permitted to stream. Contact the server owner.";

function StopForm({ session, onDone }: { session: LiveSession; onDone: () => void }) {
  const [message, setMessage] = useState(DEFAULT_MESSAGE);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const plexPass = useIsAvailable("plex_pass");

  async function stop() {
    setBusy(true);
    setError(null);
    try {
      await api.post(`/activity/${session.session_key}/terminate`, { message });
      onDone();
    } catch (err) {
      setError((err as Error).message);
      setBusy(false);
    }
  }

  return (
    <div className="stop-form">
      <label>
        Message shown to the viewer
        <textarea rows={2} value={message} onChange={(e) => setMessage(e.target.value)} />
      </label>

      {/* Plex composes the on-screen text itself; only the middle is ours.
          Showing the whole thing avoids a round of "why does it say that". */}
      <div className="preview">
        <span className="preview-label">They will see</span>
        <p>
          <span className="fixed">
            Your Plex account name asked to stop your playback from this server:{" "}
          </span>
          <span className="ours">{message}</span>
          <span className="fixed"> {session.session_key}</span>
        </p>
        <small className="muted">
          Only the highlighted part is editable. Plex adds the rest and it cannot be changed.
        </small>
      </div>

      {error && <p className="note bad-note">{error}</p>}

      <div className="row">
        <button className="btn danger" onClick={stop} disabled={busy || !plexPass.ok}>
          {busy ? "Stopping\u2026" : `Stop ${session.friendly_name || session.username}'s stream`}
        </button>
        {!plexPass.ok && <span className="muted small">{plexPass.reason}</span>}
      </div>
    </div>
  );
}

function Card({
  big,
  label,
  sub,
  onClick,
  accent,
  warn,
}: {
  big: number;
  label: string;
  sub?: string;
  onClick?: () => void;
  accent?: boolean;
  warn?: boolean;
}) {
  const className = ["card", accent && big > 0 ? "accent" : "", warn ? "warn" : ""]
    .filter(Boolean)
    .join(" ");
  return (
    <div className={className} onClick={onClick} role={onClick ? "button" : undefined}>
      <span className="card-big">{big.toLocaleString()}</span>
      <span className="card-label">{label}</span>
      {sub && <span className="card-sub">{sub}</span>}
    </div>
  );
}

/* Inline SVG rather than a charting library, since it's one series of thirty
 * points, and a dependency would outweigh the chart. */
function Sparkline({ points }: { points: { day: string; plays: number }[] }) {
  if (points.length < 2) return <p className="muted">Not enough history yet.</p>;

  const width = 320;
  const height = 64;
  const max = Math.max(...points.map((p) => p.plays), 1);
  const step = width / (points.length - 1);
  const path = points
    .map((p, i) => `${i === 0 ? "M" : "L"} ${i * step} ${height - (p.plays / max) * height}`)
    .join(" ");

  return (
    <svg className="spark" viewBox={`0 0 ${width} ${height}`} preserveAspectRatio="none" role="img"
         aria-label={`Plays per day, peak ${max}`}>
      <path d={`${path} L ${width} ${height} L 0 ${height} Z`} className="spark-fill" />
      <path d={path} className="spark-line" />
    </svg>
  );
}
