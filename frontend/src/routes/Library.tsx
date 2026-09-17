import { useState, type ReactNode } from "react";
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

type Problem = FileInfo & {
  plays: number;
  remote_plays: number;
  remote_transcodes: number;
  users: number;
  last_play: number | null;
  stalls: number;
  stall_users: number;
  causes: string[];
  reasons: string[];
  score: number;
};

type Overview = {
  titles: number;
  checked: number;
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
  titles: { rating_key: number; title: string | null; streams: number }[];
};

type Messy = {
  checked: number;
  counts: { issue: string; label: string; files: number }[];
  files: (FileInfo & { plays: number })[];
  total: number;
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

type FileDetail = FileInfo & {
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
  { id: "problems", title: "Problem files" },
  { id: "transcodes", title: "Why streams transcode" },
  { id: "messy", title: "Messy files" },
  { id: "four-k", title: "4K copies" },
  { id: "requests", title: "Requested, never watched" },
] as const;
type SectionId = (typeof SECTIONS)[number]["id"];

const REASONS: Record<string, string> = {
  over_threshold: "Over the bitrate limit, watched remotely",
  stalls: "Stalls",
  mostly_transcoded: "Transcoded for most remote viewers",
};

const ISSUE_LABELS: Record<string, string> = {
  no_compatible_audio: "No widely playable audio",
  image_subtitles_only: "Image subtitles only",
  styled_subtitles: "Styled subtitles",
  subtitle_clutter: "Subtitle clutter",
  untagged_audio: "Untagged audio",
  legacy_container: "Old container",
};

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

  return (
    <div className="settings-layout">
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
            </button>
          ))}
        </div>
      </nav>
      <div className="settings-page">
        <header className="settings-page-head row-between">
          <h2>{current.title}</h2>
          {section !== "overview" && section !== "requests" && (
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
        {section === "problems" && <Problems days={days} />}
        {section === "transcodes" && <Transcodes days={days} />}
        {section === "messy" && <MessyFiles days={days} />}
        {section === "four-k" && <FourKSection days={days} />}
        {section === "requests" && <Requests />}
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
      {pending > 0 && (
        <p className="note">
          Reading file details: {o.checked.toLocaleString()} of {o.titles.toLocaleString()} titles so far. The rest fill in
          150 at a time with each sync, so lists grow over the next few hours.
        </p>
      )}
      <dl className="stats">
        <div className="stat">
          <dt>Titles with file details</dt>
          <dd>{o.checked.toLocaleString()}</dd>
        </div>
        <div className="stat">
          <dt>Size of those files</dt>
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

function Problems({ days }: { days: number }) {
  const overview = useApi<Overview>("/library/overview");
  const [threshold, setThreshold] = useState<number | null>(null);
  const limit = threshold ?? overview.data?.threshold_mbps ?? null;
  const rows = useApi<Problem[]>(limit === null ? null : `/library/problems?days=${days}&threshold_mbps=${limit}`);
  return (
    <>
      <p className="muted">
        Files that are over the bitrate limit and watched remotely, that stall, or that most remote viewers get
        transcoded. Stalls count most, since those are what people notice.
      </p>
      <label className="inline-select">
        <span className="muted small">Bitrate limit (Mbps)</span>
        <input
          type="number"
          min={1}
          max={500}
          step={1}
          value={limit ?? ""}
          onChange={(e) => setThreshold(Number(e.target.value) || null)}
        />
        <span className="muted small">Default is set in Settings, Behaviour.</span>
      </label>
      {rows.error && <p className="note bad-note">{rows.error}</p>}
      {!rows.data && !rows.error && <Loading label="Weighing files against how they were watched" />}
      {rows.data?.length === 0 && <p className="muted">Nothing is causing trouble in this period.</p>}
      <div className="mini-list">
        {rows.data?.map((r) => (
          <FileRow
            key={r.rating_key}
            file={r}
            days={days}
            badges={r.reasons.map((x) => (
              <span key={x} className={x === "stalls" ? "pill bad" : "pill warn"}>
                {REASONS[x] ?? x}
              </span>
            ))}
            stats={[
              mbps(r.file_bitrate),
              `${r.remote_plays} remote of ${r.plays} plays`,
              r.remote_transcodes ? `${r.remote_transcodes} remote transcodes` : null,
              r.stalls ? `${r.stalls} stall${r.stalls === 1 ? "" : "s"} for ${r.stall_users} ${r.stall_users === 1 ? "person" : "people"}` : null,
              r.causes.length ? `mostly ${TRANSCODE_CAUSES[r.causes[0]]?.toLowerCase() ?? r.causes[0]}` : null,
            ]}
          />
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

function MessyFiles({ days }: { days: number }) {
  const [issue, setIssue] = useState<string | null>(null);
  const data = useApi<Messy>(`/library/messy?days=${days}${issue ? `&issue=${issue}` : ""}`);
  if (data.error) return <p className="note bad-note">{data.error}</p>;
  if (!data.data) return <Loading label="Checking every file's tracks" />;
  const m = data.data;
  return (
    <>
      <p className="muted">
        Files with something that makes them harder to play, most watched first. Of {m.checked.toLocaleString()} files
        checked so far.
      </p>
      <div className="row wrap chips">
        <button className={issue === null ? "chip on" : "chip"} onClick={() => setIssue(null)}>
          All
        </button>
        {m.counts
          .filter((c) => c.files > 0 || issue === c.issue)
          .map((c) => (
            <button key={c.issue} className={issue === c.issue ? "chip on" : "chip"} title={c.label} onClick={() => setIssue(c.issue)}>
              {ISSUE_LABELS[c.issue]} {c.files}
            </button>
          ))}
      </div>
      {m.files.length === 0 && <p className="muted">Nothing found.</p>}
      <div className="mini-list">
        {m.files.map((f) => (
          <FileRow
            key={f.rating_key}
            file={f}
            days={days}
            badges={f.issues.map((i) => (
              <span key={i} className="pill warn">
                {ISSUE_LABELS[i] ?? i}
              </span>
            ))}
            stats={[format(f), `${f.plays} plays`]}
          />
        ))}
      </div>
      {m.total > m.files.length && <p className="muted small">Showing the first {m.files.length} of {m.total}.</p>}
    </>
  );
}

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
  const nav = useNav();
  const detail = useApi<FileDetail>(`/library/file/${ratingKey}?days=${days}`);
  const [showTitle, setShowTitle] = useState(false);
  if (detail.error) return <p className="note bad-note">{detail.error}</p>;
  if (!detail.data)
    return (
      <div className="file-card">
        <Loading compact label="Reading the file" />
      </div>
    );
  const f = detail.data;
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
          <ArrActions ratingKey={f.rating_key} arr={f.arr} title={f.title} />
        </section>
      ) : (
        <p className="muted small">Nothing about this file itself stands out.</p>
      )}
      <dl className="kv">
        <div>
          <dt>Format</dt>
          <dd>{format(f) || "Not checked yet"}</dd>
        </div>
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
        <button className="btn" onClick={() => run("search")} disabled={!arr.configured || busy !== null} title={why}>
          {busy === "search" ? "Asking\u2026" : `Search for a replacement in ${arr.label}`}
        </button>
        <button className="btn" onClick={() => run("tag")} disabled={!arr.configured || busy !== null} title={why}>
          {busy === "tag" ? "Tagging\u2026" : "Tag for replacement"}
        </button>
      </div>
      {!arr.configured && <p className="muted small">{why}.</p>}
      {message && <p className={message.ok ? "note ok-note" : "note bad-note"}>{message.text}</p>}
    </div>
  )
}
