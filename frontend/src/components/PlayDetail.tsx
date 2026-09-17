import { displayTitle, episodeLabel } from "../lib/titles";
import { useState } from "react";
import { useApi, type MediaDetail } from "../lib/api";
import { useNav } from "../lib/nav";
import BrandIcon from "./BrandIcon";
import { when } from "./DataTable";

type Stream = {
  quality_profile?: string | null;
  container?: string | null;
  stream_container?: string | null;
  video_decision?: string | null;
  video_codec?: string | null;
  stream_video_codec?: string | null;
  video_full_resolution?: string | null;
  stream_video_full_resolution?: string | null;
  stream_video_dynamic_range?: string | null;
  audio_decision?: string | null;
  audio_codec?: string | null;
  stream_audio_codec?: string | null;
  audio_channels?: string | number | null;
  stream_audio_channels?: string | number | null;
  audio_language?: string | null;
  bitrate?: number | null;
  stream_bitrate?: number | null;
  subtitle_decision?: string | null;
  stream_subtitle_decision?: string | null;
  subtitle_language?: string | null;
  transcode_hw_decoding?: number | null;
  transcode_hw_encoding?: number | null;
};

type Play = {
  row_id: number;
  user_id: number | null;
  user_name: string | null;
  machine_id: string | null;
  ip_address: string | null;
  started: number | null;
  stopped: number | null;
  play_duration: number | null;
  paused_counter: number | null;
  percent_complete: number | null;
  watched_status: number | null;
  media_type: string | null;
  section_id: number | null;
  library_name: string | null;
  rating_key: number | null;
  grandparent_rating_key: number | null;
  full_title: string | null;
  year: number | null;
  player: string | null;
  platform: string | null;
  product: string | null;
  transcode_decision: string | null;
  location: string | null;
  secure: boolean | null;
  relayed: boolean | null;
  device_banned: boolean;
  place: {
    city: string | null;
    region: string | null;
    country: string | null;
    accuracy_km: number | null;
    asn_org: string | null;
    is_hosting: boolean | null;
    is_private: boolean | null;
  } | null;
  stream: Stream | null;
  stream_error?: string;
};

const LINKS: { key: string; label: string }[] = [
  { key: "plex", label: "Plex" },
  { key: "imdb", label: "IMDb" },
  { key: "tmdb", label: "TMDB" },
  { key: "trakt", label: "Trakt" },
  { key: "radarr", label: "Radarr" },
  { key: "sonarr", label: "Sonarr" },
  { key: "seerr", label: "Seerr" },
];

/* One play from history, opened in place.
 *
 * Every value goes somewhere: the user and the device open in People, the
 * address opens its page, the place and the title narrow the map or the
 * history to that place or title, and the links go out to Plex and the rest.
 */
