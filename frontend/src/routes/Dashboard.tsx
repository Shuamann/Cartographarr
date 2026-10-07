import Loading from "../components/Loading";
import ServerWork from "../components/ServerWork";
import { displayTitle, episodeCode } from "../lib/titles";
import { useEffect, useMemo, useRef, useState } from "react";
import { useApi, type Activity, type Dashboard, type LiveSession } from "../lib/api";
import { runningPercent, useRunningOffset } from "../lib/playing";
import TravelFlags from "../components/TravelFlags";
import StreamDetail from "../components/StreamDetail";
import EnforcementLog from "../components/EnforcementLog";
import FilterBar from "../components/FilterBar";
import { toQuery, type FilterState } from "../lib/filters";
import { useNav } from "../lib/nav";
import type { Tab } from "../lib/tabs";

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
  onNavigate: (tab: Tab) => void;
  isAdmin?: boolean;
  onOpenUser?: (userId: number) => void;
  filters: FilterState;
  onFilters: (next: FilterState) => void;
}) {
  const nav = useNav();
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

  if (data.error) return <div className="pad"><p className="note bad-note" role="alert">{data.error}</p></div>;
  if (!data.data) return <div className="pad"><Loading /></div>;

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

      {live.error && <p className="note bad-note" role="alert">{live.error}</p>}
      {/* Why things might be slow this minute, which nothing could say
          before: a scan reads off the same disks a stream comes from. Shown
          only while something is running. */}
      {isAdmin && <ServerWork />}
      {/* The strip below redraws itself every few seconds and announced
          nothing. One polite line, so a stream starting or stopping is heard
          without reading the whole strip again. */}
      <p className="spoken" role="status">
        {live.stream_count
          ? `${live.stream_count} ${live.stream_count === 1 ? "stream" : "streams"} playing now`
          : "Nothing streaming right now"}
      </p>

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
          sub={
            d.totals.sessions !== d.totals.plays
              ? `${d.totals.sessions.toLocaleString()} sessions`
              : d.filtered
                ? "matching filters"
                : "all time"
          }
          onClick={() => onNavigate("Map")}
        />
        <Card
          big={d.totals.users}
          label="users"
          sub={`${d.totals.devices} devices`}
          onClick={() => nav.openPeople?.()}
        />
        <Card
          big={d.totals.hosting_ips}
          label="VPN origins"
          sub={`of ${d.totals.ip_locations} addresses`}
          vpn={d.totals.hosting_ips > 0}
          onClick={() => nav.filterTo?.("Map", { is_hosting: true })}
        />
        <Card
          big={d.totals.new_devices}
          label="new devices"
          sub="not yet reviewed"
          warn={d.totals.new_devices > 0}
          onClick={() => nav.openPeople?.("new")}
        />
        <Card
          big={d.totals.travel_flags}
          label="sharing signals"
          sub="unreviewed"
          onClick={() => document.getElementById("signals")?.scrollIntoView({ behavior: "smooth", block: "start" })}
          warn={d.totals.travel_flags > 0}
        />
      </section>

      {isAdmin && <HealthCards onNavigate={onNavigate} />}

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

      <div id="signals">
        <TravelFlags isAdmin={Boolean(isAdmin)} onOpenUser={onOpenUser} />
      </div>

      <section>
        <div className="row-between">
          <h2 className="section-head">Recent stream actions</h2>
          {isAdmin && (
            <button className="tab" onClick={() => onNavigate("Log")}>
              Full log
            </button>
          )}
        </div>
        {d.settings.dry_run_locked ? (
          <p className="muted small">ENFORCE_DRY_RUN is set, so every rule records only.</p>
        ) : d.settings.record_only_rules > 0 ? (
          <p className="muted small">
            {d.settings.record_only_rules} of {d.settings.enabled_rules} rules record only and do not act.
          </p>
        ) : null}
        <EnforcementLog entries={d.recent_enforcement} onOpenUser={onOpenUser} />
      </section>
      </div>
    </div>
  );
}

