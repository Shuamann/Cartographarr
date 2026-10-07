import { episodeCode } from "../lib/titles";
import { useState } from "react";
import BrandIcon from "./BrandIcon";
import Fact from "./Fact";
import { api, useApi, type LiveSession, type MediaDetail } from "../lib/api";
import { runningPercent, useRunningOffset } from "../lib/playing";
import { useNav } from "../lib/nav";
import { coveredBy, useAddressBans, useBans } from "../lib/bans";
import { useIsAvailable } from "./Gated";

/* Everything about one live stream, and everything you can do to it.
 *
 * The one place a stream is described. The dashboard shows it wide under the
 * Now playing strip, the map shows it compact in the pin's popup, and both get
 * the same facts, links and actions, because both render this.
 */

export const LINKS: { key: string; label: string }[] = [
  { key: "plex", label: "Plex" },
  { key: "imdb", label: "IMDb" },
  { key: "tmdb", label: "TMDB" },
  { key: "trakt", label: "Trakt" },
  { key: "radarr", label: "Radarr" },
  { key: "sonarr", label: "Sonarr" },
  { key: "seerr", label: "Seerr" },
];

/* What kind of thing is playing this.
 *
 * A category rather than a brand: a television, a phone, a desktop, a console
 * or a browser. The shape is the useful part at this size, and it means no
 * logos to keep current or to have opinions about.
 */
const PLATFORM_SHAPES: Record<string, string> = {
  tv: "M3 5h18v11H3zm5 14h8v-1H8z",
  mobile: "M7 2h10v20H7zm4 18h2v1h-2z",
  desktop: "M3 4h18v11H3zm2 14h14v2H5z",
  console: "M6 9h12a4 4 0 0 1 0 8H6a4 4 0 0 1 0-8zm1 2v4m-2-2h4",
  browser: "M12 2a10 10 0 1 0 0 20 10 10 0 0 0 0-20zm0 2c4 0 6 8 0 8s-4-8 0-8z",
};

export function platformKind(platform: string | null | undefined, product: string | null | undefined): string {
  const text = `${platform ?? ""} ${product ?? ""}`.toLowerCase();
  if (/playstation|xbox|nintendo|ps4|ps5/.test(text)) return "console";
  if (/roku|tizen|webos|tvos|apple tv|android tv|shield|chromecast|smart ?tv|fire ?tv/.test(text)) return "tv";
  if (/android|ios|iphone|ipad|phone|tablet/.test(text)) return "mobile";
  if (/chrome|firefox|safari|edge|opera|browser|web/.test(text)) return "browser";
  return "desktop";
}

function PlatformIcon({ platform, product }: { platform?: string | null; product?: string | null }) {
  const kind = platformKind(platform, product);
  const d = PLATFORM_SHAPES[kind];
  if (!d) return null;
  return (
    <svg className="platform-icon" width={15} height={15} viewBox="0 0 24 24" aria-label={kind} role="img">
      <path d={d} fill="none" stroke="currentColor" strokeWidth="1.6" strokeLinejoin="round" />
    </svg>
  );
}

/* S01 and E06 are one word on screen and two places in the library. */
function EpisodeLinks({ session }: { session: LiveSession }) {
  const nav = useNav();
  const code = episodeCode(session) ?? session.parent_title ?? null;
  const show = session.grandparent_rating_key ? Number(session.grandparent_rating_key) : null;
  const season = session.parent_media_index == null ? null : Number(session.parent_media_index);
  const name = session.title ?? null;

  if (!nav.openLibrary || !code || !show || !/^S\d+E\d+$/.test(code)) {
    return <>{[code, name].filter(Boolean).join(" · ")}</>;
  }
  const at = code.indexOf("E");
  return (
    <>
      <button
        className="linkish title-link"
        title={`Open season ${season}`}
        onClick={() => nav.openLibrary?.({ show, season, title: session.grandparent_title })}
      >
        {code.slice(0, at)}
      </button>
      <span className="muted card-title-sep">-</span>
      {/* The episode's name is part of its own link, because a two character
          target is a poor one and the name is the thing being pointed at. */}
      <button
        className="linkish title-link"
        title="Open this episode"
        onClick={() =>
          nav.openLibrary?.({
            show,
            season,
            ratingKey: session.rating_key ? Number(session.rating_key) : null,
            title: session.grandparent_title,
          })
        }
      >
        {code.slice(at)}
        {name ? ` · ${name}` : ""}
      </button>
    </>
  );
}