export default function PlayDetail({ rowId }: { rowId: number }) {
  const nav = useNav();
  const detail = useApi<Play>(`/history/${rowId}`);
  const [copied, setCopied] = useState(false);
  const p = detail.data;
  const media = useApi<MediaDetail>(p?.rating_key ? `/media/${p.rating_key}` : null, [p?.rating_key]);

  if (detail.error) return <p className="note bad-note">{detail.error}</p>;
  if (!p) return <p className="muted small">Loading…</p>;

  const s = p.stream ?? {};
  const links = media.data ? LINKS.filter((l) => media.data?.links[l.key]) : [];
  const where = p.place ? [p.place.city, p.place.region, p.place.country].filter(Boolean).join(", ") : "";
  const paused = p.paused_counter ?? 0;

  async function copy() {
    if (!p?.machine_id) return;
    await navigator.clipboard?.writeText(p.machine_id).catch(() => {});
    setCopied(true);
    setTimeout(() => setCopied(false), 1500);
  }

  return (
    <div className="log-detail play-detail">
      {p.rating_key ? (
        <img
          className="log-poster"
          src={`/api/media/${p.rating_key}/image?width=200&height=300`}
          alt=""
          onError={(e) => ((e.currentTarget as HTMLImageElement).style.display = "none")}
        />
      ) : null}

      <div className="min0">
        {media.data?.summary && <p className="stream-summary clamp">{media.data.summary}</p>}
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
            {displayTitle(p)}
            {p.year ? ` (${p.year})` : ""}
            {episodeLabel(p) && <span className="muted small block">{episodeLabel(p)}</span>}
            {p.rating_key && nav.filterTo && (
              <button
                className="linkish small"
                onClick={() =>
                  nav.filterTo?.("History", {
                    rating_key: p.grandparent_rating_key ?? p.rating_key,
                    ratingKeyLabel: (p.full_title ?? "").split(" - ")[0],
                  })
                }
              >
                all plays of this
              </button>
            )}
          </Field>
          <Field label="Library">
            {p.library_name && p.section_id != null && nav.filterTo ? (
              <button className="linkish" onClick={() => nav.filterTo?.("History", { section_id: [p.section_id as number] })}>
                {p.library_name}
              </button>
            ) : (
              p.library_name
            )}
            {p.media_type && <span className="pill">{p.media_type}</span>}
          </Field>
          <Field label="Who">
            {p.user_id != null && nav.openUser ? (
              <button className="linkish" onClick={() => nav.openUser?.(p.user_id as number)}>
                {p.user_name ?? p.user_id}
              </button>
            ) : (
              p.user_name
            )}
          </Field>
          <Field label="Device">
            {p.machine_id && nav.openDevice ? (
              <button className="linkish" onClick={() => nav.openDevice?.(p.machine_id as string)}>
                {[p.player, p.platform].filter(Boolean).join(" · ") || "Unknown"}
              </button>
            ) : (
              [p.player, p.platform].filter(Boolean).join(" · ") || null
            )}
            {p.device_banned && <span className="pill banned">banned</span>}
          </Field>
          <Field label="App">{p.product}</Field>
          <Field label="Device id">
            {p.machine_id ? (
              <button className="idbtn" onClick={copy} title="Copy">
                <code className="small">{p.machine_id}</code>
                <span className="muted small">{copied ? "copied" : "copy"}</span>
              </button>
            ) : null}
          </Field>
          <Field label="Where">
            {where && nav.filterTo && p.ip_address ? (
              <button
                className="linkish"
                title="Show plays from this address on the map"
                onClick={() => nav.filterTo?.("Map", { ip_address: [p.ip_address as string] })}
              >
                {where}
              </button>
            ) : (
              where || null
            )}
            {p.place?.accuracy_km ? <span className="muted small">±{p.place.accuracy_km} km</span> : null}
            {p.location && <span className="pill">{p.location.toUpperCase()}</span>}
          </Field>
          <Field label="Address">
            {p.ip_address && nav.openAddress ? (
              <button className="linkish" onClick={() => nav.openAddress?.(p.ip_address as string)}>
                <code>{p.ip_address}</code>
              </button>
            ) : (
              p.ip_address
            )}
            {p.place?.is_hosting && <span className="pill vpn">VPN</span>}
          </Field>
          <Field label="Network">
            {[p.place?.asn_org, p.relayed ? "relayed" : null, p.secure === false ? "not secure" : p.secure ? "secure" : null]
              .filter(Boolean)
              .join(" · ") || null}
          </Field>
          <Field label="When">
            {p.started ? when(p.started) : null}
            {p.stopped ? ` to ${sameDay(p.started, p.stopped) ? new Date(p.stopped * 1000).toLocaleTimeString() : when(p.stopped)}` : ""}
          </Field>
          <Field label="Watched">
            {p.play_duration != null ? clock(p.play_duration) : null}
            {paused > 60 ? <span className="muted small">paused {clock(paused)}</span> : null}
            {p.watched_status ? <span className="pill ok">finished</span> : null}
          </Field>
          <Field label="Quality">
            {[s.quality_profile, s.stream_bitrate ? `${(s.stream_bitrate / 1000).toFixed(1)} Mbps` : null].filter(Boolean).join(" · ") ||
              null}
          </Field>
          <Field label="Stream">{decision(p.transcode_decision)}</Field>
          <Field label="Container">{arrow(s.container, s.stream_container)}</Field>
          <Field label="Video">
            {s.video_decision
              ? `${decision(s.video_decision)} · ${arrow(fmt(s.video_codec, s.video_full_resolution), fmt(s.stream_video_codec, s.stream_video_full_resolution))}`
              : null}
            {s.stream_video_dynamic_range && s.stream_video_dynamic_range !== "SDR" && (
              <span className="pill">{s.stream_video_dynamic_range}</span>
            )}
            {(s.transcode_hw_decoding || s.transcode_hw_encoding) ? <span className="pill">hardware</span> : null}
          </Field>
          <Field label="Audio">
            {s.audio_decision
              ? `${decision(s.audio_decision)} · ${arrow(fmt(s.audio_codec, channels(s.audio_channels)), fmt(s.stream_audio_codec, channels(s.stream_audio_channels)))}`
              : null}
            {s.audio_language && <span className="muted small">{s.audio_language}</span>}
          </Field>
          <Field label="Subtitles">
            {s.stream_subtitle_decision || s.subtitle_decision
              ? `${decision(s.stream_subtitle_decision || s.subtitle_decision)}${s.subtitle_language ? ` · ${s.subtitle_language}` : ""}`
              : "None"}
          </Field>
        </dl>

        {p.percent_complete != null && (
          <div className="log-progress">
            <div className="progress">
              <div className="progress-fill" style={{ width: `${Math.min(p.percent_complete, 100)}%` }} />
            </div>
            <span className="muted small">{p.percent_complete}% through</span>
          </div>
        )}
        {p.stream_error && <p className="muted small">Stream details unavailable: {p.stream_error}</p>}
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

function decision(value: string | null | undefined): string {
  if (!value) return "Unknown";
  if (value === "copy") return "Direct stream";
  if (value === "direct play") return "Direct play";
  return value.charAt(0).toUpperCase() + value.slice(1);
}

function fmt(codec: string | null | undefined, extra: string | null | undefined): string {
  return [codec?.toUpperCase(), extra].filter(Boolean).join(" ");
}

function arrow(source: string | null | undefined, stream: string | null | undefined): string | null {
  const a = (source || "").toString().toUpperCase();
  const b = (stream || "").toString().toUpperCase();
  if (!a && !b) return null;
  return b && a !== b ? `${a || "?"} → ${b}` : a || b;
}

function channels(n: string | number | null | undefined): string | null {
  const c = Number(n);
  if (!c) return null;
  return c === 6 ? "5.1" : c === 8 ? "7.1" : c === 2 ? "stereo" : `${c} ch`;
}

function clock(seconds: number): string {
  const h = Math.floor(seconds / 3600);
  const m = Math.floor((seconds % 3600) / 60);
  return h ? `${h}h ${m}m` : `${m}m`;
}

function sameDay(a: number | null, b: number | null): boolean {
  if (!a || !b) return false;
  return new Date(a * 1000).toDateString() === new Date(b * 1000).toDateString();
}
