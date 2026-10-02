import { useEffect, useRef, useState, type ReactNode } from "react";
import { when } from "../components/DataTable";
import Loading from "../components/Loading";
import MediaPanel from "../components/MediaPanel";
import { api, useApi } from "../lib/api";
import { useNav } from "../lib/nav";

/* Library health: files judged by how they are actually watched.
 *
 * Every list shares one row: the title and why it is listed, opening to the
 * file itself (format, every track, where it lives) and how it has played,
 * with a jump to its plays in History.
 */

type Track = { codec: string | null; channels?: number | null; language: string | null; bitrate?: number | null; forced?: boolean; location?: string | null };

type Finding = {
  key: string;
  severity: "high" | "medium" | "low";
  title: string;
  detail: string;
  fix: string;
  arr: string | null;
};

type FileInfo = {
  findings?: Finding[];
  rating_key: number;
  title: string;
  media_type: string | null;
  year: number | null;
  file_bitrate: number | null;
  file_size: number | null;
  file_container: string | null;
  file_path: string | null;
  versions: number | null;
  video_codec: string | null;
  video_resolution: string | null;
  video_bit_depth: number | null;
  video_dynamic_range: string | null;
  audio_codec: string | null;
  audio_channels: number | null;
  audio_tracks: Track[];
  subtitle_tracks: Track[];
  issues: string[];
};

type Overview = {
  titles: number;
  checked: number;
  scanned_at: string | null;
  size: number;
  threshold_mbps: number;
  streams_recorded: number;
  stalls_recorded: number;
  resolutions: { resolution: string; files: number; size: number }[];
};

type CauseRow = {
  cause: string;
  label: string;
  streams: number;
  hardware: number;
  platforms: { name: string; streams: number }[];
  /** The actual boxes, which is what somebody can go and change. */
  players?: { name: string; streams: number }[];
  titles: { rating_key: number; title: string | null; streams: number }[];
};

type FourK = FileInfo & {
  plays: number;
  transcodes: number;
  remote_plays: number;
  users: number;
  last_play: number | null;
  streams_seen: number;
  streams_in_4k: number;
  verdict: "never_4k" | "mostly_downscaled" | "unwatched" | "benefits";
};

type RequestRow = {
  rating_key: number;
  title: string | null;
  media_type: string | null;
  requested_by: string | null;
  user_id: number | null;
  requested_at: string | null;
  available_days: number | null;
  watched_by_others: number;
  file_size: number | null;
};

export type FileDetail = FileInfo & {
  store?: string | null;
  findings: Finding[];
  arr: { name: string; label: string; configured: boolean };
  plays: number;
  remote_plays: number;
  transcodes: number;
  users: number;
  last_play: number | null;
  platforms: { platform: string; plays: number; transcodes: number }[];
  stall_causes: { cause: string; stalls: number }[];
  transcode_causes: { cause: string; streams: number }[];
};

const SECTIONS = [
  { id: "overview", title: "Overview" },
  { id: "browse", title: "Browse" },
  { id: "attention", title: "Files worth attention" },
  { id: "transcodes", title: "Why streams transcode" },
  { id: "four-k", title: "4K copies" },
  { id: "storage", title: "Storage" },
  { id: "requests", title: "Requested, never watched" },
  { id: "queue", title: "Remediation queue" },
] as const;
type SectionId = (typeof SECTIONS)[number]["id"];

const TRANSCODE_CAUSES: Record<string, string> = {
  subtitle_burn: "Subtitles burned in",
  hdr_tonemap: "HDR converted to SDR",
  video_codec: "Video format",
  quality_setting: "Quality setting",
  video_bitrate: "Bitrate or resolution",
  audio_codec: "Audio format",
  audio_channels: "Audio channels",
  container: "Container",
};

const STALL_CAUSES: Record<string, string> = {
  upload: "Upload nearly full",
  server: "Server side",
  file: "This file",
  stream: "One stream kept stalling",
  viewer: "Viewer's device or connection",
  one_off: "One-off",
};

const VERDICTS: Record<FourK["verdict"], { label: string; tone: string }> = {
  never_4k: { label: "Never reached a screen in 4K", tone: "pill bad" },
  mostly_downscaled: { label: "Mostly scaled down", tone: "pill warn" },
  unwatched: { label: "Not watched", tone: "pill" },
  benefits: { label: "Watched in 4K", tone: "pill ok" },
};

export function size(bytes: number | null | undefined): string {
  if (!bytes) return "";
  const gb = bytes / 1e9;
  return gb >= 1000 ? `${(gb / 1000).toFixed(2)} TB` : gb >= 1 ? `${gb.toFixed(1)} GB` : `${(bytes / 1e6).toFixed(0)} MB`;
}

export function mbps(kbps: number | null | undefined): string {
  return kbps ? `${(kbps / 1000).toFixed(1)} Mbps` : "";
}

function format(f: FileInfo): string {
  return [
    f.video_resolution,
    f.video_codec?.toUpperCase(),
    f.video_bit_depth ? `${f.video_bit_depth}-bit` : null,
    f.video_dynamic_range && f.video_dynamic_range !== "SDR" ? f.video_dynamic_range : null,
    f.audio_codec?.toUpperCase(),
    f.file_container,
  ]
    .filter(Boolean)
    .join(" · ");
}

export default function Library() {
  const [section, setSection] = useState<SectionId>("overview");
  const [days, setDays] = useState(90);
  const current = SECTIONS.find((s) => s.id === section)!;
  const replacementList = useApi<Replacement[]>("/library/replacements");
  const tidyList = useApi<TidyJob[]>("/library/tidy/jobs?limit=30");
  const waiting = (replacementList.data ?? []).filter((r) => r.status === "ready").length;
  const working = (tidyList.data ?? []).filter((j) => j.status === "running" || j.status === "queued").length;

  return (
    <div className="settings-layout wide">
      <nav className="settings-nav" aria-label="Library">
        <h1>Library</h1>
        <div className="settings-nav-group">
          {SECTIONS.map((s) => (
            <button
              key={s.id}
              className={s.id === section ? "settings-nav-item on" : "settings-nav-item"}
              aria-current={s.id === section ? "page" : undefined}
              onClick={() => setSection(s.id)}
            >
              <span>{s.title}</span>
              {s.id === "queue" && working > 0 && <span className="pill">{working} running</span>}
              {s.id === "queue" && working === 0 && waiting > 0 && (
                <span className="pill warn">{waiting} ready</span>
              )}
            </button>
          ))}
        </div>
      </nav>
      <div className="settings-page">
        <header className="settings-page-head row-between">
          <h2>{current.title}</h2>
          {section !== "overview" && section !== "requests" && section !== "queue" && (
            <label className="inline-select">
              <span className="muted small">Looking back</span>
              <select value={days} onChange={(e) => setDays(Number(e.target.value))}>
                {[30, 90, 180, 365, 730].map((d) => (
                  <option key={d} value={d}>
                    {d < 365 ? `${d} days` : d === 365 ? "1 year" : "2 years"}
                  </option>
                ))}
              </select>
            </label>
          )}
        </header>
        {section === "overview" && <OverviewSection onOpen={setSection} />}
        {section === "browse" && <Browse days={days} />}
        {section === "attention" && <Attention days={days} />}
        {section === "transcodes" && <Transcodes days={days} />}
        {section === "four-k" && <FourKSection days={days} />}
        {section === "storage" && <StorageSection days={days} />}
        {section === "requests" && <Requests />}
        {section === "queue" && <RemediationQueue />}
      </div>
    </div>
  );
}

function OverviewSection({ onOpen }: { onOpen: (s: SectionId) => void }) {
  const data = useApi<Overview>("/library/overview");
  if (data.error) return <p className="note bad-note">{data.error}</p>;
  if (!data.data) return <Loading label="Reading the library" />;
  const o = data.data;
  const pending = o.titles - o.checked;
  return (
    <>
      <p className="muted">
        Files judged by how they are watched: which cause trouble for remote viewers, why streams transcode, which are
        awkward to play, whether 4K copies reach a 4K screen, and which requests nobody watched.
      </p>
      {!o.scanned_at && (
        <p className="note">
          Listing the whole library. This takes about a minute after the app starts, then repeats every 6 hours.
        </p>
      )}
      {o.scanned_at && pending > 0 && (
        <p className="note">
          Reading audio and subtitle tracks: {o.checked.toLocaleString()} of {o.titles.toLocaleString()} files so far,
          about 3,000 a minute. Awkward to play grows as this finishes. Bitrate, resolution and 4K lists are already
          complete.
        </p>
      )}
      <OldStalls />
      <dl className="stats">
        <div className="stat">
          <dt>Files in the library</dt>
          <dd>{o.titles.toLocaleString()}</dd>
        </div>
        <div className="stat">
          <dt>Library size</dt>
          <dd>{size(o.size) || "0"}</dd>
        </div>
        <div className="stat">
          <dt>Streams recorded live</dt>
          <dd>{o.streams_recorded.toLocaleString()}</dd>
        </div>
        <div className="stat">
          <dt>Stalls recorded</dt>
          <dd>{o.stalls_recorded.toLocaleString()}</dd>
        </div>
      </dl>
      <h3>By resolution</h3>
      <div className="mini-list">
        {o.resolutions.map((r) => (
          <div key={r.resolution} className="mini">
            <span>{r.resolution}</span>
            <span className="muted">
              {r.files.toLocaleString()} files{" · "}
              {size(r.size)}
            </span>
          </div>
        ))}
      </div>
      <div className="row wrap library-jumps">
        {SECTIONS.filter((s) => s.id !== "overview").map((s) => (
          <button key={s.id} className="btn" onClick={() => onOpen(s.id)}>
            {s.title}
          </button>
        ))}
      </div>
    </>
  );
}
function Transcodes({ days }: { days: number }) {
  const nav = useNav();
  const data = useApi<{ total_streams: number; causes: CauseRow[] }>(`/library/transcodes?days=${days}`);
  if (data.error) return <p className="note bad-note">{data.error}</p>;
  if (!data.data) return <Loading label="Counting why streams transcoded" />;
  const { total_streams, causes } = data.data;
  return (
    <>
      <p className="muted">
        Every reason a stream was not a plain direct play, read from what changed between the file and what was sent. A
        stream can have more than one. From streams seen live, so this grows from the day this version was installed.
      </p>
      <p className="small">
        <strong>{total_streams.toLocaleString()}</strong> <span className="muted">streams recorded in this period.</span>
      </p>
      {causes.length === 0 && <p className="muted">No transcodes recorded yet.</p>}
      <div className="cause-grid">
        {causes.map((c) => (
          <section key={c.cause} className="cause-card">
            <div className="row-between">
              <h3>{c.label}</h3>
              <strong>{c.streams.toLocaleString()}</strong>
            </div>
            <p className="muted small">
              {total_streams ? `${Math.round((c.streams / total_streams) * 100)}% of streams` : ""}
              {c.hardware ? ` · ${c.hardware} on hardware` : ""}
            </p>
            <p className="small">
              <span className="muted">Platforms: </span>
              {c.platforms.map((p) => `${p.name} (${p.streams})`).join(", ")}
            </p>
            {c.players && c.players.length > 0 && (
              <p className="small">
                <span className="muted">Devices: </span>
                {c.players.map((p) => `${p.name} (${p.streams})`).join(", ")}
              </p>
            )}
            <div className="mini-list">
              {c.titles.map((t) => (
                <div key={t.rating_key} className="mini">
                  {nav.filterTo ? (
                    <button
                      className="linkish clip"
                      onClick={() => nav.filterTo?.("History", { rating_key: t.rating_key, ratingKeyLabel: t.title ?? "" })}
                    >
                      {t.title ?? `Item ${t.rating_key}`}
                    </button>
                  ) : (
                    <span className="clip">{t.title}</span>
                  )}
                  <span className="muted small">{t.streams}</span>
                </div>
              ))}
            </div>
            <p className="muted small">{FIXES[c.cause]}</p>
          </section>
        ))}
      </div>
    </>
  );
}