export default function StreamDetail({
  session,
  onClose,
  onChanged,
  compact = false,
  onMap = false,
}: {
  session: LiveSession;
  onClose?: () => void;
  onChanged?: () => void;
  /* Narrow layout for the map popup. */
  compact?: boolean;
  /* Already on the map, so no button to go there. */
  onMap?: boolean;
}) {
  const nav = useNav();
  const bans = useBans();
  const addressBans = useAddressBans();
  // A range counts: an address can be stopped without being on the list.
  const covering = session.ip_address ? coveredBy(session.ip_address as string, addressBans.list) : null;
  const banned = Boolean(session.machine_id && bans.ids.has(session.machine_id));
  const [stopping, setStopping] = useState(false);
  const [fullSummary, setFullSummary] = useState(false);

  // Links out (Plex, IMDb, Radarr and the rest) come from the same endpoint the
  // location drawer uses, so a title has the same buttons wherever it appears.
  const media = useApi<MediaDetail>(session.rating_key ? `/media/${session.rating_key}` : null, [
    session.rating_key,
  ]);
  const links = media.data ? LINKS.filter((l) => media.data?.links[l.key]) : [];

  const who = session.friendly_name || session.username || "Unknown";
  const where = session.geo
    ? [session.geo.city, session.geo.region, session.geo.country].filter(Boolean).join(", ")
    : null;
  const duration = Number(session.duration ?? 0);
  // Runs on between polls rather than sitting still and then jumping. The
  // percentage is worked out from the same number as the clock, so the bar
  // and the time cannot disagree.
  const offset = useRunningOffset(
    Number(session.view_offset ?? 0),
    (session.state || "").toLowerCase() === "playing",
    duration,
  );
  const progress = Math.round(runningPercent(offset, duration) || Math.min(Number(session.progress_percent ?? 0), 100));

  // An episode reads as the show on top and the episode beneath, which is how
  // everyone looks for it, rather than one long "Show - Episode" string.
  const episodic = session.media_type === "episode";
  const heading = (episodic ? session.grandparent_title : session.title) || session.full_title;
  const subheading = episodic
    ? [episodeCode(session) ?? session.parent_title, session.title].filter(Boolean).join(" · ")
    : null;

  const canMap = !onMap && nav.showOnMap && session.geo?.lat != null;

  return (
    <article className={compact ? "stream-detail compact" : "stream-detail"}>
      {/* The show, blurred, behind its own card. Decoration: everything on top
          of it sits on a scrim so the text keeps its contrast whatever the
          picture is. Falls back to the poster where there is no wide art, and
          to nothing at all where there is neither. */}
      {session.rating_key ? (
        <div
          className="stream-backdrop"
          aria-hidden="true"
          style={{ backgroundImage: `url(/api/media/${session.rating_key}/image?kind=art&width=900&height=506)` }}
        />
      ) : null}
      {onClose && (
        <button className="icon-btn stream-close" onClick={onClose} aria-label="Close">
          &times;
        </button>
      )}

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
          {/* The show on top and the episode beneath, each part going where it
              names: the show, that season, that episode. */}
          <h3>
            {nav.openLibrary && episodic && session.grandparent_rating_key ? (
              <button
                className="linkish title-link"
                title={`Open ${heading} in the library`}
                onClick={() =>
                  nav.openLibrary?.({ show: Number(session.grandparent_rating_key), title: heading })
                }
              >
                {heading}
              </button>
            ) : nav.openLibrary && !episodic && session.rating_key ? (
              <button
                className="linkish title-link"
                title="Find this in the library"
                onClick={() => nav.openLibrary?.({ ratingKey: Number(session.rating_key), mediaType: "movie" })}
              >
                {heading}
              </button>
            ) : (
              heading
            )}
          </h3>
          {subheading && (
            <p className="stream-sub">
              <EpisodeLinks session={session} />
            </p>
          )}
          <p className="muted small">
            {[session.year, session.content_rating, session.library_name].filter(Boolean).join(" · ")}
          </p>
          {media.data?.request?.requested_by && (
            <p className="muted small">Requested by {media.data.request.requested_by}</p>
          )}

          {session.summary && (
            <p
              className={fullSummary ? "stream-summary" : "stream-summary clamp"}
              onClick={() => setFullSummary((v) => !v)}
              title={fullSummary ? "Show less" : "Show more"}
            >
              {session.summary}
            </p>
          )}

          {links.length > 0 && (
            <div className="row wrap linkrow">
              {links.map((l) => (
                <a
                  key={l.key}
                  className="ms-btn"
                  href={media.data?.links[l.key]}
                  target="_blank"
                  rel="noreferrer"
                >
                  <BrandIcon name={l.key} />
                  {l.label}
                </a>
              ))}
            </div>
          )}
        </div>
      </div>

      {/* User, player and address first: they are the three things on this
          card that go somewhere, so they are together and at the top rather
          than scattered through the technical detail. */}
      <dl className="spec">
        <Spec label="User">
          <Jump onClick={session.user_id != null && nav.openUser ? () => nav.openUser?.(session.user_id as number) : undefined}>
            {who}
          </Jump>
        </Spec>
        <Spec label="Player">
          {banned && <span className="pill banned">banned</span>}
          <PlatformIcon platform={session.platform} product={session.product} />
          <Jump
            onClick={session.machine_id && nav.openDevice ? () => nav.openDevice?.(session.machine_id as string) : undefined}
            title="Open this device"
          >
            {session.player}
            {session.platform ? ` (${session.platform})` : ""}
          </Jump>
        </Spec>
        <Spec label="Location">
          <span className="pill">{(session.location || "").toUpperCase() || "?"}</span>
          {/* The address opens the address. It used to open the map, which
              is its own button at the foot of this card. */}
          <Jump
            onClick={
              session.ip_address && nav.openAddress
                ? () => nav.openAddress?.(session.ip_address as string)
                : undefined
            }
            title="Open this address"
          >
            {[session.ip_address, where].filter(Boolean).join(" · ")}
          </Jump>
          {session.geo?.is_hosting && <span className="pill vpn">VPN</span>}
        </Spec>
        <Spec label="Product">{session.product}</Spec>
        <Spec label="Quality">
          {session.quality_profile}
          {session.stream_bitrate ? ` · ${mbps(session.stream_bitrate)}` : ""}
        </Spec>
        <Spec label="Stream">{decision(session.transcode_decision)}</Spec>
        <Spec label="Container">
          {arrow(session.container, session.stream_container, session.transcode_decision)}
        </Spec>
        <Spec label="Video">
          {decision(session.video_decision)}
          {" · "}
          {arrow(
            fmt(session.video_codec, session.video_full_resolution),
            fmt(session.stream_video_codec, session.stream_video_full_resolution),
            session.video_decision,
          )}
        </Spec>
        <Spec label="Audio">
          {decision(session.audio_decision)}
          {" · "}
          {arrow(
            fmt(session.audio_codec, session.audio_channel_layout),
            fmt(session.stream_audio_codec, session.audio_channel_layout),
            session.audio_decision,
          )}
        </Spec>
        {session.subtitle_decision && <Spec label="Subtitles">{decision(session.subtitle_decision)}</Spec>}
        <Spec label="Network">
          {session.geo?.asn_org ?? "Unknown"}
          {session.relayed && Number(session.relayed) ? " · relayed" : ""}
          {session.secure !== null && session.secure !== undefined
            ? Number(session.secure)
              ? " · secure"
              : " · not secure"
            : ""}
        </Spec>
        <Spec label="Bandwidth">{session.bandwidth ? mbps(session.bandwidth) : null}</Spec>
      </dl>

      <div className="stream-progress">
        <div className="progress">
          <div className="progress-fill" style={{ width: `${progress}%` }} />
        </div>
        <div className="row-between small">
          <span>
            <span className={session.state === "playing" ? "pill ok" : "pill"}>{session.state ?? "unknown"}</span>{" "}
            {duration ? `${clock(offset)} / ${clock(duration)}` : `${progress}%`}
          </span>
          <span className="muted">
            {duration ? `${clock(Math.max(duration - offset, 0))} left · ${progress}%` : ""}
          </span>
        </div>
      </div>

      {/* Looking sits apart on the left, acting on someone's stream on the right. */}
      <div className="stream-actions">
        {canMap ? (
          <button className="btn" onClick={() => nav.showOnMap?.(session)}>
            Show on map
          </button>
        ) : (
          <span />
        )}
        {nav.isAdmin && (
          <div className="row">
            <button className="btn" onClick={() => setStopping((v) => !v)}>
              {stopping ? "Cancel" : "Stop stream"}
            </button>
            {nav.blockDevice && session.machine_id && !banned && (
              <button
                className="btn danger"
                onClick={() =>
                  nav.blockDevice?.(
                    session.machine_id as string,
                    session.player || (session.machine_id as string).slice(0, 8),
                  )
                }
              >
                Ban device
              </button>
            )}
            {nav.unbanDevice && session.machine_id && banned && (
              <button
                className="btn"
                onClick={() =>
                  nav.unbanDevice?.(
                    session.machine_id as string,
                    session.player || (session.machine_id as string).slice(0, 8),
                  )
                }
              >
                Unban device
              </button>
            )}
            {/* The connection rather than the box, for a device that comes
                back under a new identifier. */}
            {nav.blockAddress && session.ip_address && !covering && (
              <button
                className="btn danger"
                onClick={() => nav.blockAddress?.(session.ip_address as string, session.ip_address as string)}
              >
                Ban address
              </button>
            )}
            {nav.unbanAddress && covering && (
              <button className="btn" onClick={() => nav.unbanAddress?.(covering)}>
                {covering === session.ip_address ? "Unban address" : `Unban ${covering}`}
              </button>
            )}
          </div>
        )}
      </div>

      {stopping && (
        <StopForm
          session={session}
          onDone={() => {
            setStopping(false);
            onChanged?.();
          }}
        />
      )}
    </article>
  );
}

