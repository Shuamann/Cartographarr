import { useEffect } from "react";
import { useApi, type Dashboard } from "../lib/api";

/* The landing screen.
 *
 * What goes here is still being worked out, so this reads from ONE endpoint
 * (/api/dashboard) that composes every source — local database, live Tautulli
 * activity, capabilities, and integrations once they exist. Rearranging the
 * layout, or adding a panel, doesn't mean touching the data path.
 */
export default function DashboardRoute({ onNavigate }: { onNavigate: (tab: string) => void }) {
  const data = useApi<Dashboard>("/dashboard");

  useEffect(() => {
    const timer = setInterval(data.reload, 15000);
    return () => clearInterval(timer);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  if (data.error) return <div className="pad"><p className="note bad-note">{data.error}</p></div>;
  if (!data.data) return <div className="pad muted">Loading…</div>;

  const d = data.data;
  const live = d.live;

  return (
    <div className="pad scroll dash">
      <div className="row-between">
        <h1>{d.capabilities.server.name ?? "Cartographarr"}</h1>
        <span className="muted small">
          Plex {d.capabilities.server.version}
          {d.capabilities.plex_pass.active === false && " · no Plex Pass"}
        </span>
      </div>

      {live.error && <p className="note bad-note">{live.error}</p>}

      <section className="cards">
        <Card
          big={live.stream_count}
          label={live.stream_count === 1 ? "stream now" : "streams now"}
          sub={live.transcode_count ? `${live.transcode_count} transcoding` : "all direct"}
          onClick={() => onNavigate("Activity")}
          accent
        />
        <Card big={d.totals.plays} label="plays" sub="all time" onClick={() => onNavigate("Map")} />
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
        />
      </section>

      {live.sessions.length > 0 && (
        <section>
          <h2 className="section-head">Playing now</h2>
          <div className="mini-list">
            {live.sessions.map((s) => (
              <div key={s.session_key} className="mini">
                <div>
                  <strong>{s.full_title}</strong>
                  <p className="muted small">
                    {s.friendly_name || s.username} · {s.player} · {s.transcode_decision}
                    {s.geo?.is_hosting && <span className="pill warn"> VPN</span>}
                  </p>
                </div>
                <span className="muted small">{Math.round(Number(s.progress_percent ?? 0))}%</span>
              </div>
            ))}
          </div>
        </section>
      )}

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

      <section>
        <div className="row-between">
          <h2 className="section-head">Recent rule activity</h2>
          <button className="tab" onClick={() => onNavigate("Rules")}>All rules</button>
        </div>
        {d.settings.enforce_dry_run && (
          <p className="muted small">Dry run is on — rules record but don't act.</p>
        )}
        {d.recent_enforcement.length === 0 ? (
          <p className="muted">Nothing yet.</p>
        ) : (
          <div className="mini-list">
            {d.recent_enforcement.map((e, i) => (
              <div key={i} className="mini">
                <div>
                  <strong>{e.rule_name}</strong>
                  <p className="muted small">
                    {e.username} · {e.player} · {e.full_title}
                  </p>
                </div>
                <span className={e.dry_run ? "pill" : "pill warn"}>{e.result}</span>
              </div>
            ))}
          </div>
        )}
      </section>
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

/* Inline SVG rather than a charting library — it's one series of thirty
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
