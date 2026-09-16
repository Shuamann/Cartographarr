import { useEffect, useMemo, useState } from "react";
import { useApi, type Activity, type Dashboard, type LiveSession } from "../lib/api";
import TravelFlags from "../components/TravelFlags";
import StreamDetail from "../components/StreamDetail";
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
  filters,
  onFilters,
}: {
  onNavigate: (tab: string) => void;
  isAdmin?: boolean;
  onOpenUser?: (userId: number) => void;
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
}: {
  sessions: LiveSession[];
  transcoding: number | null;
  onChanged: () => void;
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
        <StreamDetail session={current} onClose={() => setOpen(null)} onChanged={onChanged} />
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