const FIXES: Record<string, string> = {
  subtitle_burn: "Fix: convert image or styled subtitles to SRT, or ask viewers to turn subtitles off on older devices.",
  hdr_tonemap: "Fix: keep an SDR version beside the HDR one, or make sure tone mapping runs on hardware.",
  video_codec: "Fix: an H.264 version for devices without HEVC or AV1 support.",
  quality_setting: "Fix: viewers can set their remote quality to Original or Maximum in the Plex app.",
  video_bitrate: "Fix: a lower bitrate version, or a higher remote streaming limit on the server if upload allows.",
  audio_codec: "Fix: add an AAC or AC3 audio track beside TrueHD or DTS.",
  audio_channels: "Fix: add a stereo AAC track for devices limited to two channels.",
  container: "Usually harmless: the server repackages the file without re-encoding it.",
};
function FourKSection({ days }: { days: number }) {
  const rows = useApi<FourK[]>(`/library/four-k?days=${days}`);
  if (rows.error) return <p className="note bad-note">{rows.error}</p>;
  if (!rows.data) return <Loading label="Checking 4K files" />;
  const wasted = rows.data.filter((r) => r.verdict === "never_4k" || r.verdict === "mostly_downscaled");
  return (
    <>
      <p className="muted">
        Whether 4K copies reach a 4K screen. A 4K file that is transcoded is nearly always scaled down, and where streams
        were seen live the resolution actually sent is known. Largest first within each group.
      </p>
      <p className="small">
        <strong>{size(wasted.reduce((n, r) => n + (r.file_size ?? 0), 0)) || "0"}</strong>{" "}
        <span className="muted">in 4K files that are mostly or always scaled down.</span>
      </p>
      {rows.data.length === 0 && <p className="muted">No 4K files found yet.</p>}
      <div className="mini-list">
        {rows.data.map((r) => (
          <FileRow
            key={r.rating_key}
            file={r}
            days={days}
            badges={[
              <span key="v" className={VERDICTS[r.verdict].tone}>
                {VERDICTS[r.verdict].label}
              </span>,
            ]}
            stats={[
              size(r.file_size),
              `${r.plays} plays, ${r.transcodes} transcoded`,
              r.streams_seen ? `${r.streams_in_4k} of ${r.streams_seen} live streams in 4K` : null,
              r.last_play ? `last ${when(r.last_play)}` : null,
            ]}
          />
        ))}
      </div>
    </>
  );
}

function Requests() {
  const nav = useNav();
  const data = useApi<{ configured: boolean; requests: RequestRow[] }>("/library/requests");
  if (data.error) return <p className="note bad-note">{data.error}</p>;
  if (!data.data) return <Loading label="Asking Seerr for requests" slowHint="Seerr is read a page of 100 requests at a time." />;
  if (!data.data.configured)
    return <p className="note warn-note">Connect Seerr in Settings to see requests that were never watched.</p>;
  const rows = data.data.requests;
  return (
    <>
      <p className="muted">
        Requests that are available and the person who asked has never played, longest available first. Requesters are
        matched to Plex users by Plex username or email.
      </p>
      {rows.length === 0 && <p className="muted">Everyone watched what they asked for.</p>}
      <div className="mini-list">
        {rows.map((r, i) => (
          <div key={`${r.rating_key}-${i}`} className="mini">
            <div className="min0">
              {nav.filterTo ? (
                <button
                  className="linkish clip"
                  onClick={() => nav.filterTo?.("History", { rating_key: r.rating_key, ratingKeyLabel: r.title ?? "" })}
                >
                  {r.title ?? `Item ${r.rating_key}`}
                </button>
              ) : (
                <span className="clip">{r.title}</span>
              )}
              <p className="muted small">
                Requested by{" "}
                {r.user_id != null && nav.openUser ? (
                  <button className="linkish" onClick={() => nav.openUser?.(r.user_id as number)}>
                    {r.requested_by}
                  </button>
                ) : (
                  r.requested_by ?? "someone"
                )}
                {r.available_days != null ? ` · available ${r.available_days} days` : ""}
                {r.watched_by_others ? ` · watched by ${r.watched_by_others} other${r.watched_by_others === 1 ? "" : "s"}` : " · watched by nobody"}
                {r.file_size ? ` · ${size(r.file_size)}` : ""}
              </p>
            </div>
          </div>
        ))}
      </div>
    </>
  );
}

/* One file in any list: a summary that opens to the whole file. */
function FileRow({ file, badges, stats, days }: { file: FileInfo; badges: ReactNode[]; stats: (string | null)[]; days: number }) {
  const [open, setOpen] = useState(false);
  return (
    <div>
      <button className={open ? "mini mini-button on" : "mini mini-button"} aria-expanded={open} onClick={() => setOpen(!open)}>
        <div className="min0">
          <span className="clip">
            <strong>{file.title}</strong>
          </span>
          <div className="row wrap file-badges">{badges}</div>
          <p className="muted small">{stats.filter(Boolean).join(" · ")}</p>
          {file.findings && file.findings.length > 0 && (
            <p className="small finding-summary">
              {file.findings[0].title}
              {file.findings.length > 1 ? ` and ${file.findings.length - 1} more` : ""}
            </p>
          )}
        </div>
        <span className="muted small">{open ? "Hide" : "Details"}</span>
      </button>
      {open && <FileCard ratingKey={file.rating_key} days={days} />}
    </div>
  );
}

function FileCard({ ratingKey, days }: { ratingKey: number; days: number }) {
  const detail = useApi<FileDetail>(`/library/file/${ratingKey}?days=${days}`);
  if (detail.error) return <p className="note bad-note">{detail.error}</p>;
  if (!detail.data)
    return (
      <div className="file-card">
        <Loading compact label="Reading the file" />
      </div>
    );
  return <FileCardView f={detail.data} days={days} />;
}

/* The card itself, given a file. Issues render it from their own payload
 * rather than asking for the same file twice. */
export function FileCardView({ f, days }: { f: FileDetail; days: number }) {
  const nav = useNav();
  const [showTitle, setShowTitle] = useState(false);
  return (
    <div className="file-card">
      {f.findings.length > 0 ? (
        <section className="findings">
          <h4>What is wrong, and how to fix it</h4>
          {f.findings.map((x) => (
            <div key={x.key} className={`finding ${x.severity}`}>
              <div className="row">
                <span className={x.severity === "high" ? "pill bad" : x.severity === "medium" ? "pill warn" : "pill"}>
                  {x.severity === "high" ? "Fix first" : x.severity === "medium" ? "Worth fixing" : "Tidy up"}
                </span>
                <strong>{x.title}</strong>
              </div>
              <p className="small">{x.detail}</p>
              <p className="small">
                <span className="muted">Fix: </span>
                {x.fix}
              </p>
              {x.arr && <p className="muted small">{x.arr}</p>}
            </div>
          ))}
        </section>
      ) : (
        <p className="muted small">Nothing about this file itself stands out.</p>
      )}
      {/* Outside the findings: a file can be worth replacing for taking up
          room, not only for being broken. */}
      <ArrActions ratingKey={f.rating_key} arr={f.arr} title={f.title} />
      <TidyPanel ratingKey={f.rating_key} title={f.title} />
      <dl className="kv">
        <div>
          <dt>Format</dt>
          <dd>{format(f) || "Not checked yet"}</dd>
        </div>
        {f.store && (
          <div>
            <dt>Stored on</dt>
            <dd>{f.store}</dd>
          </div>
        )}
        <div>
          <dt>Bitrate and size</dt>
          <dd>{[mbps(f.file_bitrate), size(f.file_size), f.versions && f.versions > 1 ? `${f.versions} versions` : null].filter(Boolean).join(" · ")}</dd>
        </div>
        <div>
          <dt>Played, last {days} days</dt>
          <dd>
            {f.plays} times by {f.users} {f.users === 1 ? "person" : "people"}, {f.remote_plays} remote, {f.transcodes} transcoded
            {f.last_play ? `, last ${when(f.last_play)}` : ""}
          </dd>
        </div>
        {f.transcode_causes.length > 0 && (
          <div>
            <dt>Why it transcoded</dt>
            <dd>{f.transcode_causes.map((c) => `${TRANSCODE_CAUSES[c.cause] ?? c.cause} (${c.streams})`).join(", ")}</dd>
          </div>
        )}
        {f.stall_causes.length > 0 && (
          <div>
            <dt>Stalls</dt>
            <dd>{f.stall_causes.map((c) => `${STALL_CAUSES[c.cause] ?? c.cause} (${c.stalls})`).join(", ")}</dd>
          </div>
        )}
        {f.platforms.length > 0 && (
          <div>
            <dt>Platforms</dt>
            <dd>{f.platforms.map((p) => `${p.platform} ${p.plays}${p.transcodes ? ` (${p.transcodes} transcoded)` : ""}`).join(", ")}</dd>
          </div>
        )}
      </dl>


      <div className="track-lists">
        <div>
          <h4>Audio</h4>
          {f.audio_tracks.length === 0 && <p className="muted small">None recorded.</p>}
          {f.audio_tracks.map((t, i) => (
            <p key={i} className="small">
              {[t.codec?.toUpperCase(), t.channels ? `${t.channels} ch` : null, t.language ?? "no language", t.bitrate ? `${t.bitrate} kbps` : null]
                .filter(Boolean)
                .join(" · ")}
            </p>
          ))}
        </div>
        <div>
          <h4>Subtitles</h4>
          {f.subtitle_tracks.length === 0 && <p className="muted small">None.</p>}
          {f.subtitle_tracks.map((t, i) => (
            <p key={i} className="small">
              {[t.codec?.toUpperCase(), t.language ?? "no language", t.forced ? "forced" : null, t.location].filter(Boolean).join(" · ")}
            </p>
          ))}
        </div>
      </div>

      {f.file_path && <code className="file-path">{f.file_path}</code>}

      <div className="row wrap">
        {nav.filterTo && (
          <button className="btn" onClick={() => nav.filterTo?.("History", { rating_key: f.rating_key, ratingKeyLabel: f.title })}>
            Plays in History
          </button>
        )}
        <button className="btn" onClick={() => setShowTitle(!showTitle)}>
          {showTitle ? "Hide title card" : "Title card"}
        </button>
      </div>
      {showTitle && <MediaPanel ratingKey={f.rating_key} />}
    </div>
  );
}