/* What to show before the strip has been measured, and the least it will
   ever show. The real number comes from the grid itself. */
const VISIBLE = 4;

/* How many columns the strip actually drew.
 *
 * The CSS fills the row by itself, so asking the browser what it did beats
 * keeping the card width in two places and watching them drift. It answers
 * with one length per column, so counting them is the whole measurement. */
function useColumns(ref: React.RefObject<HTMLDivElement | null>, fallback: number) {
  const [columns, setColumns] = useState(fallback);
  useEffect(() => {
    const el = ref.current;
    if (!el || typeof ResizeObserver === "undefined") return;
    const measure = () => {
      const drawn = getComputedStyle(el).gridTemplateColumns.split(" ").filter(Boolean).length;
      setColumns(Math.max(1, drawn));
    };
    measure();
    const watch = new ResizeObserver(measure);
    watch.observe(el);
    return () => watch.disconnect();
  }, [ref]);
  return columns;
}

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
  const strip = useRef<HTMLDivElement>(null);
  const columns = useColumns(strip, VISIBLE);

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

  /* One full row, whatever the screen is.
   *
   * The "and N more" tile takes a slot of its own, so when something has to be
   * hidden there is room for one fewer card. When everything fits there is no
   * tile and no reason to hold a card back. */
  const perRow = columns;
  const fits = sessions.length <= perRow ? perRow : Math.max(1, perRow - 1);
  const shown = expanded ? sessions : sessions.slice(0, fits);
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
          {hidden > 0 || expanded ? (
            <button className="tab" onClick={() => setExpanded(!expanded)}>
              {expanded ? "Show fewer" : `Show all ${sessions.length}`}
            </button>
          ) : null}
        </div>
      </div>

      <div className="stream-strip" ref={strip}>
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

/* What a glance should answer: who, on what, how far in, playing or paused,
 * whether the server is working to send it, at what quality and what cost. */
/* The title on a tile, in the parts that go somewhere: the show, the season,
   the episode with its name, or for a film just the film. */
