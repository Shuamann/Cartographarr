import BrandIcon from "../components/BrandIcon";
import Fact from "../components/Fact";
import GapsSection from "../components/Gaps";
import CollectionsSection from "../components/Collections";
import { ServerWorkLately } from "../components/ServerWork";
import { LINKS } from "../components/StreamDetail";
import { askConfirm, askText, tell } from "../components/Ask";
import { type ReactNode, useEffect, useMemo, useRef, useState } from "react";
import { when } from "../components/DataTable";
import Loading from "../components/Loading";
import MediaPanel from "../components/MediaPanel";
import { QUEUE_CHANGED, api, queueChanged, useApi } from "../lib/api";
import { useNav, type LibraryTarget } from "../lib/nav";
import SettingsLink, { SETTINGS_PAGES } from "../components/SettingsLink";

/* Library health: files judged by how they are actually watched.
 *
 * Every list shares one row: the title and why it is listed, opening to the
 * file itself (format, every track, where it lives) and how it has played,
 * with a jump to its plays in History.
 */

/* A track, as it is stored.
 *
 * The first four are always there. The rest are only present when Plex said
 * so, which is how Plex itself answers: a track that is not for the hard of
 * hearing simply has nothing to say about it. A file read through Tautulli
 * has only the first four, because that is all Tautulli passes on. */
type Track = {
  codec: string | null;
  channels?: number | null;
  language: string | null;
  bitrate?: number | null;
  forced?: boolean;
  location?: string | null;
  layout?: string | null;
  profile?: string | null;
  sample_rate?: number | null;
  bit_depth?: number | null;
  default?: boolean;
  title?: string | null;
  sdh?: boolean;
  dub?: boolean;
  original?: boolean;
};

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

/* What a row in any of these lists needs, which is far less than a file.
 *
 * `FileRow` draws a title, some badges, some stats and the first finding; the
 * card underneath fetches the file properly when it is opened. Typing the
 * prop as a whole FileInfo made the server send one, which was most of a 420
 * kilobyte payload for a page that draws 57. */