/* Hand a file back to Radarr or Sonarr. Search asks it to look for a better
 * release, which it only grabs if the quality profile rates it higher; Tag
 * marks it to pick a release by hand. Neither deletes the current file. */
/* Tidying a file's tracks with ffmpeg, in this container.
 *
 * What is offered comes from the file's own tracks, so the list is empty for a
 * file with nothing wrong. Nothing re-encodes the picture: subtitles are
 * converted or dropped, an audio track everything can play is added beside the
 * original, an old container is repackaged.
 */
type TidyTrack = {
  position: number;
  codec: string | null;
  channels?: number | null;
  language: string | null;
  forced?: boolean;
  title?: string | null;
};

type Tidy = {
  steps: { key: string; what: string; why: string }[];
  file_path: string | null;
  audio: TidyTrack[];
  subtitles: TidyTrack[];
  local_path: string | null;
  tools: { ready: boolean };
};

function trackName(track: TidyTrack): string {
  return [
    (track.codec ?? "?").toUpperCase(),
    track.channels ? `${track.channels} ch` : null,
    track.language ?? "no language",
    track.forced ? "forced" : null,
    track.title,
  ]
    .filter(Boolean)
    .join(" \u00b7 ");
}

type TidyJob = {
  id: number;
  rating_key: number;
  title: string | null;
  status: string;
  progress: number;
  detail: string | null;
  saved_bytes: number | null;
  steps: string[];
};

function TidyPanel({ ratingKey, title }: { ratingKey: number; title: string }) {
  const plan = useApi<Tidy>(`/library/file/${ratingKey}/tidy`, [ratingKey]);
  const [chosen, setChosen] = useState<Set<string> | null>(null);
  const [message, setMessage] = useState<{ text: string; ok: boolean } | null>(null);
  const [busy, setBusy] = useState(false);
  // Which tracks survive, and which one plays first. Null until somebody
  // touches them, so a file nobody has edited sends no choice at all.
  const [keepAudio, setKeepAudio] = useState<Set<number> | null>(null);
  const [keepSubs, setKeepSubs] = useState<Set<number> | null>(null);
  const [first, setFirst] = useState<number | null>(null);

  if (plan.error || !plan.data) return null;
  const t = plan.data;
  const tracks = t.audio.length + t.subtitles.length;
  if (t.steps.length === 0 && tracks === 0) return null;
  const picked = chosen ?? new Set(t.steps.map((s) => s.key));
  const audioKept = keepAudio ?? new Set(t.audio.map((a) => a.position));
  const subsKept = keepSubs ?? new Set(t.subtitles.map((x) => x.position));
  const edited =
    keepAudio !== null || keepSubs !== null || first !== null;

  function pick(key: string, on: boolean) {
    const next = new Set(picked);
    if (on) next.add(key);
    else next.delete(key);
    setChosen(next);
  }

  function keep(which: "audio" | "subtitles", position: number, on: boolean) {
    const from = which === "audio" ? audioKept : subsKept;
    const next = new Set(from);
    if (on) next.add(position);
    else next.delete(position);
    (which === "audio" ? setKeepAudio : setKeepSubs)(next);
  }

  async function start() {
    const dropped =
      t.audio.length - audioKept.size + (t.subtitles.length - subsKept.size);
    const warning = dropped > 0 ? `\n\n${dropped} track${dropped === 1 ? "" : "s"} will be dropped.` : "";
    if (!confirm(`Tidy ${title}?${warning}\n\nThe file is read and written once, the result is checked against the original for length and picture, and only then does it replace it. The picture is never re-encoded.`)) return;
    setBusy(true);
    setMessage(null);
    try {
      await api.post(`/library/file/${ratingKey}/tidy`, {
        steps: [...picked],
        chosen: edited
          ? {
              audio: [...audioKept],
              subtitles: [...subsKept],
              ...(first !== null ? { default_audio: first } : {}),
            }
          : {},
      });
      setMessage({ text: "Queued. It runs one file at a time, and the Remediation queue shows how far along it is.", ok: true });
    } catch (err) {
      setMessage({ text: (err as Error).message, ok: false });
    } finally {
      setBusy(false);
    }
  }

  const blocked = !t.tools.ready
    ? "ffmpeg is not in this image, so this build cannot tidy anything."
    : !t.local_path
      ? `This container cannot open ${t.file_path ?? "the file"}. Mount the share that holds it, then say where it landed under Settings, Library and files.`
      : null;

  return (
    <section className="profile-section tidy">
      <h3>Tidy the tracks</h3>
      <div className="mini-list">
        {t.steps.map((step) => (
          <label key={step.key} className="mini tidy-step">
            <span className="min0">
              <span className="check">
                <input
                  type="checkbox"
                  checked={picked.has(step.key)}
                  disabled={Boolean(blocked)}
                  onChange={(e) => pick(step.key, e.target.checked)}
                />
                <strong>{step.what}</strong>
              </span>
              <p className="muted small">{step.why}</p>
            </span>
          </label>
        ))}
      </div>
      {tracks > 0 && (
        <div className="track-picks">
          {t.audio.length > 0 && (
            <div className="min0">
              <div className="row-between">
                <p className="muted small">Audio: untick to drop, choose one to play first</p>
                <span className="row">
                  <button className="tab" onClick={() => setKeepAudio(new Set(t.audio.map((a) => a.position)))}>
                    all
                  </button>
                  <button className="tab" onClick={() => setKeepAudio(new Set())}>
                    none
                  </button>
                </span>
              </div>
              {t.audio.map((track) => (
                <div key={track.position} className="track-row">
                  <label className="check">
                    <input
                      type="checkbox"
                      checked={audioKept.has(track.position)}
                      disabled={Boolean(blocked)}
                      onChange={(e) => keep("audio", track.position, e.target.checked)}
                    />
                    <span>{trackName(track)}</span>
                  </label>
                  <label className="check" title="Players take the first track unless somebody goes looking">
                    <input
                      type="radio"
                      name={`first-${ratingKey}`}
                      checked={first === track.position}
                      disabled={Boolean(blocked) || !audioKept.has(track.position)}
                      onChange={() => setFirst(track.position)}
                    />
                    <span className="muted small">first</span>
                  </label>
                </div>
              ))}
              {t.audio.length > 1 && audioKept.size === 0 && (
                <p className="muted small">Everything is kept: a file is never left with no sound.</p>
              )}
            </div>
          )}
          {t.subtitles.length > 0 && (
            <div className="min0">
              <div className="row-between">
                <p className="muted small">Subtitles: untick to drop</p>
                <span className="row">
                  <button className="tab" onClick={() => setKeepSubs(new Set(t.subtitles.map((x) => x.position)))}>
                    all
                  </button>
                  <button className="tab" onClick={() => setKeepSubs(new Set())}>
                    none
                  </button>
                  {/* The commonest wish by far, and fifty six clicks otherwise. */}
                  <button
                    className="tab"
                    title="Keep only tracks in the language you watch in"
                    onClick={() =>
                      setKeepSubs(
                        new Set(
                          t.subtitles
                            .filter((x) => (x.language ?? "").toLowerCase() === (t.subtitles[0]?.language ?? "eng").toLowerCase())
                            .map((x) => x.position),
                        ),
                      )
                    }
                  >
                    first language only
                  </button>
                </span>
              </div>
              {t.subtitles.map((track) => (
                <div key={track.position} className="track-row">
                  <label className="check">
                    <input
                      type="checkbox"
                      checked={subsKept.has(track.position)}
                      disabled={Boolean(blocked)}
                      onChange={(e) => keep("subtitles", track.position, e.target.checked)}
                    />
                    <span>{trackName(track)}</span>
                  </label>
                </div>
              ))}
            </div>
          )}
        </div>
      )}

      {blocked ? (
        <p className="muted small">{blocked}</p>
      ) : (
        <div className="row wrap">
          <button className="btn" disabled={busy || (picked.size === 0 && !edited)} onClick={start}>
            {busy ? "Queueing..." : "Tidy it"}
          </button>
          <span className="muted small">
            The picture is copied, never re-encoded. The original is replaced only after the result is checked.
          </span>
        </div>
      )}
      {message && <p className={message.ok ? "note" : "note bad-note"}>{message.text}</p>}
    </section>
  );
}

/* What ffmpeg is doing now, and what it did lately. Shown only when there is
   something to say, so the page is unchanged for anyone not using it. */
function TidyJobs({ scope }: { scope: "active" | "history" }) {
  const jobs = useApi<TidyJob[]>("/library/tidy/jobs?limit=40", []);
  const busy = (jobs.data ?? []).some((j) => j.status === "running" || j.status === "queued");
  const again = useRef(jobs.reload);
  again.current = jobs.reload;

  // Only while something is working: a finished list does not change by itself.
  useEffect(() => {
    if (!busy) return;
    const timer = setInterval(() => again.current(), 3000);
    return () => clearInterval(timer);
  }, [busy]);

  const working = (job: TidyJob) => job.status === "running" || job.status === "queued";
  const rows = (jobs.data ?? []).filter((job) => (scope === "active" ? working(job) : !working(job)));
  if (rows.length === 0) return null;

  return (
    <section className="tidy-jobs">
      <h3 className="section-head">{scope === "active" ? "Tidying tracks" : "Tidied"}</h3>
      <div className="mini-list">
        {rows.map((job) => (
          <div key={job.id} className="mini">
            <div className="min0">
              <strong>{job.title ?? `Item ${job.rating_key}`}</strong>
              <p className="muted small">
                {job.status === "running"
                  ? `${job.progress}% - ${job.detail ?? "working"}`
                  : job.status === "queued"
                    ? "Waiting its turn"
                    : `${job.status}: ${job.detail ?? ""}`}
                {job.saved_bytes ? ` (${size(job.saved_bytes)} smaller)` : ""}
              </p>
            </div>
            {(job.status === "running" || job.status === "queued") && (
              <button
                className="tab"
                onClick={async () => {
                  await api.post(`/library/tidy/jobs/${job.id}/cancel`, {});
                  jobs.reload();
                }}
              >
                Stop
              </button>
            )}
          </div>
        ))}
      </div>
    </section>
  );
}

function ArrActions({
  ratingKey,
  arr,
  title,
}: {
  ratingKey: number;
  arr: { name: string; label: string; configured: boolean };
  title: string;
}) {
  const [busy, setBusy] = useState<string | null>(null);
  const [message, setMessage] = useState<{ text: string; ok: boolean } | null>(null);
  const [picking, setPicking] = useState(false);

  async function run(action: "search" | "tag") {
    const question =
      action === "search"
        ? `Ask ${arr.label} to search for a replacement for ${title}?\n\nIt only downloads a release your quality profile rates higher than the current file. Nothing is deleted.`
        : `Tag ${title} "cartographarr-replace" in ${arr.label}, to find and pick a release by hand later?`;
    if (!confirm(question)) return;
    setBusy(action);
    setMessage(null);
    try {
      const r = await api.post<{ message: string }>(`/library/file/${ratingKey}/arr`, { action });
      setMessage({ text: r.message, ok: true });
    } catch (err) {
      setMessage({ text: (err as Error).message, ok: false });
    } finally {
      setBusy(null);
    }
  }

  const why = arr.configured ? undefined : `Connect ${arr.label} in Settings to use this`;
  return (
    <div className="arr-actions">
      <div className="row wrap">
        <button className="btn primary" onClick={() => setPicking(!picking)} disabled={!arr.configured} title={why}>
          Find a replacement
        </button>
        <button className="btn" onClick={() => run("search")} disabled={!arr.configured || busy !== null} title={why}>
          {busy === "search" ? "Asking\u2026" : `Let ${arr.label} search by itself`}
        </button>
        <button className="btn" onClick={() => run("tag")} disabled={!arr.configured || busy !== null} title={why}>
          {busy === "tag" ? "Tagging\u2026" : "Tag for replacement"}
        </button>
      </div>
      {!arr.configured && <p className="muted small">{why}.</p>}
      {message && <p className={message.ok ? "note ok-note" : "note bad-note"}>{message.text}</p>}
      {picking && <ReleasePicker ratingKey={ratingKey} label={arr.label} title={title} onClose={() => setPicking(false)} />}
    </div>
  )
}