/* A value that goes somewhere when there is somewhere to go, and plain text
 * when there is not. */
function Jump({
  onClick,
  title,
  children,
}: {
  onClick?: () => void;
  title?: string;
  children: React.ReactNode;
}) {
  if (!onClick) return <>{children}</>;
  return (
    <button className="linkish" onClick={onClick} title={title}>
      {children}
    </button>
  );
}

/* A label and its value, in one cell.
 *
 * They used to be loose dt and dd elements sharing the grid's columns, so a
 * long value wrapped inside its column while the short ones left a gap and the
 * block went ragged. Wrapping the pair lets the cells flow instead: a long one
 * takes the room it needs and nothing breaks in the middle. A div between dl
 * and its dt is allowed, and screen readers still read the pairs. */
const Spec = Fact;

function decision(value: string | null | undefined): string {
  if (!value) return "Unknown";
  if (value === "copy") return "Direct stream";
  if (value === "direct play") return "Direct play";
  return value.charAt(0).toUpperCase() + value.slice(1);
}

function fmt(codec: string | null | undefined, extra: string | null | undefined): string {
  return [codec?.toUpperCase(), extra].filter(Boolean).join(" ");
}

/* "H264 1080 to HEVC 720" when it is being converted, just the source when not. */
function arrow(source: string | null | undefined, stream: string | null | undefined, how: string | null | undefined) {
  const src = (source || "").toString();
  const out = (stream || "").toString();
  if (how === "transcode" && out && out.toLowerCase() !== src.toLowerCase()) {
    return `${src.toUpperCase() || "?"} → ${out.toUpperCase()}`;
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
          <span className="fixed">Your Plex account name asked to stop your playback from this server: </span>
          <span className="ours">{message}</span>
          <span className="fixed"> {session.session_key}</span>
        </p>
        <small className="muted">
          Only the highlighted part is editable. Plex adds the rest and it cannot be changed.
        </small>
      </div>

      {error && <p className="note bad-note" role="alert">{error}</p>}

      <div className="row">
        <button className="btn danger" onClick={stop} disabled={busy || !plexPass.ok}>
          {busy ? "Stopping…" : `Stop ${session.friendly_name || session.username}'s stream`}
        </button>
        {!plexPass.ok && <span className="muted small">{plexPass.reason}</span>}
      </div>
    </div>
  );
}