type RowSummary = {
  rating_key: number;
  title: string;
  finding?: string | null;
  findings_count?: number;
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
  links?: Record<string, string>;
  // Whether the library has a file under that key at all.
  in_library?: boolean;
  matched_by_id?: boolean;
  also_requested_by?: string[];
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
  { id: "gaps", title: "Missing and doubled" },
  { id: "collections", title: "Collections" },
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

/* What one step is worth, as a signed size.
 *
 * Three different answers, and they have to stay apart. Null is "the file does
 * not say what these tracks weigh", which is not the same as zero, and zero is
 * a real answer for a step that reorders tracks or rewraps the container.
 */
export function change(bytes: number | null | undefined): string {
  if (bytes === null || bytes === undefined) return "size not stated";
  if (bytes === 0) return "same size";
  return (bytes < 0 ? "\u2212" : "+") + size(Math.abs(bytes));
}

export function size(bytes: number | null | undefined): string {
  if (!bytes) return "";
  const gb = bytes / 1e9;
  return gb >= 1000 ? `${(gb / 1000).toFixed(2)} TB` : gb >= 1 ? `${gb.toFixed(1)} GB` : `${(bytes / 1e6).toFixed(0)} MB`;
}

export function mbps(kbps: number | null | undefined): string {
  return kbps ? `${(kbps / 1000).toFixed(1)} Mbps` : "";
}

export function fileFormat(f: FileInfo): string {
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

export default function Library({
  focus,
  onFocused,
}: {
  /* Somewhere to open at, from a title clicked elsewhere. Consumed once: the
     tab stays where the person leaves it afterwards. */
  focus?: LibraryTarget | null;
  onFocused?: () => void;
} = {}) {
  const [section, setSection] = useState<SectionId>("overview");
  const [days, setDays] = useState(90);
  useEffect(() => {
    if (focus) setSection("browse");
  }, [focus]);

  const current = SECTIONS.find((s) => s.id === section)!;
  const replacementList = useApi<Replacement[]>("/library/replacements");
  const tidyList = useApi<TidyJob[]>("/library/tidy/jobs?limit=30");

  // Queueing happens on one page and shows up on another, so the queue and the
  // count beside it are told rather than left to catch up on the next visit.
  useEffect(() => {
    const again = () => {
      replacementList.reload();
      tidyList.reload();
    };
    window.addEventListener(QUEUE_CHANGED, again);
    return () => window.removeEventListener(QUEUE_CHANGED, again);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  /* Which files already have something happening to them, so a list can say
   * so rather than letting somebody ask for the same replacement twice while
   * the first one is still downloading. */
  const inFlight = useMemo(() => {
    const out = new Map<number, string>();
    for (const r of tidyList.data ?? []) {
      if (r.status === "running" || r.status === "queued") out.set(r.rating_key, "tidying");
    }
    for (const r of replacementList.data ?? []) {
      if (ACTIVE_STATUSES.includes(r.status)) out.set(r.rating_key, "being replaced");
    }
    return out;
  }, [tidyList.data, replacementList.data]);
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
          {section !== "overview" && section !== "requests" && section !== "queue" && section !== "gaps" && (
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
        {section === "browse" && <Browse days={days} inFlight={inFlight} focus={focus} onFocused={onFocused} />}
        {section === "attention" && <Attention days={days} inFlight={inFlight} />}
        {section === "transcodes" && <Transcodes days={days} />}
        {section === "four-k" && <FourKSection days={days} />}
        {section === "gaps" && <GapsSection />}
        {section === "collections" && <CollectionsSection days={days} />}
        {section === "storage" && <StorageSection days={days} />}
        {section === "requests" && <Requests />}
        {section === "queue" && <RemediationQueue />}
      </div>
    </div>
  );
}

function OverviewSection({ onOpen }: { onOpen: (s: SectionId) => void }) {
  const data = useApi<Overview>("/library/overview");
  if (data.error) return <p className="note bad-note" role="alert">{data.error}</p>;
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
      <Space />
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
type SpaceReport = {
  libraries: {
    section_id: number;
    name: string;
    files: number;
    size: number;
    change_week: number | null;
    /* How long that figure actually covers. A new install has days rather
       than a week of them, and three days must not be shown as a week. */
    week_days: number | null;
    week_since: string | null;
    files_week: number | null;
    change_month: number | null;
  }[];
  total: number;
  recorded_from: string | null;
  recorded_days: number;
};

/* Gained or lost, in words.
 *
 * Null is not zero. "Nothing has changed" and "nobody wrote down what it was"
 * are different answers, and a library that reads as unchanged when the truth
 * is that there is no history yet is the kind of wrong that gets believed. */
function moved(bytes: number | null, days: number | null): { text: string; tone: string } {
  if (bytes === null) return { text: "no history yet", tone: "muted small" };
  // Under a gigabyte either way is a file being replaced, not the library
  // growing, and saying "up 0.2 GB" every week is noise.
  if (Math.abs(bytes) < 1e9) return { text: over("about the same", days), tone: "muted small" };
  return bytes > 0
    ? { text: over(`up ${size(bytes)}`, days), tone: "muted small space-up" }
    : { text: over(`down ${size(-bytes)}`, days), tone: "muted small space-down" };
}

/* A figure measured over three days is not a week's, and labelling it one
   would be the page quietly overstating what it knows. Said only while it is
   short, so an established install reads as it always has. */
function over(text: string, days: number | null): string {
  if (days === null || days >= 7) return text;
  return `${text} in ${days} ${days === 1 ? "day" : "days"}`;
}

/* What the libraries take and what is left on the disks.
 *
 * Free space belongs to the disk, not the library: two libraries on one share
 * have one answer between them, so it is reported per mount with the
 * libraries that live there named, and never added up across mounts. */
function Space() {
  const data = useApi<SpaceReport>("/library/space");
  if (data.error) return <p className="note bad-note" role="alert">{data.error}</p>;
  if (!data.data) return null;
  const s = data.data;
  if (s.libraries.length === 0) return null;
  const biggest = Math.max(...s.libraries.map((l) => l.size), 1);

  return (
    <>
      <h3>Space</h3>
      <p className="muted small">
        What each library takes, and what it has gained or lost. How much room is left belongs to the disk rather than
        the library, since two libraries on one share have one answer between them, so it is under Storage.
      </p>
      <div className="mini-list">
        {s.libraries.map((l) => {
          const week = moved(l.change_week, l.week_days);
          return (
            <div key={l.section_id} className="mini">
              <div className="min0">
                <div className="row-between">
                  <strong>{l.name}</strong>
                  <span className="muted small">{size(l.size)}</span>
                </div>
                <span className="progress space-bar">
                  <span className="progress-fill" style={{ width: `${(l.size / biggest) * 100}%` }} />
                </span>
                <p className="muted small">
                  {l.files.toLocaleString()} files{" · "}
                  <span className={week.tone}>{week.text} this week</span>
                  {l.files_week !== null && l.files_week !== 0
                    ? `, ${l.files_week > 0 ? "+" : ""}${l.files_week.toLocaleString()} files`
                    : ""}
                </p>
              </div>
            </div>
          );
        })}
      </div>

      {s.recorded_days < 8 && (
        <p className="muted small">
          {s.recorded_days === 0
            ? "Nothing is written down yet. The library scan notes what each library holds once a day, so what was gained or lost can be shown from tomorrow."
            : `${s.recorded_days} ${s.recorded_days === 1 ? "day" : "days"} written down so far, from ${s.recorded_from}. A week of them makes the weekly figure a real one.`}
        </p>
      )}
    </>
  );
}

function Transcodes({ days }: { days: number }) {
  const nav = useNav();
  const data = useApi<{
    total_streams: number;
    transcoded: number;
    hardware: number;
    enough_to_judge: boolean;
    causes: CauseRow[];
  }>(`/library/transcodes?days=${days}`);
  if (data.error) return <p className="note bad-note" role="alert">{data.error}</p>;
  if (!data.data) return <Loading label="Counting why streams transcoded" />;
  const { total_streams, transcoded, hardware, enough_to_judge, causes } = data.data;
  return (
    <>
      <p className="muted">
        Every reason a stream was not a plain direct play, read from what changed between the file and what was sent. A
        stream can have more than one. From streams seen live, so this grows from the day this version was installed.
      </p>
      <p className="small">
        <strong>{total_streams.toLocaleString()}</strong> <span className="muted">streams recorded in this period.</span>
      </p>
      {/* The app has always recorded whether a transcode was done on a GPU and
          has never said anything about it. Software transcoding spends most of
          a core on each stream; the same work on an iGPU is nearly free, which
          makes this the single most useful thing the numbers here can tell
          somebody. */}
      {enough_to_judge && hardware === 0 && (
        <p className="note warn-note">
          <strong>None of the {transcoded.toLocaleString()} transcoded streams used hardware.</strong> Every one was
          done in software, which spends most of a processor core per stream. If this server has an integrated GPU
          or a graphics card, switching on hardware acceleration in Plex under Settings, Transcoder is the single
          biggest change available here. It needs Plex Pass.
        </p>
      )}
      {enough_to_judge && hardware > 0 && hardware < transcoded && (
        <p className="note">
          {hardware.toLocaleString()} of {transcoded.toLocaleString()} transcoded streams used hardware. The rest
          fell back to software, usually a format the card cannot handle or more streams at once than it will take.
        </p>
      )}
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
  if (rows.error) return <p className="note bad-note" role="alert">{rows.error}</p>;
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
  const [lens, setLens] = useState<"watched" | "missing">("watched");
  const data = useApi<{ configured: boolean; requests: RequestRow[]; missing: RequestRow[] }>(
    "/library/requests",
  );
  if (data.error) return <p className="note bad-note" role="alert">{data.error}</p>;
  if (!data.data) return <Loading label="Asking Seerr for requests" slowHint="Seerr is read a page of 100 requests at a time." />;
  if (!data.data.configured)
    return (
      <p className="note warn-note">
        <SettingsLink page={SETTINGS_PAGES.mediaApps}>Connect Seerr in Settings</SettingsLink> to see requests that
        were never watched.
      </p>
    );
  const missing = data.data.missing ?? [];
  const rows = lens === "missing" ? missing : data.data.requests;
  return (
    <>
      <p className="muted">
        {lens === "watched"
          ? "Requests that arrived and the person who asked has never played, longest available first. Requesters are matched to Plex users by Plex username or email."
          : "Seerr has these marked as available, and the library has no file under that key. Either it was removed since, or the status is stale. These were mixed in with the list above, where they read as something nobody had watched."}
      </p>
      {/* Two different problems. One is nobody watching what they asked for;
          the other is the thing not being there at all, which is the more
          actionable of the two and was indistinguishable from the first. */}
      {missing.length > 0 && (
        <div className="row chips">
          <button className={lens === "watched" ? "chip on" : "chip"} onClick={() => setLens("watched")}>
            Never watched {data.data.requests.length}
          </button>
          <button className={lens === "missing" ? "chip on" : "chip"} onClick={() => setLens("missing")}>
            Not in the library {missing.length}
          </button>
        </div>
      )}
      {rows.length === 0 && (
        <p className="muted">
          {lens === "missing" ? "Everything Seerr says arrived is here." : "Everyone watched what they asked for."}
        </p>
      )}
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
                {r.also_requested_by?.length
                  ? ` and ${r.also_requested_by.length} other${r.also_requested_by.length === 1 ? "" : "s"}`
                  : ""}
                {r.available_days != null ? ` · available ${r.available_days} days` : ""}
                {r.watched_by_others ? ` · watched by ${r.watched_by_others} other${r.watched_by_others === 1 ? "" : "s"}` : " · watched by nobody"}
                {r.file_size ? ` · ${size(r.file_size)}` : ""}
              </p>
              {/* Somewhere to go from the row. A missing id means no button
                  rather than one that goes nowhere. */}
              <div className="row wrap linkrow request-links">
                {nav.filterTo && (
                  <button
                    className="ms-btn"
                    onClick={() =>
                      nav.filterTo?.("History", { rating_key: r.rating_key, ratingKeyLabel: r.title ?? "" })
                    }
                  >
                    History
                  </button>
                )}
                {LINKS.filter((l) => r.links?.[l.key]).map((l) => (
                  <a key={l.key} className="ms-btn" href={r.links![l.key]} target="_blank" rel="noreferrer">
                    <BrandIcon name={l.key} />
                    {l.label}
                  </a>
                ))}
              </div>
            </div>
          </div>
        ))}
      </div>
    </>
  );
}

/* One file in any list: a summary that opens to the whole file. */
function FileRow({
  file,
  badges,
  stats,
  days,
  aside,
}: {
  file: RowSummary;
  badges: ReactNode[];
  stats: (string | null)[];
  days: number;
  /* A quiet action belonging to this file. It sits inside the row rather than
     in a band under it, because a second full width strip per file doubled the
     height of a list of two hundred. */
  aside?: ReactNode;
}) {
  const [open, setOpen] = useState(false);
  const more = (file.findings_count ?? 1) - 1;
  return (
    <div className={open ? "file-row open" : "file-row"}>
      <div className="file-row-head">
        <button
          className="file-row-main"
          aria-expanded={open}
          onClick={() => setOpen(!open)}
        >
          {/* The rest of the app shows a poster wherever it shows a title, and
              this list read as a wall of text without one. */}
          <img className="file-row-poster" src={poster(file.rating_key, 80)} alt="" loading="lazy" />
          <span className="min0 file-row-text">
            <span className="clip">
              <strong>{file.title}</strong>
            </span>
            <span className="row wrap file-badges">{badges}</span>
            <span className="muted small file-row-line">{stats.filter(Boolean).join(" · ")}</span>
            {file.finding && (
              <span className="small finding-summary file-row-line">
                {file.finding}
                {more > 0 ? ` and ${more} more` : ""}
              </span>
            )}
          </span>
          <span className="file-row-caret" aria-hidden="true">
            {open ? "−" : "+"}
          </span>
        </button>
        {aside}
      </div>
      {open && <FileCard ratingKey={file.rating_key} days={days} />}
    </div>
  );
}

function FileCard({ ratingKey, days }: { ratingKey: number; days: number }) {
  const detail = useApi<FileDetail>(`/library/file/${ratingKey}?days=${days}`);
  if (detail.error) return <p className="note bad-note" role="alert">{detail.error}</p>;
  if (!detail.data)
    return (
      <div className="file-card">
        <Loading compact label="Reading the file" />
      </div>
    );
  return <FileCardView f={detail.data} days={days} />;
}

/* The card itself, given a file. Issues render it from their own payload
 * rather than asking for the same file twice.
 *
 * Laid out the way the rest of the app reads: what is wrong first, then the
 * facts as label and value on one line each, then the tracks once, then the
 * one or two things worth doing. Tidying used to sit open in the middle, with
 * a second copy of every track in it, so a file with nothing wrong was mostly
 * a form. It opens when asked for, and while it is open its tick boxes are the
 * track list rather than a second one. */
export function FileCardView({ f, days }: { f: FileDetail; days: number }) {
  const nav = useNav();
  const [showTitle, setShowTitle] = useState(false);
  const [tidying, setTidying] = useState(false);
  const [picking, setPicking] = useState(false);
  const plan = useApi<Tidy>(`/library/file/${f.rating_key}/tidy`, [f.rating_key]);
  const tidyable = Boolean(plan.data && (plan.data.steps.length > 0 || plan.data.audio.length + plan.data.subtitles.length > 0));
  const worth = f.findings.some((x) => x.severity !== "low");
  const name = f.file_path ? f.file_path.split(/[\\/]/).pop() : null;

  return (
    <div className="file-card">
      {f.findings.length > 0 ? (
        /* One line each: how much it matters and what it is. Four findings
           written out in full were most of the card, so the why and the fix
           open from the line rather than standing open all the time. */
        <section className="findings">
          {f.findings.map((x) => (
            <details key={x.key} className={`finding ${x.severity}`}>
              <summary className="finding-head">
                <span className={x.severity === "high" ? "pill bad" : x.severity === "medium" ? "pill warn" : "pill"}>
                  {x.severity === "high" ? "Fix first" : x.severity === "medium" ? "Worth fixing" : "Tidy up"}
                </span>
                <strong>{x.title}</strong>
              </summary>
              <p className="small">{x.detail}</p>
              <p className="small">
                <span className="muted">Fix: </span>
                {x.fix}
              </p>
              {x.arr && <p className="muted small">{x.arr}</p>}
            </details>
          ))}
        </section>
      ) : (
        <p className="muted small">Nothing about this file itself stands out.</p>
      )}

      <dl className="spec file-facts">
        <Fact label="Format">{fileFormat(f) || "Not checked yet"}</Fact>
        <Fact label="Size">
          {[size(f.file_size), mbps(f.file_bitrate), f.versions && f.versions > 1 ? `${f.versions} versions` : null]
            .filter(Boolean)
            .join(", ") || "Not known"}
        </Fact>
        {f.store && <Fact label="Stored">{f.store}</Fact>}
        <Fact label="Played">
          {f.plays
            ? `${f.plays} ${f.plays === 1 ? "time" : "times"} by ${f.users} ${f.users === 1 ? "person" : "people"} in ${days} days` +
              (f.remote_plays ? `, ${f.remote_plays} remote` : "") +
              (f.transcodes ? `, ${f.transcodes} transcoded` : "") +
              (f.last_play ? `, last ${when(f.last_play)}` : "")
            : `Not in the last ${days} days`}
        </Fact>
        {f.transcode_causes.length > 0 && (
          <Fact label="Transcodes">
            {f.transcode_causes.map((c) => `${TRANSCODE_CAUSES[c.cause] ?? c.cause} (${c.streams})`).join(", ")}
          </Fact>
        )}
        {f.stall_causes.length > 0 && (
          <Fact label="Stalls">{f.stall_causes.map((c) => `${STALL_CAUSES[c.cause] ?? c.cause} (${c.stalls})`).join(", ")}</Fact>
        )}
        {f.platforms.length > 0 && (
          <Fact label="Devices">
            {f.platforms.map((p) => `${p.platform} ${p.plays}${p.transcodes ? ` (${p.transcodes} transcoded)` : ""}`).join(", ")}
          </Fact>
        )}
        {/* The name, which says which file it is. The folders above it are in
            the tooltip: a whole path on the card was the longest thing on it
            and the least read. */}
        {name && (
          <Fact label="File">
            <span className="file-name" title={f.file_path ?? undefined}>
              {name}
            </span>
          </Fact>
        )}
      </dl>

      {tidying && plan.data ? (
        <TidyPanel ratingKey={f.rating_key} title={f.title} plan={plan.data} onClose={() => setTidying(false)} />
      ) : (
        <div className="track-lists">
          <div>
            <h4>Audio</h4>
            {f.audio_tracks.length === 0 && <p className="muted small">None recorded.</p>}
            {f.audio_tracks.map((t, i) => (
              <p key={i} className="small">
                {[
                  t.codec?.toUpperCase(),
                  // The layout says what the count cannot: 5.1(side) and
                  // 5.1(rear) are both six channels and not the same thing.
                  t.layout ?? (t.channels ? `${t.channels} ch` : null),
                  t.language ?? "no language",
                  t.bitrate ? `${t.bitrate} kbps` : null,
                  t.sample_rate ? `${Math.round(t.sample_rate / 100) / 10} kHz` : null,
                  t.default ? "default" : null,
                  t.title,
                ]
                  .filter(Boolean)
                  .join(" \u00b7 ")}
              </p>
            ))}
          </div>
          <div>
            <h4>Subtitles</h4>
            {f.subtitle_tracks.length === 0 && <p className="muted small">None.</p>}
            {f.subtitle_tracks.map((t, i) => (
              <p key={i} className="small">
                {[
                  t.codec?.toUpperCase(),
                  t.language ?? "no language",
                  // Subtitles carrying sound effects and speaker names. Anybody
                  // who wants plain subtitles does not want these, and nothing
                  // could tell them apart before.
                  t.sdh ? "SDH" : null,
                  t.forced ? "forced" : null,
                  t.dub ? "for the dub" : null,
                  t.location,
                  t.default ? "default" : null,
                  t.title,
                ]
                  .filter(Boolean)
                  .join(" \u00b7 ")}
              </p>
            ))}
          </div>
        </div>
      )}

      {!tidying && (
        <ArrActions
          ratingKey={f.rating_key}
          arr={f.arr}
          title={f.title}
          primary={worth || !tidyable}
          picking={picking}
          onPick={setPicking}
          extra={
            tidyable ? (
              <button className={worth ? "btn" : "btn primary"} onClick={() => setTidying(true)}>
                Tidy the tracks
              </button>
            ) : null
          }
        />
      )}

      <p className="muted small file-links">
        {nav.filterTo && (
          <button
            className="linkish"
            onClick={() => nav.filterTo?.("History", { rating_key: f.rating_key, ratingKeyLabel: f.title })}
          >
            Plays in History
          </button>
        )}
        <button className="linkish" onClick={() => setShowTitle(!showTitle)}>
          {showTitle ? "Hide the title card" : "Title card"}
        </button>
      </p>
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
  /* Since 0.90.0 the scan keeps all of this. Two rows reading "PGS eng" with
     nothing between them is a choice nobody can make. */
  layout?: string | null;
  bitrate?: number | null;
  sdh?: boolean;
  dub?: boolean;
  default?: boolean;
};

type Tidy = {
  /* Each step says which tracks it would drop, so the steps and the track
     list below them are one view of the file rather than two that disagree.
     The positions come from the code that decides, not from working it out
     again here. */
  steps: {
    key: string;
    what: string;
    why: string;
    drops_subtitles?: number[];
    drops_audio?: number[];
    /* Negative means the file gets smaller. Null where a track carried no
       bitrate, which is about one file in ten, and zero is a real answer
       for a step that only reorders or rewraps. */
    size_change?: number | null;
  }[];
  duration?: number | null;
  file_path: string | null;
  audio: TidyTrack[];
  subtitles: TidyTrack[];
  local_path: string | null;
  tools: { ready: boolean };
};

type TidyJob = {
  id: number;
  rating_key: number;
  title: string | null;
  status: string;
  progress: number;
  detail: string | null;
  saved_bytes: number | null;
  asked_by: string | null;
  steps: string[];
  created_at?: string | null;
};

/* What a track is, in the order somebody reads it.
 *
 * The language first and on its own, because that is what the choice is made
 * by: a list of ninety tracks is chosen through at the language level and
 * nowhere else. Then what it is, then the handful of things that tell two
 * tracks of the same language apart, which is the case that used to be
 * impossible: two rows both reading "PGS eng" and no way to pick between them.
 */
function TrackRow({
  track,
  kept,
  first,
  onKeep,
  onFirst,
  disabled,
}: {
  track: TidyTrack;
  kept: boolean;
  first?: boolean | null;
  onKeep: (on: boolean) => void;
  onFirst?: () => void;
  disabled: boolean;
}) {
  const facts = [
    (track.codec ?? "?").toUpperCase(),
    track.layout ?? (track.channels ? `${track.channels} ch` : null),
    track.bitrate ? `${track.bitrate} kbps` : null,
  ].filter(Boolean);
  const flags = [
    track.forced ? "forced" : null,
    track.sdh ? "SDH" : null,
    track.dub ? "for the dub" : null,
    track.default ? "default" : null,
  ].filter(Boolean) as string[];

  return (
    <div className={kept ? "track-row" : "track-row dropping"}>
      <label className="check min0">
        <input type="checkbox" checked={kept} disabled={disabled} onChange={(e) => onKeep(e.target.checked)} />
        <span className="track-lang">{(track.language ?? "??").toUpperCase()}</span>
        <span className="muted small track-facts">{facts.join(" \u00b7 ")}</span>
        {flags.map((flag) => (
          <span key={flag} className="pill small">
            {flag}
          </span>
        ))}
        {track.title && <span className="muted small clip track-title">{track.title}</span>}
      </label>
      {onFirst && (
        <button
          className={first ? "btn trust on" : "btn trust"}
          disabled={disabled || !kept}
          title="Players take the first track unless somebody goes looking, which is how a film ends up playing its dub"
          onClick={onFirst}
        >
          {first ? "plays first" : "play first"}
        </button>
      )}
    </div>
  );
}

function TidyPanel({
  ratingKey,
  title,
  plan: t,
  onClose,
}: {
  ratingKey: number;
  title: string;
  plan: Tidy;
  onClose: () => void;
}) {
  const [chosen, setChosen] = useState<Set<string> | null>(null);
  const [message, setMessage] = useState<{ text: string; ok: boolean } | null>(null);
  const [busy, setBusy] = useState(false);
  // Which tracks survive, and which one plays first. Null until somebody
  // touches them, so a file nobody has edited sends no choice at all.
  const [keepAudio, setKeepAudio] = useState<Set<number> | null>(null);
  const [keepSubs, setKeepSubs] = useState<Set<number> | null>(null);
  const [first, setFirst] = useState<number | null>(null);

  const picked = chosen ?? new Set(t.steps.map((s) => s.key));

  /* What the ticked steps alone would drop.
   *
   * Shown in the track list so there is one view of the file. Until somebody
   * touches a track the steps decide, which is also what the server does:
   * a choice is only sent when one was made, and a choice made by hand
   * outranks the steps for that kind.
   */
  function dropsFrom(which: "drops_audio" | "drops_subtitles") {
    const gone = new Set<number>();
    for (const step of t.steps) {
      if (!picked.has(step.key)) continue;
      for (const position of step[which] ?? []) gone.add(position);
    }
    return gone;
  }

  const audioKept = keepAudio ?? new Set(t.audio.filter((a) => !dropsFrom("drops_audio").has(a.position)).map((a) => a.position));
  const subsKept = keepSubs ?? new Set(t.subtitles.filter((x) => !dropsFrom("drops_subtitles").has(x.position)).map((x) => x.position));
  const edited = keepAudio !== null || keepSubs !== null || first !== null;
  const dropped = t.audio.length - audioKept.size + (t.subtitles.length - subsKept.size);

  /* What the ticked steps come to, in bytes, and whether anything was
     left out of the total.

     A step whose tracks carried no bitrate cannot be counted, and adding
     it in as zero would understate what tidying is worth while reading
     like a complete answer. It is counted separately and said. */
  const worth = (() => {
    let bytes = 0;
    let unknown = 0;
    for (const step of t.steps) {
      if (!picked.has(step.key)) continue;
      if (step.size_change === null || step.size_change === undefined) unknown += 1;
      else bytes += step.size_change;
    }
    return { bytes, unknown };
  })();

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

  /* The languages present, with how many tracks each has.
   *
   * The reason this exists: a film with ninety subtitle tracks is six in each
   * of fifteen languages, and nobody goes down ninety checkboxes. The choice
   * is made by language, so the control is by language, and the list
   * underneath is there for the one case where two tracks of the same
   * language are not the same thing.
   */
  function languagesIn(tracks: TidyTrack[]) {
    const counted = new Map<string, number>();
    for (const track of tracks) {
      const key = (track.language ?? "??").toLowerCase();
      counted.set(key, (counted.get(key) ?? 0) + 1);
    }
    return [...counted.entries()].sort((a, b) => b[1] - a[1] || a[0].localeCompare(b[0]));
  }

  function setLanguage(which: "audio" | "subtitles", language: string, on: boolean) {
    const tracks = which === "audio" ? t.audio : t.subtitles;
    const from = which === "audio" ? audioKept : subsKept;
    const next = new Set(from);
    for (const track of tracks) {
      if ((track.language ?? "??").toLowerCase() !== language) continue;
      if (on) next.add(track.position);
      else next.delete(track.position);
    }
    (which === "audio" ? setKeepAudio : setKeepSubs)(next);
  }

  /* Asked, because the answer can be no: this rewrites the whole file, and
     dropping a track cannot be undone from here. */
  async function start() {
    const goneAudio = t.audio.filter((a) => !audioKept.has(a.position));
    const goneSubs = t.subtitles.filter((s) => !subsKept.has(s.position));
    if (
      !(await askConfirm({
        title: dropped > 0 ? `Tidy ${title}, dropping ${dropped} tracks?` : `Tidy ${title}?`,
        body: (
          <>
            {dropped > 0 ? (
              <p>
                Dropping{" "}
                {[
                  goneAudio.length ? `${goneAudio.length} audio` : null,
                  goneSubs.length ? `${goneSubs.length} subtitle` : null,
                ]
                  .filter(Boolean)
                  .join(" and ")}{" "}
                track{dropped === 1 ? "" : "s"}. They are not recoverable from here.
              </p>
            ) : null}
            <p>
              The file is read and written once, the result is checked against the original for length and picture, and
              only then does it replace it. The picture is never re-encoded.
            </p>
          </>
        ),
        confirm: "Tidy it",
        danger: dropped > 0,
      }))
    )
      return;
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
      queueChanged();
      setMessage({ text: "Queued. It runs one file at a time, and the Remediation queue shows how far along it is.", ok: true });
    } catch (err) {
      setMessage({ text: (err as Error).message, ok: false });
    } finally {
      setBusy(false);
    }
  }

  const blocked: React.ReactNode = !t.tools.ready
    ? "ffmpeg is not in this image, so this build cannot tidy anything."
    : !t.local_path
      ? (
          <>
            This container cannot open the file. Mount the share that holds it, then say where it landed under{" "}
            <SettingsLink page={SETTINGS_PAGES.library}>Settings, Library and files</SettingsLink>.
          </>
        )
      : null;
  const off = Boolean(blocked);

  function section(which: "audio" | "subtitles") {
    const tracks = which === "audio" ? t.audio : t.subtitles;
    if (tracks.length === 0) return null;
    const keptHere = which === "audio" ? audioKept : subsKept;
    const languages = languagesIn(tracks);
    return (
      <div className="track-group">
        {/* Packed left rather than spread. "All" and "None" belong to the
            heading beside them, and space-between put them a thousand pixels
            away at the far edge of the card, where they read as belonging to
            whatever happened to be on that side. */}
        <div className="row wrap track-group-head">
          <h4>
            {which === "audio" ? "Audio" : "Subtitles"}{" "}
            <span className="muted small">
              keeping {keptHere.size} of {tracks.length}
            </span>
          </h4>
          <div className="segmented" role="group" aria-label={`Which ${which} to keep`}>
            <button
              className="seg"
              disabled={off}
              onClick={() => (which === "audio" ? setKeepAudio : setKeepSubs)(new Set(tracks.map((x) => x.position)))}
            >
              All
            </button>
            <button className="seg" disabled={off} onClick={() => (which === "audio" ? setKeepAudio : setKeepSubs)(new Set())}>
              None
            </button>
          </div>
        </div>
        {languages.length > 1 && (
          <div className="row wrap track-languages">
            {languages.map(([language, count]) => {
              const all = tracks
                .filter((x) => (x.language ?? "??").toLowerCase() === language)
                .every((x) => keptHere.has(x.position));
              return (
                <button
                  key={language}
                  className={all ? "chip on" : "chip"}
                  disabled={off}
                  title={all ? `Drop all ${count} ${language.toUpperCase()} tracks` : `Keep all ${count} ${language.toUpperCase()} tracks`}
                  onClick={() => setLanguage(which, language, !all)}
                >
                  {language.toUpperCase()} {count}
                </button>
              );
            })}
          </div>
        )}
        <div className="track-list">
          {tracks.map((track) => (
            <TrackRow
              key={track.position}
              track={track}
              kept={keptHere.has(track.position)}
              disabled={off}
              onKeep={(on) => keep(which, track.position, on)}
              {...(which === "audio"
                ? { first: first === track.position, onFirst: () => setFirst(track.position) }
                : {})}
            />
          ))}
        </div>
        {which === "audio" && audioKept.size === 0 && t.audio.length > 0 && (
          <p className="muted small">Everything is kept: a file is never left with no sound.</p>
        )}
      </div>
    );
  }

  return (
    <section className="tidy">
      <h4>Tidy the tracks</h4>
      {blocked && <p className="note warn-note">{blocked}</p>}
      {t.steps.length > 0 && (
        <>
          <p className="muted small tidy-step-why">
            What each would be worth, worked out from each track's bitrate and how long the file runs. An
            estimate: the tracks being added are exact, since the encoder is given a fixed bitrate, and the ones
            being dropped are as good as the bitrates in the file.
          </p>
        <div className="tidy-steps">
          {t.steps.map((step) => (
            <label key={step.key} className="tidy-step" title={step.why}>
              <input
                type="checkbox"
                checked={picked.has(step.key)}
                disabled={off}
                onChange={(e) => pick(step.key, e.target.checked)}
              />
              <span className="min0">
                <strong>{step.what}</strong>
                <span className="muted small tidy-step-why">{step.why}</span>
              </span>
              {/* What it is worth, beside the step rather than under it,
                  so a column of numbers can be read down. */}
              <span className="tidy-step-worth muted small">{change(step.size_change)}</span>
            </label>
          ))}
        </div>
        <p className="note tidy-worth">
          {worth.bytes === 0 && worth.unknown === 0
            ? "Nothing ticked would change the size of the file."
            : worth.bytes < 0
              ? `About ${size(-worth.bytes)} smaller.`
              : worth.bytes > 0
                ? `About ${size(worth.bytes)} larger.`
                : "Nothing countable ticked."}
          {worth.unknown > 0 && (
            <span className="muted">
              {" "}
              {worth.unknown === 1 ? "One ticked step drops" : `${worth.unknown} ticked steps drop`} tracks whose
              size the file does not state, so the real figure is better than this one.
            </span>
          )}
        </p>
        </>
      )}

      {section("audio")}
      {section("subtitles")}

      {message && <p className={message.ok ? "note ok-note" : "note bad-note"}>{message.text}</p>}
      <div className="file-actions">
        <button className="btn primary" disabled={off || busy || (picked.size === 0 && !edited)} onClick={start}>
          {busy ? "Queueing" : dropped > 0 ? `Tidy it, dropping ${dropped}` : "Tidy it"}
        </button>
        <button className="btn" onClick={onClose}>
          Done
        </button>
        <span className="muted small">The picture is copied, never re-encoded.</span>
      </div>
    </section>
  );
}

/* What ffmpeg is doing now, and what it did lately. Shown only when there is
   something to say, so the page is unchanged for anyone not using it. */
/* One job in the queue.

   The list that drew these lives in RemediationQueue now, interleaved with the
   replacements, because tidying a file and replacing it are the same question
   asked about the same file and splitting them put one above the other for no
   reason a person would recognise. */
function TidyJobRow({ job, waitForQuiet, onChanged }: { job: TidyJob; waitForQuiet: boolean; onChanged: () => void }) {
  const working = job.status === "running" || job.status === "queued";
  return (
    <div className="mini queue-row">
      <div className="min0">
        <div className="row wrap queue-head">
          <span className="pill">tidying</span>
          <strong className="clip">{job.title ?? `Item ${job.rating_key}`}</strong>
        </div>
        {job.status === "running" && (
          <div className="download-progress" title={`${job.progress}%`}>
            <span style={{ width: `${Math.max(2, Math.min(100, job.progress))}%` }} />
          </div>
        )}
        <p className="muted small">
          {job.status === "running"
            ? `${job.progress}% - ${job.detail ?? "working"}`
            : job.status === "queued"
              ? waitForQuiet
                ? "Waiting for the streams to stop"
                : "Waiting its turn"
              : `${job.status}: ${job.detail ?? ""}`}
          {/* A tidy can make a file larger, and often is meant to: adding a
              track everything can play costs a few hundred megabytes. The
              figure is what the file lost, so a negative one is growth, and
              printing it as "-350 MB smaller" is nonsense. */}
          {job.saved_bytes
            ? job.saved_bytes > 0
              ? ` (${size(job.saved_bytes)} smaller)`
              : ` (${size(-job.saved_bytes)} larger)`
            : ""}
          {/* Who asked, because a rule acting on its own is the case somebody
              will want to go and look at. */}
          {job.asked_by ? ` \u00b7 asked by ${job.asked_by}` : ""}
        </p>
      </div>
      {working && (
        <button
          className="tab"
          onClick={async () => {
            await api.post(`/library/tidy/jobs/${job.id}/cancel`, {});
            onChanged();
          }}
        >
          Stop
        </button>
      )}
    </div>
  );
}

function ArrActions({
  ratingKey,
  arr,
  title,
  primary,
  picking,
  onPick,
  extra,
}: {
  ratingKey: number;
  arr: { name: string; label: string; configured: boolean };
  title: string;
  primary: boolean;
  picking: boolean;
  onPick: (on: boolean) => void;
  extra?: React.ReactNode;
}) {
  const [busy, setBusy] = useState<string | null>(null);
  const [message, setMessage] = useState<{ text: string; ok: boolean } | null>(null);

  /* No confirmation here any more. Searching only downloads a release the
     quality profile already rates higher, tagging writes a label, and neither
     deletes anything: the old dialog said so itself, which makes it a step
     that is only ever clicked through. What happens instead is that the
     button says what it is doing and the answer appears under it. */
  async function run(action: "search" | "tag") {
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
      {/* One thing to do, made the obvious one: replacing when something is
          wrong with the file, tidying when only its tracks are untidy. */}
      <div className="file-actions">
        <button className={primary ? "btn primary" : "btn"} onClick={() => onPick(!picking)} disabled={!arr.configured} title={why}>
          Find a replacement
        </button>
        {extra}
      </div>
      {arr.configured ? (
        <p className="muted small">
          Or leave it to {arr.label}:{" "}
          <button className="linkish" onClick={() => run("search")} disabled={busy !== null}>
            {busy === "search" ? "asking" : "search by itself"}
          </button>
          {", or "}
          <button className="linkish" onClick={() => run("tag")} disabled={busy !== null}>
            {busy === "tag" ? "tagging" : "tag it for replacement"}
          </button>
          .
        </p>
      ) : (
        <p className="muted small">{why}.</p>
      )}
      {message && <p className={message.ok ? "note ok-note" : "note bad-note"}>{message.text}</p>}
      {picking && <ReleasePicker ratingKey={ratingKey} label={arr.label} title={title} onClose={() => onPick(false)} />}
    </div>
  );
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
  created_at?: string | null;
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

/* Each one names a field and says which way round is usually wanted, rather
 * than folding the direction into the name. "Smallest" cannot be a column
 * heading you click to reverse; "Size" can. */
const SORTS: Record<SortKey, { label: string; of: (r: Release) => number; down: boolean }> = {
  best: { label: "Best first", of: () => 0, down: true },
  score: { label: "Profile score", of: (r) => r.custom_format_score ?? -1e9, down: true },
  size: { label: "Size", of: (r) => r.size ?? 0, down: false },
  bitrate: { label: "Bitrate", of: (r) => r.estimated_bitrate ?? 0, down: false },
  seeders: { label: "Seeders", of: (r) => r.seeders ?? -1, down: true },
  age: { label: "Age", of: (r) => r.age_days ?? 1e9, down: false },
};

/* The columns of the list, in order. Everything a tile shows except the
 * rejection text, which is three lines of Radarr's reasoning and belongs in
 * the tile or a tooltip rather than in a cell. */
const COLUMNS: { key: SortKey; label: string; cell: (r: Release) => string }[] = [
  { key: "size", label: "Size", cell: (r) => size(r.size) },
  { key: "bitrate", label: "Bitrate", cell: (r) => mbps(r.estimated_bitrate) },
  { key: "score", label: "Score", cell: (r) => String(r.custom_format_score ?? 0) },
  { key: "seeders", label: "Seeders", cell: (r) => (r.seeders == null ? "n/a" : String(r.seeders)) },
  { key: "age", label: "Age", cell: (r) => (r.age_days == null ? "?" : `${r.age_days} d`) },
];

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
  const [down, setDown] = useState(true);
  // A list to compare twenty releases, tiles to read one properly. Which was
  // wanted last time is almost always which is wanted now.
  const [view, setView] = useState<"list" | "tiles">(() => {
    try {
      return localStorage.getItem("releases.view") === "tiles" ? "tiles" : "list";
    } catch {
      return "list";
    }
  });

  function show(next: "list" | "tiles") {
    setView(next);
    try {
      localStorage.setItem("releases.view", next);
    } catch {
      // A private window has no storage, and the view still works without it.
    }
  }

  // Clicking the column already sorted by turns it round; a new one starts
  // whichever way round that field is usually read.
  function sortBy(key: SortKey) {
    if (key === sort) setDown((v) => !v);
    else {
      setSort(key);
      setDown(SORTS[key].down);
    }
  }
  const [resolution, setResolution] = useState("");
  const [protocol, setProtocol] = useState("");
  const [maxSize, setMaxSize] = useState(0);
  const [hideBlocked, setHideBlocked] = useState(true);
  const [hideHeld, setHideHeld] = useState(false);
  const [queued, setQueued] = useState<string | null>(null);
  const [asking, setAsking] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    ref.current?.showModal();
  }, []);

  /* Whether a grab says up front that it does not want to be asked again.
     Remembered here because somebody who wants it usually wants it every
     time, and still sent per grab: it overrides the service's own judgement
     about one file, which is not a thing to leave switched on invisibly. */
  const [letThrough, setLetThrough] = useState(() => {
    try {
      return localStorage.getItem("library.replace.letThrough") === "on";
    } catch {
      return false;
    }
  });

  function chooseLetThrough(on: boolean) {
    setLetThrough(on);
    try {
      localStorage.setItem("library.replace.letThrough", on ? "on" : "off");
    } catch {
      /* a browser that refuses to remember is not a reason to refuse the tick */
    }
  }

  async function queue(release: Release) {

    setError(null);
    // Asking the service can take a few seconds, and until now the dialog sat
    // there looking like nothing had happened, which is how a file gets asked
    // for twice.
    setAsking(release.guid);
    try {
      await api.post(`/library/file/${ratingKey}/replace`, { release, auto_confirm: letThrough });
      setQueued(release.guid);
      queueChanged();
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setAsking(null);
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
  // Best first is the order the server worked out, so it is left alone.
  const rows =
    sort === "best"
      ? visible
      : [...visible].sort((a, b) => (down ? SORTS[sort].of(b) - SORTS[sort].of(a) : SORTS[sort].of(a) - SORTS[sort].of(b)));

  return (
    <dialog ref={ref} className="dialog wide" onClose={onClose} aria-labelledby="release-picker-title">
      <div className="row-between dialog-head">
        <div className="min0">
          <h2 id="release-picker-title">Replace {title}</h2>
          {found.data && (
            <p className="muted small">
              Current file: {fileFormat(found.data.current)}
              {found.data.current.file_size ? ` \u00b7 ${size(found.data.current.file_size)}` : ""}
              {found.data.current.file_bitrate ? ` \u00b7 ${mbps(found.data.current.file_bitrate)}` : ""}
            </p>
          )}
        </div>
        <button className="icon-btn" onClick={() => ref.current?.close()} aria-label="Close">
          &times;
        </button>
      </div>

      {found.error && <p className="note bad-note" role="alert">{found.error}</p>}
      {!found.data && !found.error && (
        <Loading
          label={`Asking ${label} to search the indexers`}
          slowHint="A live search across every indexer, which often takes half a minute or more."
        />
      )}
      {asking && <p className="note">Asking {label} to start the download\u2026</p>}
      {queued && <p className="note ok-note">Queued. Follow it under Library, Remediation queue.</p>}
      {error && <p className="note bad-note" role="alert">{error}</p>}

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
            <label
              className="check"
              title={`${label} holds a release it will not take by itself, usually because it does not rate it an upgrade. Ticked, the import happens the moment it is held instead of waiting here to be asked.`}
            >
              <input type="checkbox" checked={letThrough} onChange={(e) => chooseLetThrough(e.target.checked)} />
              Import it without asking me again
            </label>
            <div className="segmented push-right">
              <button className={view === "list" ? "seg on" : "seg"} onClick={() => show("list")}>
                List
              </button>
              <button className={view === "tiles" ? "seg on" : "seg"} onClick={() => show("tiles")}>
                Cards
              </button>
            </div>
          </div>

          <p className="muted small">
            {rows.length} of {all.length} releases. Best first means most of this file's problems solved, then{" "}
            {label}&apos;s own score against your profile. <span className="pill ok">Waits</span> is held for you to
            confirm; <span className="pill warn">Auto</span> is imported by itself.
            {letThrough && (
              <>
                {" "}
                A held one will be imported as soon as it is held, without waiting here, because you asked for
                that above. {label} is overruled about the file, not about anything else.
              </>
            )}
          </p>

          {rows.length === 0 ? (
            <p className="muted">Nothing matches those filters.</p>
          ) : view === "list" ? (
            <table className="table releases">
              <thead>
                <tr>
                  <th>
                    <button className="col-sort" onClick={() => sortBy("best")}>
                      Release {sort === "best" && <span aria-hidden>{"\u2193"}</span>}
                    </button>
                  </th>
                  <th className="num">Fixes</th>
                  {COLUMNS.map((c) => (
                    <th key={c.key} className="num">
                      <button className="col-sort" onClick={() => sortBy(c.key)}>
                        {c.label} {sort === c.key && <span aria-hidden>{down ? "\u2193" : "\u2191"}</span>}
                      </button>
                    </th>
                  ))}
                  <th>From</th>
                  <th />
                </tr>
              </thead>
              <tbody>
                {rows.map((r) => (
                  <tr key={r.guid} className={r.blocked ? "blocked" : undefined}>
                    {/* Name and badges on one line: the name gives up its end
                        rather than the row growing a second line for them. */}
                    <td>
                      <div className="release-cell">
                        <span className="clip release-name" title={r.title}>
                          {r.title}
                        </span>
                        <span className="release-badges">
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
                      </div>
                    </td>
                    {/* The count, with what they are on hover: five words a row
                        would push everything else off the screen. */}
                    <td className="num" title={r.fixes.join(". ") || "Nothing this file needs"}>
                      {r.fixes.length || ""}
                    </td>
                    {COLUMNS.map((c) => (
                      <td key={c.key} className="num">
                        {c.cell(r)}
                      </td>
                    ))}
                    <td className="clip" title={r.rejections.join(". ") || undefined}>
                      {r.indexer ?? "?"}
                    </td>
                    <td>
                      <button className="tab" disabled={Boolean(queued || asking)} onClick={() => queue(r)}>
                        {queued === r.guid ? "Queued" : asking === r.guid ? "Asking" : "Get"}
                      </button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
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

                  <button className="btn" disabled={Boolean(queued || asking)} onClick={() => queue(r)}>
                    {queued === r.guid ? "Queued" : asking === r.guid ? `Asking ${label}\u2026` : "Download this"}
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
  const tidy = useApi<TidyJob[]>("/library/tidy/jobs?limit=40");
  // Why a job is sitting there rather than running, which is otherwise the
  // sort of thing somebody watches for ten minutes before asking about.
  const settings = useApi<{ key: string; value: unknown }[]>("/settings");
  const waitForQuiet = (settings.data ?? []).some((s) => s.key === "tidy_when_quiet" && s.value === true);
  const [tab, setTab] = useState<"active" | "history">("active");

  const rows = list.data ?? [];
  const jobs = tidy.data ?? [];
  const working = (job: TidyJob) => job.status === "running" || job.status === "queued";
  const current = rows.filter((r) => ACTIVE_STATUSES.includes(r.status));
  const running = jobs.filter(working);

  const again = useRef(() => {
    list.reload();
    tidy.reload();
  });
  again.current = () => {
    list.reload();
    tidy.reload();
  };

  // Only while something is working: a finished list does not change by itself.
  const busy = current.length > 0 || running.length > 0;
  useEffect(() => {
    if (!busy) return;
    const timer = setInterval(() => again.current(), 5000);
    return () => clearInterval(timer);
  }, [busy]);

  useEffect(() => {
    const go = () => again.current();
    window.addEventListener(QUEUE_CHANGED, go);
    return () => window.removeEventListener(QUEUE_CHANGED, go);
  }, []);

  if (list.error) return <p className="note bad-note" role="alert">{list.error}</p>;
  if (!list.data) return <Loading label="Reading the queue" />;

  /* One list rather than two.
   *
   * Tidying a file and replacing it are the same question asked about the same
   * file, and they were in separate sections with separate headings, so what
   * you queued a minute ago appeared above or below the other list depending
   * only on which kind of work it was. Newest first, which is where somebody
   * who just queued something looks. */
  const active = tab === "active";
  const entries = [
    ...(active ? current : rows.filter((r) => !ACTIVE_STATUSES.includes(r.status))).map((r) => ({
      key: `r${r.id}`,
      at: r.created_at ?? "",
      node: active ? <ReplacementRow r={r} onChanged={() => again.current()} /> : <PastReplacement r={r} />,
    })),
    ...(active ? running : jobs.filter((j) => !working(j))).map((job) => ({
      key: `t${job.id}`,
      at: job.created_at ?? "",
      node: <TidyJobRow job={job} waitForQuiet={waitForQuiet} onChanged={() => again.current()} />,
    })),
  ].sort((a, b) => b.at.localeCompare(a.at));

  return (
    <>
      <div className="row-between queue-bar">
        <p className="muted small">
          Everything being done to a file. Radarr and Sonarr import an upgrade by themselves; anything else waits here
          for you to confirm or deny.
        </p>
        <div className="segmented">
          <button className={active ? "seg on" : "seg"} onClick={() => setTab("active")}>
            Active {current.length + running.length}
          </button>
          <button className={!active ? "seg on" : "seg"} onClick={() => setTab("history")}>
            History {rows.length - current.length + jobs.length - running.length}
          </button>
        </div>
      </div>

      {entries.length === 0 && (
        <p className="muted">
          {active
            ? "Nothing in progress. Open a file in any list and choose Tidy its tracks, or Find a replacement."
            : "Nothing finished yet."}
        </p>
      )}
      <div className="mini-list">
        {entries.map((e) => (
          <div key={e.key}>{e.node}</div>
        ))}
      </div>
    </>
  );
}

/* What a download client said, with the nothing taken out.
 *
 * Radarr passes its script's status line straight through, and it reads
 * "PAR Status: FAILURE - Unpack Status: NONE - Move Status: NONE - Script
 * Status: {scriptStatus} - Delete Status: NONE - Mark Status: NONE". One of
 * those six fields is the answer, four say nothing happened, and one is a
 * placeholder nobody filled in. Keeping only the fields that say something
 * leaves "PAR Status: FAILURE", which is the message.
 *
 * Anything that is not in that shape is left exactly as it came. */
const NOTHING = /^(none|ok|success|n\/a|-|)$/i;

export function readable(message: string | null | undefined): string | null {
  if (!message) return null;
  const parts = message.split(" - ");
  if (parts.length < 2) return message;
  const kept = parts.filter((part) => {
    const value = part.includes(":") ? part.slice(part.indexOf(":") + 1).trim() : part.trim();
    // A placeholder that never got substituted is not information.
    if (/^\{.*\}$/.test(value)) return false;
    return !NOTHING.test(value);
  });
  return kept.length ? kept.join(" \u00b7 ") : null;
}

function PastReplacement({ r }: { r: Replacement }) {
  const [open, setOpen] = useState(false);
  const status = REPLACEMENT_STATUS[r.status];
  return (
    <div>
      <button className={open ? "mini mini-button on" : "mini mini-button"} onClick={() => setOpen(!open)} aria-expanded={open}>
        <div className="min0">
          <span className="pill">replacing</span> <strong>{r.title}</strong> <span className={status.tone}>{status.label}</span>
          <p className="muted small release-title">{r.release?.title}</p>
          {r.status === "failed" && readable(r.message) && (
            <p className="small danger-text">{readable(r.message)}</p>
          )}
        </div>
        <span className="muted small">
          {r.updated_at ? new Date(/[zZ]|[+-]\d\d:\d\d$/.test(r.updated_at) ? r.updated_at : `${r.updated_at}Z`).toLocaleDateString() : ""}
          {r.resolved_by ? ` \u00b7 ${r.resolved_by}` : ""}
        </span>
      </button>
      {open && <ReplacementRow r={r} onChanged={() => undefined} heading={false} />}
    </div>
  );
}

function ReplacementRow({
  r: stored,
  onChanged,
  heading = true,
}: {
  r: Replacement;
  onChanged: () => void;
  /* False when this is already inside a row that drew the title, the kind and
     the release name, which is every row in History. */
  heading?: boolean;
}) {
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
    // A failed one is not going to change by itself, so it is asked once
    // rather than every ten seconds, and asked without being told to.
    if (!active) {
      if (r.status === "failed" && !fresh) refresh();
      return;
    }
    refresh();
    const timer = setInterval(refresh, 10000);
    return () => clearInterval(timer);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [stored.id, active]);
  const status = REPLACEMENT_STATUS[r.status];
  const service = r.service === "sonarr" ? "Sonarr" : "Radarr";

  async function decide(confirmIt: boolean) {
    const ok = await askConfirm({
      title: confirmIt ? `Import the new file for ${r.title}?` : `Deny this replacement for ${r.title}?`,
      body: confirmIt
        ? `${service} replaces the current file, into its recycle bin if you have one set.`
        : `The download is deleted and the release is blocked in ${service}.`,
      confirm: confirmIt ? "Import it" : "Deny it",
      danger: !confirmIt,
    });
    if (!ok) return;
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
          {heading && (
            <>
              <span className="pill">replacing</span> <strong>{r.title}</strong>{" "}
              <span className={status.tone}>{status.label}</span>
              <p className="muted small release-title">{r.release?.title}</p>
            </>
          )}
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
        {/* "Show what happened" used to sit here and call refresh, which is
            what the Refresh button below it already did. A failed row asks
            once when it opens instead, so what happened is simply there. */}
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
      {fresh?.live.queue?.messages && readable(fresh.live.queue.messages.join(" - ")) && (
        <p className="muted small">{readable(fresh.live.queue.messages.join(" - "))}</p>
      )}
      {fresh && fresh.live.events.length > 0 && (
        <ul className="arr-events">
          {fresh.live.events.map((e, i) => (
            <li key={i} className={e.type?.toLowerCase().includes("fail") ? "bad" : undefined}>
              <span className="muted small">{e.date ? new Date(e.date).toLocaleString() : ""}</span> <strong>{e.label}</strong>
              {readable(e.message) && <span className="small"> {readable(e.message)}</span>}
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
      {/* The message is in the closed row and in the events, both of which
          read better than this did. Only shown here when neither of those is
          on screen to carry it. */}
      {readable(r.message) &&
        !(fresh && fresh.live.events.length > 0) &&
        r.status !== "failed" &&
        !(r.candidate?.rejections ?? []).some((x) => r.message?.includes(x)) && (
          <p className="muted small">{readable(r.message)}</p>
        )}
      {error && <p className="note bad-note" role="alert">{error}</p>}
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
  // Read from the disk this store is on, or null when the media is not
  // mounted into this container.
  path: string | null;
  free: number | null;
  /* True where the capacity was written down rather than read off the disk,
     and the space in use counted from the files this app knows about. */
    stated?: boolean;
  total: number | null;
  used: number | null;
  shared_with: string[];
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
  const data = useApi<{ stores: Store[]; days: number; depth: number; warn_at?: number; critical_at?: number }>(
    `/library/stores?days=${days}`,
    [days],
  );
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

  if (data.error) return <p className="note bad-note" role="alert">{data.error}</p>;
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
      {error && <p className="note bad-note" role="alert">{error}</p>}
      {worst && elsewhereRate != null && (worst.stalls_per_100 ?? 0) > elsewhereRate * 2 && (
        <p className="note">
          Watching from <strong>{worst.store}</strong> stalls {worst.stalls_per_100} times per 100 plays, against{" "}
          {elsewhereRate} everywhere else. Open <strong>Why</strong> beside it before blaming the storage: stalls from
          viewers outside the house usually are not the disk.
        </p>
      )}
      <Disks stores={stores} warnAt={data.data?.warn_at} criticalAt={data.data?.critical_at} />
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
      {/* Here rather than anywhere else: a scan or a media analysis reads
          every file it touches off these same disks, which is the one answer
          this page could never give about a store that went slow. */}
      <h3>What the server has been doing for itself</h3>
      <p className="muted small">
        Plex scanning, analysing or generating for itself reads off these disks, so a stream being read from the
        same one has to wait. Plex says what is running this second and keeps no history, so this is only what has
        been seen since the app was watching.
      </p>
      <ServerWorkLately hours={48} />
    </>
  );
}

/* How much room is left, from the disks themselves.
 *
 * Above the table rather than a column in it, because free space belongs to
 * the disk and several stores can sit on one: as a column it would print the
 * same four terabytes on three rows and invite somebody to add them up. */
function Disks({ stores, warnAt = 10, criticalAt = 3 }: { stores: Store[]; warnAt?: number; criticalAt?: number }) {
  // One card per disk, whichever stores point at it.
  const byPath = new Map<
    string,
    { path: string; free: number; total: number; used: number; on: string[]; stated?: boolean }
  >();
  for (const s of stores) {
    if (!s.path || s.total === null || s.free === null || s.used === null) continue;
    const row = byPath.get(s.path) ?? {
      path: s.path, free: s.free, total: s.total, used: s.used, on: [], stated: s.stated,
    };
    row.on.push(s.store);
    byPath.set(s.path, row);
  }
  const disks = [...byPath.values()].sort((a, b) => a.path.localeCompare(b.path));

  if (disks.length === 0) {
    return (
      <p className="muted small">
        How much room is left is read from the disks the media sits on, which are not mounted into this container.
        Add them under Settings, Library, Tidying files and it appears here.
      </p>
    );
  }

  return (
    <div className="mini-list space-disks">
      {disks.map((d) => {
        const full = d.total ? (d.used / d.total) * 100 : 0;
        // The same thresholds the disk warning uses, read from the server
        // rather than written here as well: two numbers meaning one thing is
        // how a page ends up disagreeing with a notification.
        const left = 100 - full;
        const low = warnAt > 0 && left <= warnAt;
        const dire = criticalAt > 0 && left <= criticalAt;
        return (
          <div key={d.path} className="mini space-disk">
            <div className="min0">
              <div className="row-between">
                <strong>{d.path}</strong>
                <span className={dire ? "pill bad" : low ? "pill warn" : "pill"}>{size(d.free)} free</span>
              </div>
              <span className="progress space-bar">
                <span
                  className={low ? "progress-fill full" : "progress-fill"}
                  style={{ width: `${Math.min(100, full)}%` }}
                />
              </span>
              <p className="muted small">
                {size(d.used)} of {size(d.total)} used ({full.toFixed(0)}%)
                {d.stated ? " · size as written down, used counted from the files here" : ""}
                {d.on.length > 1 ? ` · shared by ${d.on.join(", ")}` : ` · ${d.on[0]}`}
              </p>
            </div>
          </div>
        );
      })}
    </div>
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
  if (data.error) return <p className="note bad-note" role="alert">{data.error}</p>;
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
          if (!(await askConfirm({
            title: `Forget ${old.data!.count} stalls recorded before ${old.data!.since}?`,
            body: "This cannot be undone.",
            confirm: "Forget them",
            danger: true,
          }))) return;
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

type Show = {
  rating_key: number;
  title: string;
  episodes: number;
  seasons: number;
  file_size: number;
  hours: number;
  year: number | null;
  library: string | null;
  plays: number;
};

type SeasonList = {
  rating_key: number;
  title: string | null;
  seasons: {
    season: number;
    rating_key: number | null;
    episodes: number;
    file_size: number;
    hours: number;
    plays: number;
  }[];
};

/* Where in the library we are looking.
 *
 * Films are a flat list and always were. Television is not: it is shows, each
 * with seasons, each with episodes, and browsing it as twenty six thousand
 * loose episodes was the only way in. The scan stores no row for a show or a
 * season, because neither has a file, but every episode carries the keys and
 * numbers that say where it belongs, so the shape was in the data already. */
type Place = { show: number | null; season: number | null; title: string | null };

const NOWHERE: Place = { show: null, season: null, title: null };

function Browse({
  days,
  inFlight,
  focus,
  onFocused,
}: {
  days: number;
  inFlight: Map<number, string>;
  focus?: LibraryTarget | null;
  onFocused?: () => void;
}) {
  const [place, setPlace] = useState<Place>(NOWHERE);
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

  /* Going where a title pointed.
   *
   * An episode arrives with its show and season, so the list opens there and
   * the episode itself is opened in the panel. A film has only its key, so the
   * flat list is already the right place and the panel is all that is needed.
   * Consumed once, or going back to Browse later would keep teleporting. */
  useEffect(() => {
    if (!focus) return;
    if (focus.show) {
      remember("kind", "episode", setKind);
      setPlace({ show: focus.show, season: focus.season ?? null, title: focus.title ?? null });
    } else if (focus.mediaType === "movie") {
      remember("kind", "movie", setKind);
      setPlace(NOWHERE);
    }
    if (focus.ratingKey) setOpen(focus.ratingKey);
    onFocused?.();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [focus]);

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
  if (place.show !== null) query.set("show", String(place.show));
  if (place.season !== null) query.set("season", String(place.season));

  // Episodes are only asked for once a season is open. Above that the lists
  // are shows and seasons, which are their own shape.
  const showing = kind === "episode" && place.season === null;
  const data = useApi<BrowseList>(
    showing ? null : `/library/browse?${query}`,
    [days, sort, kind, problem, resolution, sectionId, language, search, perHour, place.show, place.season],
  );
  const showList = useApi<{ items: Show[]; total: number }>(
    kind === "episode" && place.show === null
      ? `/library/shows?days=${days}${sectionId ? `&section_id=${sectionId}` : ""}${search.trim() ? `&search=${encodeURIComponent(search.trim())}` : ""}`
      : null,
    [days, kind, sectionId, search, place.show],
  );
  const seasonList = useApi<SeasonList>(
    kind === "episode" && place.show !== null && place.season === null
      ? `/library/shows/${place.show}?days=${days}`
      : null,
    [days, place.show, place.season],
  );

  function choose(key: number, on: boolean) {
    const next = new Set(chosen);
    if (on) next.add(key);
    else next.delete(key);
    setChosen(next);
  }

  async function tag() {
    const keys = [...chosen];
    // Nothing is downloaded and nothing is deleted: the tag is a shortlist.
    // There is nothing here to be sure about.
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

  if (data.error) return <p className="note bad-note" role="alert">{data.error}</p>;

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
          <select
            value={kind}
            onChange={(e) => {
              setPlace(NOWHERE);
              remember("kind", e.target.value, setKind);
            }}
          >
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

      {/* Where you are, and the way back. Only for television: films are a
          flat list and always were. */}
      {kind === "episode" && place.show !== null && (
        <nav className="row wrap trail" aria-label="Where you are">
          <button className="linkish" onClick={() => setPlace(NOWHERE)}>
            All shows
          </button>
          <span className="muted" aria-hidden="true">
            /
          </span>
          {place.season === null ? (
            <strong>{place.title ?? "Show"}</strong>
          ) : (
            <>
              <button
                className="linkish"
                onClick={() => setPlace({ ...place, season: null })}
              >
                {place.title ?? "Show"}
              </button>
              <span className="muted" aria-hidden="true">
                /
              </span>
              <strong>Season {place.season}</strong>
            </>
          )}
        </nav>
      )}

      {/* The shows. */}
      {kind === "episode" && place.show === null && (
        <>
          {!showList.data && <Loading label="Reading the shows" />}
          {showList.error && <p className="note bad-note" role="alert">{showList.error}</p>}
          {showList.data && (
            <>
              <p className="muted small count-line">
                {showList.data.total.toLocaleString()} {showList.data.total === 1 ? "show" : "shows"}.
              </p>
              <div className={asTiles ? "poster-wall" : "mini-list"}>
                {showList.data.items.map((s) => (
                  <button
                    key={s.rating_key}
                    className={asTiles ? "poster-tile" : "mini mini-button"}
                    onClick={() => setPlace({ show: s.rating_key, season: null, title: s.title })}
                  >
                    <img
                      className={asTiles ? undefined : "row-poster"}
                      src={poster(s.rating_key, asTiles ? 200 : 80)}
                      alt=""
                      loading="lazy"
                    />
                    <div className="min0">
                      <strong className={asTiles ? "poster-name" : undefined}>{s.title}</strong>
                      <p className="muted small">
                        {s.seasons} {s.seasons === 1 ? "season" : "seasons"}
                        {" \u00b7 "}
                        {s.episodes.toLocaleString()} {s.episodes === 1 ? "episode" : "episodes"}
                        {" \u00b7 "}
                        {size(s.file_size)}
                        {s.library ? ` \u00b7 ${s.library}` : ""}
                        {s.plays ? ` \u00b7 ${s.plays.toLocaleString()} plays in ${days} days` : ""}
                      </p>
                    </div>
                    <span className="muted small">Open</span>
                  </button>
                ))}
              </div>
            </>
          )}
        </>
      )}

      {/* Its seasons. */}
      {kind === "episode" && place.show !== null && place.season === null && (
        <>
          {!seasonList.data && <Loading label="Reading the seasons" />}
          {seasonList.error && <p className="note bad-note" role="alert">{seasonList.error}</p>}
          {seasonList.data && (
            <div className={asTiles ? "poster-wall" : "mini-list"}>
              {seasonList.data.seasons.map((s) => (
                <button
                  key={s.season}
                  className={asTiles ? "poster-tile" : "mini mini-button"}
                  onClick={() => setPlace({ ...place, season: s.season, title: place.title ?? seasonList.data!.title })}
                >
                  <img
                    className={asTiles ? undefined : "row-poster"}
                    src={poster(s.rating_key ?? place.show ?? 0, asTiles ? 200 : 80)}
                    alt=""
                    loading="lazy"
                  />
                  <div className="min0">
                    <strong className={asTiles ? "poster-name" : undefined}>Season {s.season}</strong>
                    <p className="muted small">
                      {s.episodes} {s.episodes === 1 ? "episode" : "episodes"}
                      {" \u00b7 "}
                      {size(s.file_size)}
                      {s.plays ? ` \u00b7 ${s.plays.toLocaleString()} plays in ${days} days` : ""}
                    </p>
                  </div>
                  <span className="muted small">Open</span>
                </button>
              ))}
            </div>
          )}
        </>
      )}

      {!showing && !data.data && <Loading label="Reading the library" />}
      {!showing && data.data && (
        <p className="muted small count-line">
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

      {!showing && !asTiles && (
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
              <img className="row-poster" src={poster(row.rating_key, 80)} alt="" loading="lazy" />
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

      <div className="poster-wall" hidden={showing || !asTiles}>
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
              {/* First, because it is the one that changes what you would do
                  next: asking for a second replacement while the first is
                  still downloading is the mistake this prevents. */}
              {inFlight.has(tile.rating_key) && (
                <span className="pill ok" title="Already in the remediation queue">
                  {inFlight.get(tile.rating_key)}
                </span>
              )}
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
      {file.error && <p className="note bad-note" role="alert">{file.error}</p>}
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

type AttentionRow = RowSummary & {
  kind: Lens;
  why: string | null;
  store: string;
  plays?: number;
  media_type: string | null;
  year: number | null;
  file_bitrate: number | null;
  file_size: number | null;
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

function Attention({ days, inFlight }: { days: number; inFlight: Map<number, string> }) {
  const nav = useNav();
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
    /* Episodes left out because somebody is partway through their show.
       Said rather than silently dropped: a list that quietly shrinks is a
       list nobody can reason about. */
    watching?: number;
    watching_days?: number;
    settling?: number;
    settling_days?: number;
    /* Left out because they are in a collection somebody said to keep. */
    in_collection?: number;
    kept_collections?: string[];
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

  /* Tidying the whole list.
   *
   * The feature has only ever worked one file at a time, opened by hand, and
   * this list runs to two hundred. Asked for first as a dry run, so the
   * question is answered with what would actually happen to which files
   * rather than with a number, and each file is queued as its own job so the
   * queue says which one it is on and any of them can be stopped.
   */
  async function tidyAll() {
    const shown = data.data?.items.length ?? 0;
    if (!shown) return;
    setError(null);
    try {
      const preview = await api.post<{
        queued: number;
        skipped: number;
        not_done: { why: string }[];
        /* Negative is smaller, the same sign one file uses. */
        size_change: number;
        size_unknown: number;
      }>(
        "/library/tidy/many",
        { kind: lens, days, limit: shown, dry_run: true },
      );
      if (!preview.queued) {
        void tell("Nothing to do", "None of these files has anything worth changing.");
        return;
      }
      if (
        !(await askConfirm({
          title: `Tidy ${preview.queued} ${preview.queued === 1 ? "file" : "files"}?`,
          body: (
            <>
              <p>
                Each one is read and written once, with the steps worked out from that file rather than the same
                thing done to all of them. The picture is never re-encoded, and the original is replaced only
                after the result is checked.
              </p>
              <p>
                {/* The number that makes this a decision rather than a count.
                    Dropping spare dubs across a list frees real room, and
                    adding a playable track across one costs it, and until now
                    the question said neither. */}
                {preview.size_change < 0
                  ? `Together they would free about ${size(-preview.size_change)}.`
                  : preview.size_change > 0
                    ? `Together they would take about ${size(preview.size_change)} more.`
                    : "Together they would not change how much room is used."}
                {preview.size_unknown > 0 &&
                  ` ${preview.size_unknown} of them drop tracks the file states no size for, so the real figure is better than that.`}
              </p>
              <p>
                They run one at a time and the Remediation queue shows which. Any of them can be stopped before it
                starts.
                {preview.skipped > 0 && ` ${preview.skipped} will be left alone, with nothing worth changing.`}
              </p>
            </>
          ),
          confirm: `Tidy ${preview.queued}`,
          danger: true,
        }))
      )
        return;
      const done = await api.post<{ queued: number; skipped: number }>("/library/tidy/many", {
        kind: lens,
        days,
        limit: shown,
      });
      queueChanged();
      void tell("Queued", `${done.queued} queued. The Remediation queue shows how far along it is.`);
    } catch (err) {
      setError((err as Error).message);
    }
  }

  return (
    <>
      <div className="segmented">
        {LENSES.map((l) => (
          <button key={l.id} className={lens === l.id ? "seg on" : "seg"} onClick={() => choose(l.id)}>
            {l.label}
          </button>
        ))}
      </div>
      <div className="row-between">
        <p className="muted min0">{here.blurb}</p>
        {lens === "messy" && nav.isAdmin && (data.data?.items.length ?? 0) > 1 && (
          <button className="btn" onClick={tidyAll}>
            Tidy all {data.data?.items.length}
          </button>
        )}
      </div>
      {error && <p className="note bad-note" role="alert">{error}</p>}

      {data.error && <p className="note bad-note" role="alert">{data.error}</p>}
      {!data.data && <Loading label="Reading the library" />}
      {data.data && data.data.items.length === 0 && (
        <p className="note">Nothing here. Either nothing qualifies, or you have kept everything that did.</p>
      )}
      {data.data && data.data.items.length > 0 && (
        /* A count is not a notice. It was in a full width boxed note, which
           is the same furniture the app uses to warn somebody. */
        <p className="muted small count-line">
          {lens === "room" && data.data.reclaimable
            ? `${size(data.data.reclaimable)} across ${(data.data.found ?? data.data.total).toLocaleString()} files nobody is watching.`
            : `${data.data.total.toLocaleString()} ${data.data.total === 1 ? "file" : "files"}, worst first.`}
          {Boolean(data.data.watching) && (
            <>
              {" "}
              {data.data.watching} more left out: somebody has watched something in the same show in the last{" "}
              {data.data.watching_days} days, so those are next episodes rather than files nobody wants.
            </>
          )}
          {Boolean(data.data.settling) && (
            <>
              {" "}
              {data.data.settling} were added in the last {data.data.settling_days} days, so nobody not having
              watched them yet says nothing.
            </>
          )}
          {Boolean(data.data.in_collection) && (
            <>
              {" "}
              {data.data.in_collection} are in{" "}
              {(data.data.kept_collections ?? []).length === 1
                ? "a collection"
                : `${(data.data.kept_collections ?? []).length} collections`}{" "}
              you said to keep.
            </>
          )}
        </p>
      )}

      <div className="file-list">
        {(data.data?.items ?? []).map((f) => (
          <div key={f.rating_key} className="cleanup-row">
            <FileRow
              file={f}
              days={days}
              aside={
                <button
                  className="tab file-row-aside"
                  title="Stop this file being suggested, whichever question is asked"
                  onClick={async () => {
                    const why = await askText({
                      title: `Keep ${f.title} and stop suggesting it?`,
                      body: "It stays in the library and stops appearing in this list. You can undo it later.",
                      label: "Reason, for the Log",
                      placeholder: "Optional",
                      confirm: "Keep it",
                    });
                    if (why === null) return;
                    act(() => api.post(`/library/cleanup/${f.rating_key}/keep`, { reason: why }));
                  }}
                >
                  Keep it
                </button>
              }
              badges={[
                ...(inFlight.has(f.rating_key)
                  ? [
                      <span key="busy" className="pill ok" title="Already in the remediation queue">
                        {inFlight.get(f.rating_key)}
                      </span>,
                    ]
                  : []),
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