function CardTitle({ session }: { session: LiveSession }) {
  const nav = useNav();
  const code = episodeCode(session);
  const show = session.grandparent_rating_key ? Number(session.grandparent_rating_key) : null;
  const season = session.parent_media_index == null ? null : Number(session.parent_media_index);
  const key = session.rating_key ? Number(session.rating_key) : null;
  const stop = (e: React.MouseEvent) => e.stopPropagation();

  if (!nav.openLibrary) return <>{displayTitle(session)}</>;
  if (!code || !show || !/^S\d+E\d+$/.test(code)) {
    return (
      <button
        className="linkish title-link"
        onClick={(e) => {
          stop(e);
          nav.openLibrary?.({ ratingKey: key, mediaType: session.media_type ?? "movie" });
        }}
      >
        {displayTitle(session)}
      </button>
    );
  }
  const at = code.indexOf("E");
  return (
    <>
      {/* The show gives way first and the numbers never do: "The Chosen -
          S01 - ..." tells you less than the thing it cut off. */}
      <button
        className="linkish title-link card-title-show"
        onClick={(e) => {
          stop(e);
          nav.openLibrary?.({ show, title: session.grandparent_title });
        }}
      >
        {session.grandparent_title}
      </button>
      <span className="muted card-title-sep">-</span>
      <button
        className="linkish title-link card-title-code"
        onClick={(e) => {
          stop(e);
          nav.openLibrary?.({ show, season, title: session.grandparent_title });
        }}
      >
        {code.slice(0, at)}
      </button>
      <span className="muted card-title-sep">-</span>
      <button
        className="linkish title-link card-title-code"
        onClick={(e) => {
          stop(e);
          nav.openLibrary?.({ show, season, ratingKey: key, title: session.grandparent_title });
        }}
      >
        {code.slice(at)}
      </button>
      {session.title ? (
        <button
          className="linkish title-link card-title-name"
          onClick={(e) => {
            stop(e);
            nav.openLibrary?.({ show, season, ratingKey: key, title: session.grandparent_title });
          }}
        >
          {` · ${session.title}`}
        </button>
      ) : null}
    </>
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
  const nav = useNav();
  const who = session.friendly_name || session.username || "Unknown";
  const paused = (session.state || "").toLowerCase() === "paused";
  const transcoding = session.transcode_decision === "transcode";
  const quality = session.stream_video_full_resolution || session.video_full_resolution;
  const rate = Number(session.stream_bitrate || session.bandwidth || 0);
  const total = Number(session.duration ?? 0);
  // Runs on between polls. Stops dead when the stream is not playing, which
  // is the half that keeps it honest: a paused stream whose timer climbed
  // would be a lie told smoothly.
  const offset = useRunningOffset(
    Number(session.view_offset ?? 0),
    (session.state || "").toLowerCase() === "playing",
    total,
  );
  const progress = runningPercent(offset, total) || Math.min(Math.max(Number(session.progress_percent ?? 0), 0), 100);
  // Where they were when this stream started, recorded at the time. A stream
  // first seen at the beginning says so; anything else says where they resumed.
  const from = session.started_percent;
  const resumed = from != null && from >= 2 ? from : null;

  return (
    /* A div rather than a button, because the things inside it are buttons and
       a button inside a button is not valid and does not behave. It keeps the
       keyboard behaviour a button would have had. */
    <div
      className={selected ? "stream-card on" : "stream-card"}
      role="button"
      tabIndex={0}
      onClick={onClick}
      onKeyDown={(e) => {
        if (e.key === "Enter" || e.key === " ") {
          e.preventDefault();
          onClick();
        }
      }}
    >
      {/* The same blurred show as the opened card, so the strip and the panel
          below it look like the same thing. Decoration only. */}
      {session.rating_key ? (
        <span
          className="stream-backdrop"
          aria-hidden="true"
          style={{ backgroundImage: `url(/api/media/${session.rating_key}/image?kind=art&width=600&height=338)` }}
        />
      ) : null}
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
        {/* Every part of this names something that can be opened: the show,
            the season, the episode, the person and the device. */}
        <strong className="card-title">
          <CardTitle session={session} />
        </strong>
        <span className="muted small clip">
          {session.user_id != null && nav.openUser ? (
            <button
              className="linkish title-link"
              onClick={(e) => {
                e.stopPropagation();
                nav.openUser?.(session.user_id as number);
              }}
            >
              {who}
            </button>
          ) : (
            who
          )}
        </span>
        <span className="muted small clip">
          {session.machine_id && nav.openDevice ? (
            <button
              className="linkish title-link"
              onClick={(e) => {
                e.stopPropagation();
                nav.openDevice?.(session.machine_id as string);
              }}
            >
              {session.player}
            </button>
          ) : (
            session.player
          )}
          {session.geo?.is_hosting && <span className="pill vpn">VPN</span>}
        </span>
        <span className="stream-facts">
          <span className={paused ? "pill" : "pill ok"}>{paused ? "paused" : "playing"}</span>
          <span className={transcoding ? "pill warn" : "pill"}>{transcoding ? "transcode" : "direct"}</span>
          {quality && <span className="muted small">{quality}</span>}
          {rate > 0 && <span className="muted small">{(rate / 1000).toFixed(1)} Mbps</span>}
        </span>
        <span className="stream-times muted small">
          <span>
            {total > 0 ? `${clock(offset)} / ${clock(total)}` : `${Math.round(progress)}%`}
          </span>
          {from != null && (
            <span title="Where this stream was when Cartographarr first saw it">
              {resumed ? `started at ${Math.round(resumed)}%` : "from the start"}
            </span>
          )}
        </span>
        <span className="progress" title={`${Math.round(progress)}% watched`}>
          <span className={paused ? "progress-fill paused" : "progress-fill"} style={{ width: `${progress}%` }} />
          {resumed != null && resumed < progress && (
            <span className="progress-mark" style={{ left: `${resumed}%` }} title={`Started watching at ${Math.round(resumed)}%`} />
          )}
        </span>
      </span>
    </div>
  );
}

/* 1:05:12, or 5:12 for anything under an hour. */
function clock(ms: number): string {
  const total = Math.max(0, Math.floor(ms / 1000));
  const h = Math.floor(total / 3600);
  const m = Math.floor((total % 3600) / 60);
  const s = String(total % 60).padStart(2, "0");
  return h ? `${h}:${String(m).padStart(2, "0")}:${s}` : `${m}:${s}`;
}

function Card({
  big,
  label,
  sub,
  onClick,
  accent,
  warn,
  vpn,
}: {
  big: number | string;
  label: string;
  sub?: string;
  onClick?: () => void;
  accent?: boolean;
  warn?: boolean;
  vpn?: boolean;
}) {
  const className = ["card", accent && typeof big === "number" && big > 0 ? "accent" : "", warn ? "warn" : "", vpn ? "vpn" : ""]
    .filter(Boolean)
    .join(" ");
  const body = (
    <>
      <span className="card-big">{typeof big === "number" ? big.toLocaleString() : big}</span>
      <span className="card-label">{label}</span>
      {sub && <span className="card-sub">{sub}</span>}
    </>
  );
  // A real button when it goes somewhere, so it can be reached and used from
  // the keyboard; a div with a click handler could not.
  return onClick ? (
    <button type="button" className={`${className} card-button`} onClick={onClick}>
      {body}
    </button>
  ) : (
    <div className={className}>{body}</div>
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

type Health = {
  stalls_week: number;
  top_stall_cause: string | null;
  peak_upload_mbps: number | null;
  upload_capacity_mbps: number | null;
  streams_week: number;
  transcoded_week: number;
  not_watching: number;
  people: number;
  idle_days: number;
};

/* Server health at a glance, from what is recorded live: stalls, upload,
 * transcoding, and who has stopped watching. Admins only. */
function HealthCards({ onNavigate }: { onNavigate: (tab: Tab) => void }) {
  const health = useApi<Health>("/library/health");
  const h = health.data;
  if (!h) return null;
  const share = h.streams_week ? Math.round((h.transcoded_week / h.streams_week) * 100) : null;
  const uploadShare =
    h.peak_upload_mbps !== null && h.upload_capacity_mbps ? Math.round((h.peak_upload_mbps / h.upload_capacity_mbps) * 100) : null;
  return (
    <section className="cards">
      <Card
        big={h.stalls_week}
        label={h.stalls_week === 1 ? "stall this week" : "stalls this week"}
        sub={h.top_stall_cause ? `mostly: ${h.top_stall_cause.toLowerCase()}` : "none recorded"}
        warn={h.stalls_week > 0}
        onClick={() => onNavigate("Reports")}
      />
      <Card
        big={h.peak_upload_mbps === null ? "none" : `${h.peak_upload_mbps} Mbps`}
        label="peak upload today"
        sub={
          uploadShare !== null
            ? `${uploadShare}% of ${h.upload_capacity_mbps} Mbps`
            : "set upload capacity in Settings"
        }
        warn={uploadShare !== null && uploadShare >= 90}
        onClick={() => onNavigate("Reports")}
      />
      <Card
        big={share === null ? "none" : `${share}%`}
        label="streams transcoded"
        sub={h.streams_week ? `${h.transcoded_week} of ${h.streams_week} this week` : "no streams recorded yet"}
        onClick={() => onNavigate("Library")}
      />
      <Card
        big={h.not_watching}
        label="not watching"
        sub={`of ${h.people}, no plays in ${h.idle_days} days`}
        onClick={() => onNavigate("Sharing")}
      />
    </section>
  );
}