type Release = {
  guid: string;
  indexer_id: number;
  title: string;
  indexer: string | null;
  size: number | null;
  age_days: number | null;
  seeders: number | null;
  protocol: string | null;
  quality: string | null;
  languages: string[];
  custom_format_score: number | null;
  custom_formats?: string[];
  estimated_bitrate: number | null;
  parsed: Parsed;
  fixes: string[];
  held: boolean;
  rejections: string[];
  blocked: boolean;
};

type Parsed = {
  resolution?: string;
  video_codec?: string;
  bit_depth?: number;
  hdr?: string;
  audio_codec?: string;
  audio_channels?: number;
  source?: string;
};

type Replacement = {
  id: number;
  rating_key: number;
  title: string | null;
  service: string;
  status: "queued" | "downloading" | "ready" | "importing" | "imported" | "imported_automatically" | "denied" | "failed";
  progress: number | null;
  message: string | null;
  release: Release | null;
  current: (FileInfo & { duration?: number | null }) | null;
  candidate: {
    name?: string;
    size?: number;
    quality?: string;
    languages?: string[];
    release_group?: string;
    rejections?: string[];
    parsed?: Parsed;
    imported?: {
      size?: number;
      quality?: string;
      video_codec?: string;
      bit_depth?: number;
      hdr?: string;
      audio_codec?: string;
      audio_channels?: number;
      audio_languages?: string;
      subtitles?: string;
      resolution?: string;
    };
  } | null;
  created_by: string | null;
  updated_at: string | null;
  resolved_by: string | null;
  checked_at?: string | null;
};

type Live = {
  checked_at: string;
  queue: {
    status: string | null;
    state: string | null;
    health: string | null;
    progress: number | null;
    time_left: string | null;
    client: string | null;
    messages: string[];
  } | null;
  events: { type: string; label: string; date: string | null; title: string | null; message: string | null }[];
};

const STEPS: { key: string; label: string }[] = [
  { key: "queued", label: "Queued" },
  { key: "downloading", label: "Downloading" },
  { key: "ready", label: "Ready for you" },
  { key: "done", label: "Replaced" },
];

function stepOf(status: Replacement["status"]): number {
  return { queued: 0, downloading: 1, ready: 2, importing: 2, imported: 3, imported_automatically: 3 }[status as string] ?? -1;
}

function ago(iso: string | null | undefined): string {
  if (!iso) return "never";
  const t = new Date(/[zZ]|[+-]\d\d:\d\d$/.test(iso) ? iso : `${iso}Z`).getTime();
  const s = Math.max(0, Math.round((Date.now() - t) / 1000));
  return s < 60 ? `${s}s ago` : s < 3600 ? `${Math.round(s / 60)} min ago` : new Date(t).toLocaleString();
}

const CHANNELS: Record<number, string> = { 2: "stereo", 6: "5.1", 8: "7.1" };

/* Releases Radarr or Sonarr can find, each against the current file.
 *
 * A tile each rather than a row, because the decision needs the whole of a
 * release at once: what it would fix, what it is made of, how big, how old,
 * and whether the service will take it by itself. Best first, which means
 * most of this file's problems solved, then the service's own score against
 * the profile.
 */
type SortKey = "best" | "score" | "size" | "bitrate" | "seeders" | "age";

const SORTS: Record<SortKey, { label: string; of: (r: Release) => number }> = {
  best: { label: "Best first", of: () => 0 },
  score: { label: "Profile score", of: (r) => r.custom_format_score ?? -1e9 },
  size: { label: "Smallest", of: (r) => -(r.size ?? 0) },
  bitrate: { label: "Lowest bitrate", of: (r) => -(r.estimated_bitrate ?? 0) },
  seeders: { label: "Most seeders", of: (r) => r.seeders ?? -1 },
  age: { label: "Newest", of: (r) => -(r.age_days ?? 1e9) },
};

function ReleasePicker({
  ratingKey,
  label,
  title,
  onClose,
}: {
  ratingKey: number;
  label: string;
  title: string;
  onClose: () => void;
}) {
  const ref = useRef<HTMLDialogElement>(null);
  const found = useApi<{ service: string; current: FileInfo; releases: Release[] }>(`/library/file/${ratingKey}/releases`);
  const [sort, setSort] = useState<SortKey>("best");
  const [resolution, setResolution] = useState("");
  const [protocol, setProtocol] = useState("");
  const [maxSize, setMaxSize] = useState(0);
  const [hideBlocked, setHideBlocked] = useState(true);
  const [hideHeld, setHideHeld] = useState(false);
  const [queued, setQueued] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    ref.current?.showModal();
  }, []);

  async function queue(release: Release) {
    const how = release.held
      ? `${label} does not rate it as an upgrade, so once downloaded it waits in Library, Replacements for you to confirm or deny.`
      : `${label} rates it as an upgrade, so it will import it as soon as it is downloaded, without waiting for you.`;
    if (!confirm(`Download this replacement for ${title}?\n\n${release.title}\n\n${how}`)) return;
    setError(null);
    try {
      await api.post(`/library/file/${ratingKey}/replace`, { release });
      setQueued(release.guid);
    } catch (err) {
      setError((err as Error).message);
    }
  }

  const all = found.data?.releases ?? [];
  const resolutions = [...new Set(all.map((r) => r.parsed.resolution).filter(Boolean))] as string[];
  const protocols = [...new Set(all.map((r) => r.protocol).filter(Boolean))] as string[];
  const sizes = all.map((r) => r.size ?? 0).filter(Boolean);
  const biggest = sizes.length ? Math.max(...sizes) : 0;

  const visible = all.filter(
    (r) =>
      (!hideBlocked || !r.blocked) &&
      (!hideHeld || !r.held) &&
      (!resolution || r.parsed.resolution === resolution) &&
      (!protocol || r.protocol === protocol) &&
      (!maxSize || (r.size ?? 0) <= maxSize),
  );
  const rows = sort === "best" ? visible : [...visible].sort((a, b) => SORTS[sort].of(b) - SORTS[sort].of(a));

  return (
    <dialog ref={ref} className="dialog wide" onClose={onClose} aria-labelledby="release-picker-title">
      <div className="row-between dialog-head">
        <div className="min0">
          <h2 id="release-picker-title">Replace {title}</h2>
          {found.data && (
            <p className="muted small">
              Current file: {format(found.data.current)}
              {found.data.current.file_size ? ` \u00b7 ${size(found.data.current.file_size)}` : ""}
              {found.data.current.file_bitrate ? ` \u00b7 ${mbps(found.data.current.file_bitrate)}` : ""}
            </p>
          )}
        </div>
        <button className="icon-btn" onClick={() => ref.current?.close()} aria-label="Close">
          &times;
        </button>
      </div>

      {found.error && <p className="note bad-note">{found.error}</p>}
      {!found.data && !found.error && (
        <Loading
          label={`Asking ${label} to search the indexers`}
          slowHint="A live search across every indexer, which often takes half a minute or more."
        />
      )}
      {queued && <p className="note ok-note">Queued. Follow it in Library, Replacements.</p>}
      {error && <p className="note bad-note">{error}</p>}

      {found.data && (
        <>
          <div className="row wrap release-filters">
            <label>
              Order
              <select value={sort} onChange={(e) => setSort(e.target.value as SortKey)}>
                {(Object.keys(SORTS) as SortKey[]).map((key) => (
                  <option key={key} value={key}>
                    {SORTS[key].label}
                  </option>
                ))}
              </select>
            </label>
            <label>
              Resolution
              <select value={resolution} onChange={(e) => setResolution(e.target.value)}>
                <option value="">Any</option>
                {resolutions.map((r) => (
                  <option key={r} value={r}>
                    {r}
                  </option>
                ))}
              </select>
            </label>
            {protocols.length > 1 && (
              <label>
                Source
                <select value={protocol} onChange={(e) => setProtocol(e.target.value)}>
                  <option value="">Either</option>
                  {protocols.map((r) => (
                    <option key={r} value={r}>
                      {r}
                    </option>
                  ))}
                </select>
              </label>
            )}
            {biggest > 0 && (
              <label>
                At most
                <select value={maxSize} onChange={(e) => setMaxSize(Number(e.target.value))}>
                  <option value={0}>Any size</option>
                  {[5, 10, 15, 20, 30, 50].map((gb) => (
                    <option key={gb} value={gb * 1e9}>
                      {gb} GB
                    </option>
                  ))}
                </select>
              </label>
            )}
            <label className="check">
              <input type="checkbox" checked={hideHeld} onChange={(e) => setHideHeld(e.target.checked)} />
              Only ones it will import by itself
            </label>
            <label className="check">
              <input type="checkbox" checked={hideBlocked} onChange={(e) => setHideBlocked(e.target.checked)} />
              Hide what {label} would refuse
            </label>
          </div>

          <p className="muted small">
            {rows.length} of {all.length} releases. Best first means most of this file's problems solved, then{" "}
            {label}&apos;s own score against your profile. <span className="pill ok">Waits</span> is held for you to
            confirm; <span className="pill warn">Auto</span> is imported by itself.
          </p>

          {rows.length === 0 ? (
            <p className="muted">Nothing matches those filters.</p>
          ) : (
            <div className="release-tiles">
              {rows.map((r) => (
                <article key={r.guid} className={r.blocked ? "release-tile blocked" : "release-tile"}>
                  <header>
                    <strong className="clip" title={r.title}>
                      {r.title}
                    </strong>
                    <span className="row wrap release-badges">
                      {r.parsed.resolution && <span className="pill">{r.parsed.resolution}</span>}
                      {r.parsed.source && <span className="pill">{r.parsed.source}</span>}
                      {r.parsed.video_codec && <span className="pill">{r.parsed.video_codec}</span>}
                      {r.parsed.hdr && <span className="pill">{r.parsed.hdr}</span>}
                      {r.parsed.audio_codec && (
                        <span className="pill">
                          {r.parsed.audio_codec}
                          {r.parsed.audio_channels ? ` ${r.parsed.audio_channels}ch` : ""}
                        </span>
                      )}
                      <span className={r.held ? "pill ok" : "pill warn"}>{r.held ? "Waits" : "Auto"}</span>
                    </span>
                  </header>

                  {r.fixes.length > 0 && (
                    <ul className="release-fixes">
                      {r.fixes.map((fix) => (
                        <li key={fix}>{fix}</li>
                      ))}
                    </ul>
                  )}

                  <dl className="release-facts">
                    <div>
                      <dt>Size</dt>
                      <dd>{size(r.size)}</dd>
                    </div>
                    <div>
                      <dt>Bitrate</dt>
                      <dd>{mbps(r.estimated_bitrate)}</dd>
                    </div>
                    <div>
                      <dt>Profile score</dt>
                      <dd>{r.custom_format_score ?? "0"}</dd>
                    </div>
                    <div>
                      <dt>Seeders</dt>
                      <dd>{r.seeders ?? "n/a"}</dd>
                    </div>
                    <div>
                      <dt>Age</dt>
                      <dd>{r.age_days == null ? "?" : `${r.age_days} d`}</dd>
                    </div>
                    <div>
                      <dt>From</dt>
                      <dd className="clip">{r.indexer ?? "?"}</dd>
                    </div>
                  </dl>

                  {(r.custom_formats?.length ?? 0) > 0 && (
                    <p className="muted small clip">{r.custom_formats?.join(", ")}</p>
                  )}
                  {r.rejections.length > 0 && (
                    <p className="muted small">{r.rejections.join(". ")}</p>
                  )}

                  <button className="btn" disabled={Boolean(queued)} onClick={() => queue(r)}>
                    {queued === r.guid ? "Queued" : "Download this"}
                  </button>
                </article>
              ))}
            </div>
          )}
        </>
      )}
    </dialog>
  );
}


function differs(a: string | null | undefined, b: string | null | undefined): boolean {
  if (!a || !b) return false;
  const x = a.toLowerCase().trim();
  const y = b.toLowerCase().replace(/^about /, "").trim();
  return !(x === y || x.startsWith(y) || y.startsWith(x));
}

const REPLACEMENT_STATUS: Record<Replacement["status"], { label: string; tone: string }> = {
  queued: { label: "Queued", tone: "pill" },
  downloading: { label: "Downloading", tone: "pill" },
  ready: { label: "Ready for you", tone: "pill warn" },
  importing: { label: "Importing", tone: "pill" },
  imported: { label: "Replaced", tone: "pill ok" },
  imported_automatically: { label: "Imported by itself", tone: "pill ok" },
  denied: { label: "Denied", tone: "pill" },
  failed: { label: "Failed", tone: "pill bad" },
};

const ACTIVE_STATUSES = ["queued", "downloading", "ready", "importing"];

/* Everything being done to a file, in one place.
 *
 * Tidying a file's tracks and replacing it with a better copy are the same job
 * from where you are standing: something is being changed about a file and you
 * want to know how far along it is. They used to live on different pages, one
 * of them as a banner above an unrelated list, so neither was anywhere you
 * would go looking.
 */
function RemediationQueue() {
  const list = useApi<Replacement[]>("/library/replacements");
  const [tab, setTab] = useState<"active" | "history">("active");
  const rows = list.data ?? [];
  const current = rows.filter((r) => ACTIVE_STATUSES.includes(r.status));
  const past = rows.filter((r) => !ACTIVE_STATUSES.includes(r.status));
  useEffect(() => {
    if (current.length === 0) return;
    const timer = setInterval(list.reload, 15000);
    return () => clearInterval(timer);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [current.length]);
  if (list.error) return <p className="note bad-note">{list.error}</p>;
  if (!list.data) return <Loading label="Reading replacements" />;
  const shown = tab === "active" ? current : past;
  return (
    <>
      <div className="row-between">
        <p className="muted">
          Everything being done to a file: tracks being tidied, and copies being replaced. Radarr and Sonarr import an
          upgrade by themselves; anything else waits here once downloaded, beside the current file, for you to confirm
          or deny. Finished work moves to History.
        </p>
        <div className="segmented">
          <button className={tab === "active" ? "seg on" : "seg"} onClick={() => setTab("active")}>
            Active {current.length}
          </button>
          <button className={tab === "history" ? "seg on" : "seg"} onClick={() => setTab("history")}>
            History {past.length}
          </button>
        </div>
      </div>

      <TidyJobs scope={tab} />
      {shown.length > 0 && <h3 className="section-head">{tab === "active" ? "Replacing files" : "Replaced"}</h3>}
      {shown.length === 0 && (
        <p className="muted">
          {tab === "active"
            ? "Nothing being replaced. Open a file in any list and choose Find a replacement, or Tidy its tracks."
            : "Nothing replaced yet."}
        </p>
      )}
      <div className="mini-list">
        {shown.map((r) =>
          tab === "active" ? <ReplacementRow key={r.id} r={r} onChanged={list.reload} /> : <PastReplacement key={r.id} r={r} />,
        )}
      </div>
    </>
  );
}

/* A finished replacement, one line, opening to its comparison. */
function PastReplacement({ r }: { r: Replacement }) {
  const [open, setOpen] = useState(false);
  const status = REPLACEMENT_STATUS[r.status];
  return (
    <div>
      <button className={open ? "mini mini-button on" : "mini mini-button"} onClick={() => setOpen(!open)} aria-expanded={open}>
        <div className="min0">
          <strong>{r.title}</strong> <span className={status.tone}>{status.label}</span>
          <p className="muted small release-title">{r.release?.title}</p>
          {r.status === "failed" && r.message && <p className="small danger-text">{r.message}</p>}
        </div>
        <span className="muted small">
          {r.updated_at ? new Date(/[zZ]|[+-]\d\d:\d\d$/.test(r.updated_at) ? r.updated_at : `${r.updated_at}Z`).toLocaleDateString() : ""}
          {r.resolved_by ? ` \u00b7 ${r.resolved_by}` : ""}
        </span>
      </button>
      {open && <ReplacementRow r={r} onChanged={() => undefined} />}
    </div>
  );
}

function ReplacementRow({ r: stored, onChanged }: { r: Replacement; onChanged: () => void }) {
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  // What Radarr or Sonarr says right now: its queue entry and history, asked
  // directly while this row is on screen, every 10 seconds while it is active.
  const [fresh, setFresh] = useState<(Replacement & { live: Live }) | null>(null);
  const [checking, setChecking] = useState(false);
  const r = fresh ?? stored;
  const active = ["queued", "downloading", "ready", "importing"].includes(r.status);

  async function refresh() {
    setChecking(true);
    try {
      const next = await api.get<Replacement & { live: Live }>(`/library/replacements/${stored.id}/live`);
      if (next.status !== r.status) onChanged();
      setFresh(next);
      setError(null);
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setChecking(false);
    }
  }

  useEffect(() => {
    if (!active) return;
    refresh();
    const timer = setInterval(refresh, 10000);
    return () => clearInterval(timer);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [stored.id, active]);
  const status = REPLACEMENT_STATUS[r.status];
  const service = r.service === "sonarr" ? "Sonarr" : "Radarr";

  async function decide(confirmIt: boolean) {
    const question = confirmIt
      ? `Import the new file for ${r.title}? ${service} replaces the current file (into its recycle bin, if you have one set).`
      : `Deny this replacement for ${r.title}? The download is deleted and the release is blocked in ${service}.`;
    if (!confirm(question)) return;
    setBusy(true);
    setError(null);
    try {
      await api.post(`/library/replacements/${r.id}/${confirmIt ? "confirm" : "deny"}`);
      onChanged();
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setBusy(false);
    }
  }

  const cur = r.current;
  const next = r.candidate?.parsed ?? r.release?.parsed;
  const imported = r.candidate?.imported;
  const rows: [string, string | null | undefined, string | null | undefined][] = cur
    ? [
        ["Resolution", cur.video_resolution, imported?.resolution ?? next?.resolution],
        ["Video", [cur.video_codec?.toUpperCase(), cur.video_bit_depth ? `${cur.video_bit_depth}-bit` : null].filter(Boolean).join(" "),
          [(imported?.video_codec ?? next?.video_codec)?.toUpperCase(), (imported?.bit_depth ?? next?.bit_depth) ? `${imported?.bit_depth ?? next?.bit_depth}-bit` : null].filter(Boolean).join(" ")],
        ["HDR", cur.video_dynamic_range, imported?.hdr ?? next?.hdr ?? "SDR"],
        ["Audio", (cur.audio_tracks ?? []).map((t) => `${t.codec?.toUpperCase()}${t.channels ? ` ${CHANNELS[t.channels] ?? t.channels}` : ""}`).join(", "),
          imported?.audio_codec ? `${imported.audio_codec} ${imported.audio_channels ?? ""}`.trim() :
          next?.audio_codec ? `${next.audio_codec.toUpperCase()}${next.audio_channels ? ` ${CHANNELS[next.audio_channels] ?? ""}` : ""}` : null],
        ["Subtitles", (cur.subtitle_tracks ?? []).map((t) => t.codec?.toUpperCase()).join(", ") || "none", imported?.subtitles ?? null],
        ["Size", size(cur.file_size), size(imported?.size ?? r.candidate?.size ?? r.release?.size)],
        ["Bitrate", mbps(cur.file_bitrate), r.release?.estimated_bitrate ? `about ${mbps(r.release.estimated_bitrate)}` : null],
        ["Quality", null, imported?.quality ?? r.candidate?.quality ?? r.release?.quality],
      ]
    : [];
  const showCompare = ["ready", "importing", "imported", "imported_automatically"].includes(r.status);

  return (
    <div className="replacement">
      <div className="row-between">
        <div className="min0">
          <strong>{r.title}</strong> <span className={status.tone}>{status.label}</span>
          <p className="muted small release-title">{r.release?.title}</p>
        </div>
        {r.status === "ready" && (
          <div className="row">
            <button className="btn danger" onClick={() => decide(false)} disabled={busy}>
              Deny
            </button>
            <button className="btn primary" onClick={() => decide(true)} disabled={busy}>
              Confirm
            </button>
          </div>
        )}
        {(r.status === "queued" || r.status === "downloading") && (
          <button className="tab danger-text" onClick={() => decide(false)} disabled={busy}>
            Cancel
          </button>
        )}
        {r.status === "failed" && (
          <button className="tab" onClick={refresh} disabled={checking}>
            {checking ? "Checking\u2026" : "Show what happened"}
          </button>
        )}
      </div>
      {stepOf(r.status) >= 0 && (
        <ol className="steps">
          {STEPS.map((step, i) => (
            <li key={step.key} className={i < stepOf(r.status) ? "done" : i === stepOf(r.status) ? "now" : undefined}>
              {step.label}
            </li>
          ))}
        </ol>
      )}
      {(r.status === "downloading" || fresh?.live.queue?.progress != null) && (fresh?.live.queue?.progress ?? r.progress) != null && (
        <div className="download-progress" title={`${Math.round((fresh?.live.queue?.progress ?? r.progress ?? 0) * 100)}%`}>
          <span style={{ width: `${Math.round((fresh?.live.queue?.progress ?? r.progress ?? 0) * 100)}%` }} />
        </div>
      )}
      <div className="row wrap live-line">
        <span className="muted small">
          {fresh?.live.queue
            ? [
                `${service}: ${fresh.live.queue.state ?? fresh.live.queue.status ?? "in the queue"}`,
                fresh.live.queue.progress != null ? `${Math.round(fresh.live.queue.progress * 100)}%` : null,
                fresh.live.queue.time_left ? `${fresh.live.queue.time_left} left` : null,
                fresh.live.queue.client,
              ]
                .filter(Boolean)
                .join(" \u00b7 ")
            : fresh
              ? `Not in ${service}'s queue`
              : null}
          {`${fresh ? " \u00b7 " : ""}checked ${ago(fresh?.live.checked_at ?? r.checked_at)}`}
        </span>
        <button className="tab" onClick={refresh} disabled={checking}>
          {checking ? "Checking\u2026" : "Refresh"}
        </button>
      </div>
      {fresh?.live.queue?.messages && fresh.live.queue.messages.length > 0 && (
        <p className="muted small">{fresh.live.queue.messages.join("; ")}</p>
      )}
      {fresh && fresh.live.events.length > 0 && (
        <ul className="arr-events">
          {fresh.live.events.map((e, i) => (
            <li key={i} className={e.type?.toLowerCase().includes("fail") ? "bad" : undefined}>
              <span className="muted small">{e.date ? new Date(e.date).toLocaleString() : ""}</span> <strong>{e.label}</strong>
              {e.message && <span className="small"> {e.message}</span>}
            </li>
          ))}
        </ul>
      )}
      {r.release?.fixes && r.release.fixes.length > 0 && (
        <div className="row wrap file-badges">
          {r.release.fixes.map((f) => (
            <span key={f} className="pill ok">
              {f}
            </span>
          ))}
        </div>
      )}
      {showCompare && rows.length > 0 && (
        <table className="table compare">
          <thead>
            <tr>
              <th />
              <th>Current file</th>
              <th>{imported ? "Now" : "Replacement"}</th>
            </tr>
          </thead>
          <tbody>
            {rows.map(([name, a, b]) => (
              <tr key={name} className={differs(a, b) ? "changed" : undefined}>
                <td className="muted">{name}</td>
                <td>{a || <span className="muted">not known</span>}</td>
                <td>{b || <span className="muted">not known</span>}</td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
      {r.status === "ready" && !imported && (
        <p className="muted small">
          The replacement's formats are read from its file name until it is imported.
          {r.candidate?.rejections?.length ? ` ${service} says: ${r.candidate.rejections.join("; ")}.` : ""}
        </p>
      )}
      {r.message && !(r.candidate?.rejections ?? []).some((x) => r.message?.includes(x)) && (
        <p className="muted small">{r.message}</p>
      )}
      {error && <p className="note bad-note">{error}</p>}
    </div>
  );
}


/* Storage: which mount each file sits on, and how watching from it goes.
 *
 * A library can span an array share and a network SSD, and until now nothing
 * here knew the difference, so a file that stalls could not be traced to the
 * box it lives on. Mounts are read from the file paths, and two mounts given
 * the same name are treated as one store, which is how several shares off one
 * NAS read together. */
type Store = {
  store: string;
  roots: string[];
  files: number;
  size: number;
  plays: number;
  remote_plays: number;
  transcodes: number;
  stalls: number;
  average_bitrate: number | null;
  stalls_per_100: number | null;
  transcode_percent: number | null;
};

type StorePoint = {
  week: string;
  plays: number;
  stalls: number | null;
  stalled_streams: number | null;
  stalled_percent: number | null;
  partial: boolean;
};

type StoreCount = { name: string; events: number; streams: number };

type StoreTrouble = {
  store: string;
  days: number;
  events: number;
  streams: number;
  remote: number;
  local: number;
  transcoded: number;
  people: StoreCount[];
  devices: StoreCount[];
  titles: StoreCount[];
  causes: StoreCount[];
  notes: string[];
};

type StoreTrend = {
  store: string;
  points: StorePoint[];
  worst: number | null;
  direction: "worse" | "steady" | "better" | null;
};

function StorageSection({ days }: { days: number }) {
  const data = useApi<{ stores: Store[]; days: number; depth: number }>(`/library/stores?days=${days}`, [days]);
  const [naming, setNaming] = useState<string | null>(null);
  const [asking, setAsking] = useState<string | null>(null);
  const [name, setName] = useState("");
  const [error, setError] = useState<string | null>(null);

  async function save(store: Store) {
    setError(null);
    try {
      // Every mount in this store takes the name, so they stay together.
      await Promise.all(store.roots.map((root) => api.put(`/library/stores${root}`, { label: name })));
      setNaming(null);
      data.reload();
    } catch (err) {
      setError((err as Error).message);
    }
  }

  if (data.error) return <p className="note bad-note">{data.error}</p>;
  if (!data.data) return <Loading label="Reading storage" />;
  const stores = data.data.stores;
  // Worth saying only when one store is clearly worse than the rest put
  // together, and only where enough has been watched from it to mean anything.
  const used = stores.filter((s) => s.plays >= 20);
  const worst = [...used].sort((x, y) => (y.stalls_per_100 ?? 0) - (x.stalls_per_100 ?? 0))[0];
  const others = used.filter((s) => s !== worst);
  const elsewhere = others.reduce((sum, s) => sum + s.stalls, 0);
  const elsewherePlays = others.reduce((sum, s) => sum + s.plays, 0);
  const elsewhereRate = elsewherePlays ? Math.round((elsewhere / elsewherePlays) * 1000) / 10 : null;

  return (
    <>
      <p className="muted">
        Where each file is, read from the paths Plex reports. Give two mounts the same name and they count as one
        store, which is how several shares off one box read together.
      </p>
      {error && <p className="note bad-note">{error}</p>}
      {worst && elsewhereRate != null && (worst.stalls_per_100 ?? 0) > elsewhereRate * 2 && (
        <p className="note">
          Watching from <strong>{worst.store}</strong> stalls {worst.stalls_per_100} times per 100 plays, against{" "}
          {elsewhereRate} everywhere else. Open <strong>Why</strong> beside it before blaming the storage: stalls from
          viewers outside the house usually are not the disk.
        </p>
      )}
      <table className="table">
        <thead>
          <tr>
            <th>Store</th>
            <th className="num">Files</th>
            <th className="num">Size</th>
            <th className="num">Average bitrate</th>
            <th className="num">Plays, {days} days</th>
            <th className="num">Transcoded</th>
            <th className="num">Stalls per 100</th>
            <th />
          </tr>
        </thead>
        <tbody>
          {stores.map((s) => [
            <tr key={s.store}>
              <td>
                {naming === s.store ? (
                  <span className="row">
                    <input value={name} onChange={(e) => setName(e.target.value)} placeholder="Array, SSD NAS" />
                    <button className="btn" onClick={() => save(s)}>
                      Save
                    </button>
                  </span>
                ) : (
                  <>
                    <strong>{s.store}</strong>
                    <div className="muted small">{s.roots.join(", ")}</div>
                  </>
                )}
              </td>
              <td className="num">{s.files.toLocaleString()}</td>
              <td className="num">{size(s.size)}</td>
              <td className="num">{mbps(s.average_bitrate)}</td>
              <td className="num">
                {s.plays.toLocaleString()}
                {s.plays > 0 && <div className="muted small">{s.remote_plays} remote</div>}
              </td>
              <td className="num">{s.transcode_percent == null ? "" : `${s.transcode_percent}%`}</td>
              <td className="num">{s.stalls_per_100 == null ? "" : s.stalls_per_100}</td>
              <td>
                <span className="row">
                  {s.stalls > 0 && (
                    <button
                      className="tab"
                      title="What the stalling here is made of"
                      onClick={() => setAsking(asking === s.store ? null : s.store)}
                    >
                      {asking === s.store ? "Hide" : "Why"}
                    </button>
                  )}
                  <button
                    className="tab"
                    onClick={() => {
                      setNaming(naming === s.store ? null : s.store);
                      setName(s.store.startsWith("/") ? "" : s.store);
                    }}
                  >
                    {naming === s.store ? "Cancel" : "Name"}
                  </button>
                </span>
              </td>
            </tr>,
            asking === s.store ? (
              <tr key={`${s.store}-why`} className="store-why-row">
                <td colSpan={8}>
                  <StoreTroublePanel store={s.store} days={days} />
                </td>
              </tr>
            ) : null,
          ]).flat().filter(Boolean)}
        </tbody>
      </table>
      <StoreTrends />
    </>
  );
}

/* What the stalling at one store is made of.
 *
 * A bad number beside a mount is not proof of bad storage. The same number
 * comes from a disk that cannot keep up, from one household on a poor line,
 * and from one enormous new film. Stalls on your own network are the first
 * kind; stalls from outside the house are usually not.
 */
function StoreTroublePanel({ store, days }: { store: string; days: number }) {
  const data = useApi<StoreTrouble>(
    `/library/stores/trouble?store=${encodeURIComponent(store)}&days=${days}`,
    [store, days],
  );
  if (data.error) return <p className="note bad-note">{data.error}</p>;
  if (!data.data) return <Loading label="Reading the stalls" />;
  const t = data.data;
  if (t.events === 0) return <p className="muted small">Nothing has stalled here in {days} days.</p>;
  const lists: [string, StoreCount[]][] = [
    ["Who", t.people],
    ["On what", t.devices],
    ["Which titles", t.titles],
  ];
  return (
    <div className="store-why">
      <p className="muted small">
        {t.events} {t.events === 1 ? "stall" : "stalls"} across {t.streams}{" "}
        {t.streams === 1 ? "stream" : "streams"}, {days} days
        {t.transcoded > 0 ? `, ${t.transcoded} while transcoding` : ""}.
      </p>
      {t.notes.length > 0 && (
        <p className="note">
          {t.notes.map((n, i) => (
            <span key={n}>
              {i > 0 ? " " : ""}
              {n.endsWith(".") ? n : `${n}.`}
            </span>
          ))}
        </p>
      )}
      <div className="store-why-lists">
        {lists.map(([label, rows]) => (
          <div key={label} className="min0">
            <p className="muted small">{label}</p>
            {rows.length === 0 && <p className="muted small">Not recorded</p>}
            {rows.map((r) => (
              <div key={r.name} className="store-why-row-item">
                <span className="store-why-name">{r.name}</span>
                <span className="muted small">
                  {r.events} {r.events === 1 ? "stall" : "stalls"}
                  {r.streams > 1 ? `, ${r.streams} streams` : ""}
                </span>
              </div>
            ))}
          </div>
        ))}
      </div>
    </div>
  );
}

/* Whether a store has always been like this.
 *
 * The table above is a snapshot, and a snapshot cannot tell a disk going bad
 * from one bad evening. This is the share of plays that stalled at all, week
 * by week, per store: one stream that rebuffers all night is one bad stream,
 * so the number stays something anybody can read.
 */
const WHICH_WAY: Record<string, string> = {
  worse: "Getting worse",
  better: "Getting better",
  steady: "Steady",
};

function StoreTrends() {
  const data = useApi<{ stores: StoreTrend[]; weeks: number; recording_from: string | null }>("/library/stores/trend");
  if (data.error) return null;
  if (!data.data) return <Loading label="Reading the weeks" />;
  const shown = data.data.stores.filter((s) => s.points.some((p) => p.stalled_percent != null));
  if (shown.length === 0) {
    return (
      <p className="muted small">
        Nothing to compare week to week yet. Stalls are counted from the day this app started watching live streams,
        and a week needs ten plays from a store before its share means anything.
      </p>
    );
  }
  const since = data.data.recording_from;
  const weeks = shown[0].points.filter((p) => p.stalled_percent != null).length;
  return (
    <>
      <h3 className="section-head">Week by week</h3>
      <p className="muted small">
        The share of plays that stalled at all, per week.
        {since && weeks < data.data.weeks
          ? ` Counted since ${new Date(`${since}T00:00:00`).toLocaleDateString()}, so this fills out over the coming weeks.`
          : ""}
      </p>
      <div className="store-trends">
        {shown.map((s) => (
          <div key={s.store} className="store-trend">
            <div className="min0">
              <strong>{s.store}</strong>
              <p className="muted small">
                {s.direction ? WHICH_WAY[s.direction] : "Too early to say"}
                {s.worst != null ? ` · worst week ${s.worst}%` : ""}
              </p>
            </div>
            <StallSpark points={s.points} />
          </div>
        ))}
      </div>
    </>
  );
}

/* The same drawn-by-hand approach as the dashboard's sparkline, with two
   differences: weeks nobody was counting are a gap rather than a zero, and
   the week in progress is a hollow point because it is not over yet. */
function StallSpark({ points }: { points: StorePoint[] }) {
  const known = points.filter((p) => p.stalled_percent != null);
  if (known.length < 2) {
    const one = known[0];
    return <span className="muted small">{one ? `${one.stalled_percent}% this week` : "not enough weeks yet"}</span>;
  }
  const width = 220;
  const height = 40;
  const top = Math.max(...known.map((p) => p.stalled_percent as number), 5);
  // The weeks before anything was counted are not drawn at all, so two known
  // weeks span the box instead of huddling at the right hand end. Gaps in the
  // middle stay gaps, because a week nobody watched is not a week of nothing.
  const from = points.findIndex((p) => p.stalled_percent != null);
  const span = Math.max(points.length - 1 - from, 1);
  const at = (p: StorePoint, i: number) => [
    ((i - from) / span) * width,
    height - ((p.stalled_percent as number) / top) * height,
  ];
  let path = "";
  points.forEach((p, i) => {
    if (p.stalled_percent == null) return;
    const [x, y] = at(p, i);
    path += `${path ? "L" : "M"} ${x.toFixed(1)} ${y.toFixed(1)} `;
  });
  const last = known[known.length - 1];
  const lastIndex = points.lastIndexOf(last);
  const [lx, ly] = at(last, lastIndex);
  return (
    <span className="store-spark-wrap">
      <svg className="spark store-spark" viewBox={`0 0 ${width} ${height}`} preserveAspectRatio="none" role="img"
           aria-label={`Plays that stalled per week, worst ${top}%`}>
        <path d={path} className="spark-line" />
        <circle cx={lx} cy={ly} r={2.5} className={last.partial ? "spark-dot open" : "spark-dot"} />
      </svg>
      <span className="muted small">{last.stalled_percent}%</span>
    </span>
  );
}


/* Stalls recorded before this app could tell a skip from buffering.
 *
 * Jumping forward in a film and reaching the end of an episode both looked
 * like buffering, and the poll by poll positions that would sort them out now
 * were never kept. So they are offered plainly: they are in the numbers, they
 * flatter nobody, and one button forgets them. */
function OldStalls() {
  const old = useApi<{ count: number; since: string; newest: string | null }>("/library/stalls/unfiltered");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  if (!old.data?.count) return null;

  return (
    <p className="note warn-note">
      {old.data.count.toLocaleString()} stalls were recorded before {old.data.since}, when skipping and the end of an
      episode still counted as buffering. They cannot be sorted out now, so they make every stall figure look worse
      than it was.{" "}
      {error && <span className="danger-text">{error} </span>}
      <button
        className="btn"
        disabled={busy}
        onClick={async () => {
          if (!window.confirm(`Forget ${old.data!.count} stalls recorded before ${old.data!.since}? This cannot be undone.`)) return;
          setBusy(true);
          setError(null);
          try {
            await api.del("/library/stalls/unfiltered");
            old.reload();
          } catch (err) {
            setError((err as Error).message);
          } finally {
            setBusy(false);
          }
        }}
      >
        Forget them
      </button>
    </p>
  );
}


/* The library as a wall of posters, sorted by whatever is wrong today.
 *
 * Everything on a tile is something the app can already prove: it stalled for
 * somebody, it was transcoded for most of the people watching remotely, its
 * audio had to be converted, nobody has ever played it. Press one and the
 * whole file card opens, with the same actions as anywhere else.
 */
type Tile = {
  rating_key: number;
  title: string;
  year: number | null;
  media_type: string | null;
  video_resolution: string | null;
  file_bitrate: number | null;
  file_size: number | null;
  gb_per_hour: number;
  hours: number;
  languages: string[];
  section: string | null;
  store: string;
  plays: number;
  remote_plays: number;
  last_play: number | null;
  stalls: number;
  transcode_percent: number;
  marks: string[];
};

type BrowseList = {
  items: Tile[];
  total: number;
  size: number;
  sort: string;
  sorts: { key: string; label: string }[];
  sections: { section_id: number; name: string }[];
  languages: string[];
  resolutions: string[];
  marks: string[];
};

const MARKS: Record<string, { label: string; tone: string; why: string }> = {
  stalls: { label: "Stalled", tone: "pill bad", why: "Somebody's stream stopped to buffer on this" },
  transcoded: { label: "Transcoded", tone: "pill warn", why: "Converted for most of the people watching remotely" },
  heavy: { label: "Heavy", tone: "pill warn", why: "Above your problem bitrate, and watched from outside the house" },
  audio: { label: "Audio", tone: "pill", why: "Audio no common device can play, or that had to be converted" },
  subtitles: { label: "Subtitles", tone: "pill", why: "Picture or styled subtitles, or a pile of duplicates" },
  container: { label: "Container", tone: "pill", why: "An old container" },
  unwatched: { label: "Unwatched", tone: "pill", why: "Nobody has played it in this window" },
};

function poster(ratingKey: number, width = 200): string {
  return `/api/media/${ratingKey}/image?width=${width}&height=${Math.round(width * 1.5)}`;
}

function Browse({ days }: { days: number }) {
  const [sort, setSort] = useState(() => localStorage.getItem("browse.sort") ?? "per_hour");
  const [kind, setKind] = useState(() => localStorage.getItem("browse.kind") ?? "movie");
  const [problem, setProblem] = useState(() => localStorage.getItem("browse.problem") ?? "");
  const [resolution, setResolution] = useState(() => localStorage.getItem("browse.resolution") ?? "");
  const [sectionId, setSectionId] = useState(() => localStorage.getItem("browse.section") ?? "");
  const [language, setLanguage] = useState(() => localStorage.getItem("browse.language") ?? "");
  const [search, setSearch] = useState("");
  const [perHour, setPerHour] = useState(() => Number(localStorage.getItem("browse.perHour") ?? 0));
  const [asTiles, setAsTiles] = useState(() => localStorage.getItem("browse.tiles") !== "off");
  const [chosen, setChosen] = useState<Set<number>>(new Set());
  const [message, setMessage] = useState<{ text: string; ok: boolean } | null>(null);
  const [busy, setBusy] = useState(false);
  const [open, setOpen] = useState<number | null>(null);

  function remember(key: string, value: string, set: (v: string) => void) {
    set(value);
    localStorage.setItem(`browse.${key}`, value);
  }

  const query = new URLSearchParams({ days: String(days), sort, limit: "60" });
  if (perHour) query.set("min_gb_per_hour", String(perHour));
  if (kind) query.set("media_type", kind);
  if (problem) query.set("problem", problem);
  if (resolution) query.set("resolution", resolution);
  if (sectionId) query.set("section_id", sectionId);
  if (language) query.set("language", language);
  if (search.trim()) query.set("search", search.trim());
  const data = useApi<BrowseList>(`/library/browse?${query}`, [days, sort, kind, problem, resolution, sectionId, language, search, perHour]);

  function choose(key: number, on: boolean) {
    const next = new Set(chosen);
    if (on) next.add(key);
    else next.delete(key);
    setChosen(next);
  }

  async function tag() {
    const keys = [...chosen];
    if (!confirm(`Tag ${keys.length} ${keys.length === 1 ? "title" : "titles"} in Radarr or Sonarr for replacement?\n\nNothing is downloaded and nothing is deleted. The tag is a shortlist you can work through later.`)) return;
    setBusy(true);
    setMessage(null);
    try {
      const r = await api.post<{ tagged: number; failed: { rating_key: number; why: string }[] }>(
        "/library/big/tag",
        { keys },
      );
      setMessage({
        text: `Tagged ${r.tagged}.${r.failed.length ? ` ${r.failed.length} could not be: ${r.failed[0].why}` : ""}`,
        ok: r.failed.length === 0,
      });
      setChosen(new Set());
    } catch (err) {
      setMessage({ text: (err as Error).message, ok: false });
    } finally {
      setBusy(false);
    }
  }

  if (data.error) return <p className="note bad-note">{data.error}</p>;

  return (
    <>
      <p className="muted">
        Everything in the library, with what is wrong on each. Sort by the trouble you are chasing today; press a
        poster for the whole file, its findings and what can be done about it.
      </p>

      <div className="row wrap big-filters">
        <label>
          Sort by
          <select value={sort} onChange={(e) => remember("sort", e.target.value, setSort)}>
            {(data.data?.sorts ?? []).map((s) => (
              <option key={s.key} value={s.key}>
                {s.label}
              </option>
            ))}
          </select>
        </label>
        <label>
          Showing
          <select value={problem} onChange={(e) => remember("problem", e.target.value, setProblem)}>
            <option value="">Everything</option>
            {(data.data?.marks ?? []).map((m) => (
              <option key={m} value={m}>
                {MARKS[m]?.label ?? m}
              </option>
            ))}
          </select>
        </label>
        <label>
          Kind
          <select value={kind} onChange={(e) => remember("kind", e.target.value, setKind)}>
            <option value="movie">Films</option>
            <option value="episode">Episodes</option>
            <option value="">Both</option>
          </select>
        </label>
        <label>
          Resolution
          <select value={resolution} onChange={(e) => remember("resolution", e.target.value, setResolution)}>
            <option value="">Any</option>
            {(data.data?.resolutions ?? []).map((r) => (
              <option key={r} value={r}>
                {r}
              </option>
            ))}
          </select>
        </label>
        <label>
          Library
          <select value={sectionId} onChange={(e) => remember("section", e.target.value, setSectionId)}>
            <option value="">All</option>
            {(data.data?.sections ?? []).map((x) => (
              <option key={x.section_id} value={x.section_id}>
                {x.name}
              </option>
            ))}
          </select>
        </label>
        <label>
          Audio language
          <select value={language} onChange={(e) => remember("language", e.target.value, setLanguage)}>
            <option value="">Any</option>
            {(data.data?.languages ?? []).map((l) => (
              <option key={l} value={l}>
                {l}
              </option>
            ))}
          </select>
        </label>
        <label>
          At least
          <select
            value={perHour}
            onChange={(e) => {
              setPerHour(Number(e.target.value));
              localStorage.setItem("browse.perHour", e.target.value);
            }}
          >
            {[0, 3, 4, 5, 6, 8, 10].map((n) => (
              <option key={n} value={n}>
                {n === 0 ? "any size" : `${n} GB an hour`}
              </option>
            ))}
          </select>
        </label>
        <label>
          Search
          <input value={search} placeholder="Title" onChange={(e) => setSearch(e.target.value)} />
        </label>
        <div className="segmented">
          {([["posters", true], ["list", false]] as [string, boolean][]).map(([label, tiles]) => (
            <button
              key={label}
              className={asTiles === tiles ? "seg on" : "seg"}
              onClick={() => {
                setAsTiles(tiles);
                localStorage.setItem("browse.tiles", tiles ? "on" : "off");
              }}
            >
              {label}
            </button>
          ))}
        </div>
      </div>

      {!data.data && <Loading label="Reading the library" />}
      {data.data && (
        <p className="note">
          {data.data.total.toLocaleString()} {data.data.total === 1 ? "title" : "titles"}, {size(data.data.size)}.
          {data.data.items.length < data.data.total ? ` Showing the first ${data.data.items.length}.` : ""}
        </p>
      )}

      {message && <p className={message.ok ? "note" : "note bad-note"}>{message.text}</p>}
      {chosen.size > 0 && (
        <div className="row wrap">
          <button className="btn" disabled={busy} onClick={tag}>
            {busy ? "Tagging..." : `Tag ${chosen.size} in Radarr or Sonarr`}
          </button>
          <button className="tab" onClick={() => setChosen(new Set())}>
            Clear
          </button>
        </div>
      )}

      {!asTiles && (
        <div className="file-list">
          {(data.data?.items ?? []).map((row) => (
            <div key={row.rating_key} className="big-row">
              <label className="check big-pick">
                <input
                  type="checkbox"
                  checked={chosen.has(row.rating_key)}
                  onChange={(e) => choose(row.rating_key, e.target.checked)}
                />
              </label>
              <div className="min0">
                <button className="linkish" onClick={() => setOpen(row.rating_key)}>
                  <strong>{row.title}</strong>
                </button>
                <p className="row wrap poster-marks">
                  {row.gb_per_hour > 0 && <span className="pill">{row.gb_per_hour} GB an hour</span>}
                  {row.video_resolution && <span className="pill">{row.video_resolution}</span>}
                  <span className="pill">{row.section ?? row.store}</span>
                  {row.languages.length > 0 && <span className="pill">{row.languages.join(", ")}</span>}
                  {row.marks.map((mark) => (
                    <span key={mark} className={MARKS[mark]?.tone ?? "pill"} title={MARKS[mark]?.why}>
                      {MARKS[mark]?.label ?? mark}
                    </span>
                  ))}
                </p>
                <p className="muted small">
                  {[mbps(row.file_bitrate), size(row.file_size), row.hours ? `${row.hours.toFixed(1)} h` : null,
                    row.plays ? `${row.plays} plays` : "never played",
                    row.stalls ? `${row.stalls} stalls` : null,
                    row.transcode_percent ? `${row.transcode_percent}% transcoded remotely` : null]
                    .filter(Boolean)
                    .join(" \u00b7 ")}
                </p>
              </div>
            </div>
          ))}
        </div>
      )}

      <div className="poster-wall" hidden={!asTiles}>
        {(data.data?.items ?? []).map((tile) => (
          <button
            key={tile.rating_key}
            className={chosen.has(tile.rating_key) ? "poster-tile picked" : "poster-tile"}
            onClick={(e) => {
              // Tick with a modifier, open with a plain press: a wall is for
              // looking through, and a shortlist is the occasional thing.
              if (e.ctrlKey || e.metaKey || e.shiftKey) choose(tile.rating_key, !chosen.has(tile.rating_key));
              else setOpen(tile.rating_key);
            }}
            title="Press to open. Ctrl or shift and press to add it to a shortlist for tagging."
          >
            <img
              src={poster(tile.rating_key)}
              alt=""
              loading="lazy"
              onError={(e) => ((e.currentTarget as HTMLImageElement).style.visibility = "hidden")}
            />
            <span className="poster-name clamp">{tile.title}</span>
            <span className="muted small">
              {[tile.video_resolution, tile.gb_per_hour ? `${tile.gb_per_hour} GB/h` : null, size(tile.file_size)]
                .filter(Boolean)
                .join(" \u00b7 ")}
            </span>
            <span className="row wrap poster-marks">
              {tile.marks.map((mark) => (
                <span key={mark} className={MARKS[mark]?.tone ?? "pill"} title={MARKS[mark]?.why}>
                  {MARKS[mark]?.label ?? mark}
                </span>
              ))}
            </span>
          </button>
        ))}
      </div>
      {data.data && data.data.items.length === 0 && <p className="muted">Nothing matches those filters.</p>}

      {open !== null && <FileDialog ratingKey={open} days={days} onClose={() => setOpen(null)} />}
    </>
  );
}

/* The whole file card, over the wall, so nothing has to be navigated to. */
function FileDialog({ ratingKey, days, onClose }: { ratingKey: number; days: number; onClose: () => void }) {
  const ref = useRef<HTMLDialogElement>(null);
  const file = useApi<FileDetail>(`/library/file/${ratingKey}?days=${days}`, [ratingKey, days]);

  useEffect(() => {
    ref.current?.showModal();
  }, []);

  return (
    <dialog ref={ref} className="dialog wide" onClose={onClose} aria-label="File">
      <div className="row-between dialog-head">
        <h2 className="min0 clip">{file.data?.title ?? "Reading"}</h2>
        <button className="icon-btn" onClick={() => ref.current?.close()} aria-label="Close">
          &times;
        </button>
      </div>
      {file.error && <p className="note bad-note">{file.error}</p>}
      {!file.data && !file.error && <Loading label="Reading the file" />}
      {file.data && <FileCardView f={file.data} days={days} />}
    </dialog>
  );
}

/* Files that are large for what they are.
 *
 * Bitrate alone does not compare: 20 Mbps is ordinary for two hours of 4K and
 * absurd for a 45 minute cartoon. Size per hour is the same number said in a
 * way that can be sorted, and it answers the question actually being asked,
 * which is "could this be half the size without looking worse".
 */
type Kept = { rating_key: number; title: string; reason: string | null; kept_by: string | null; kept_at: string | null };
type Lens = "trouble" | "messy" | "room";

type AttentionRow = FileInfo & {
  kind: Lens;
  why: string | null;
  store: string;
  plays?: number;
  remote_plays?: number;
  last_play?: number | null;
  findings?: Finding[];
};

const LENSES: { id: Lens; label: string; blurb: string }[] = [
  {
    id: "trouble",
    label: "Trouble for viewers",
    blurb: "Stalls, transcodes for most remote viewers, or a bitrate too high for the way it is watched.",
  },
  {
    id: "messy",
    label: "Awkward to play",
    blurb:
      "Audio no common device can play, subtitles only as pictures, a container from another decade, or anything "
      + "that had to be converted for the people who actually watched it.",
  },
  {
    id: "room",
    label: "Taking up room",
    blurb: "Big, and either never played, not played in years, or 4K nobody has ever been sent in 4K.",
  },
];

function Attention({ days }: { days: number }) {
  const [lens, setLens] = useState<Lens>(() => (localStorage.getItem("library.lens") as Lens) || "trouble");
  const [error, setError] = useState<string | null>(null);
  const [showKept, setShowKept] = useState(false);
  const data = useApi<{
    items: AttentionRow[];
    total: number;
    kept: number;
    reclaimable?: number;
    found?: number;
    checked?: number;
  }>(`/library/attention?kind=${lens}&days=${days}`, [lens, days]);
  const keptList = useApi<Kept[]>("/library/cleanup/kept");

  function choose(next: Lens) {
    setLens(next);
    localStorage.setItem("library.lens", next);
  }

  async function act(run: () => Promise<unknown>) {
    setError(null);
    try {
      await run();
      data.reload();
      keptList.reload();
    } catch (err) {
      setError((err as Error).message);
    }
  }

  const here = LENSES.find((l) => l.id === lens)!;

  return (
    <>
      <div className="segmented">
        {LENSES.map((l) => (
          <button key={l.id} className={lens === l.id ? "seg on" : "seg"} onClick={() => choose(l.id)}>
            {l.label}
          </button>
        ))}
      </div>
      <p className="muted">{here.blurb}</p>
      {error && <p className="note bad-note">{error}</p>}

      {data.error && <p className="note bad-note">{data.error}</p>}
      {!data.data && <Loading label="Reading the library" />}
      {data.data && data.data.items.length === 0 && (
        <p className="note">Nothing here. Either nothing qualifies, or you have kept everything that did.</p>
      )}
      {data.data && data.data.items.length > 0 && (
        <p className="note">
          {lens === "room" && data.data.reclaimable
            ? `${size(data.data.reclaimable)} across ${(data.data.found ?? data.data.total).toLocaleString()} files nobody is watching.`
            : `${data.data.total.toLocaleString()} ${data.data.total === 1 ? "file" : "files"}, worst first.`}
        </p>
      )}

      <div className="file-list">
        {(data.data?.items ?? []).map((f) => (
          <div key={f.rating_key} className="cleanup-row">
            <FileRow
              file={f}
              days={days}
              badges={[
                <span key="store" className="pill">
                  {f.store}
                </span>,
                ...(f.plays !== undefined
                  ? [
                      <span key="plays" className="pill">
                        {/* Only the room lens looks at all time, so only it can
                            honestly say never. The others count the window. */}
                        {f.plays === 0 && lens === "room"
                          ? "never played"
                          : `${f.plays} ${f.plays === 1 ? "play" : "plays"}${lens === "room" ? "" : ` in ${days} days`}`}
                      </span>,
                    ]
                  : []),
              ]}
              stats={[f.why, mbps(f.file_bitrate), size(f.file_size)]}
            />
            <div className="keep-row">
              <button
                className="linkish small"
                title="Stop this file being suggested, whichever question is asked"
                onClick={() => {
                  const why = window.prompt(`Keep ${f.title} and stop suggesting it? A reason, for the Log:`, "");
                  if (why === null) return;
                  act(() => api.post(`/library/cleanup/${f.rating_key}/keep`, { reason: why }));
                }}
              >
                Keep it, stop asking
              </button>
            </div>
          </div>
        ))}
      </div>

      {(data.data?.kept ?? 0) > 0 && (
        <p className="muted small">
          <button className="tab" onClick={() => setShowKept(!showKept)}>
            {showKept ? "Hide" : `${data.data!.kept} kept`}
          </button>
        </p>
      )}
      {showKept && (
        <div className="mini-list">
          {(keptList.data ?? []).map((k) => (
            <div key={k.rating_key} className="mini">
              <div className="min0">
                <strong>{k.title}</strong>
                <p className="muted small">
                  {[k.reason, k.kept_by ? `kept by ${k.kept_by}` : null].filter(Boolean).join(" \u00b7 ")}
                </p>
              </div>
              <button className="tab" onClick={() => act(() => api.del(`/library/cleanup/${k.rating_key}/keep`))}>
                Put it back
              </button>
            </div>
          ))}
        </div>
      )}
    </>
  );
}
