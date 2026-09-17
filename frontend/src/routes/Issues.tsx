import { useState } from "react";
import Loading from "../components/Loading";
import { useApi } from "../lib/api";
import { FileCardView, type FileDetail } from "./Library";
import { useNav } from "../lib/nav";

/* Issues: what people reported, next to what this server knows.
 *
 * Seerr collects the sentence ("audio is out of sync"). Everything that
 * explains it is already here: the file's tracks and bitrate, who played it on
 * what, whether it transcoded for them, and whether it stalled while they
 * watched. One page, so the report and its evidence are read together.
 */

type IssueRow = {
  id: number;
  seerr_id: number | null;
  source: string;
  issue_type: "video" | "audio" | "subtitles" | "other";
  status: "open" | "resolved";
  message: string | null;
  title: string | null;
  media_type: string | null;
  rating_key: number | null;
  season: number | null;
  episode: number | null;
  reporter_name: string | null;
  reporter_user_id: number | null;
  comments: number;
  created_at: string | null;
  updated_at: string | null;
};

type Play = {
  row_id: number;
  user_id: number | null;
  user_name: string | null;
  started: number | null;
  platform: string | null;
  player: string | null;
  location: string | null;
  transcode_decision: string | null;
  percent_complete: number | null;
  mine: boolean;
  stalls: number;
  stall_seconds: number;
};

type IssueDetail = IssueRow & {
  comment_list: { message: string | null; author: string | null; created_at: string }[];
  tmdb_id: number | null;
  file: FileDetail | null;
  file_title: string | null;
  plays: Play[];
  streams: { platform: string | null; cause: string | null; buffers: number | null; started_at: string | null; user_name: string | null }[];
  other_reports: IssueRow[];
};

type Listing = {
  items: IssueRow[];
  open: number;
  resolved: number;
  by_type: Record<string, number>;
  seerr_url: string | null;
  seerr_configured: boolean;
};

const TYPES: Record<string, string> = { video: "Video", audio: "Audio", subtitles: "Subtitles", other: "Other" };

function when(iso: string | null): string {
  if (!iso) return "";
  const t = new Date(/[zZ]|[+-]\d\d:\d\d$/.test(iso) ? iso : `${iso}Z`);
  return t.toLocaleString();
}

function playedAt(seconds: number | null): string {
  return seconds ? new Date(seconds * 1000).toLocaleString() : "";
}

export default function Issues() {
  const [status, setStatus] = useState<"open" | "resolved" | "all">("open");
  const [type, setType] = useState<string>("");
  const [open, setOpen] = useState<number | null>(null);
  const query = `/issues?status=${status}${type ? `&issue_type=${type}` : ""}`;
  const data = useApi<Listing>(query, [status, type]);

  if (data.error) return <p className="note bad-note pad">{data.error}</p>;
  if (!data.data) return <div className="pad"><Loading label="Reading reported issues" /></div>;
  const d = data.data;

  return (
    <div className="pad">
      <div className="row-between">
        <h1>Issues</h1>
        <div className="row">
          <div className="segmented">
            {(["open", "resolved", "all"] as const).map((s) => (
              <button key={s} className={status === s ? "seg on" : "seg"} onClick={() => setStatus(s)}>
                {s === "open" ? `Open ${d.open}` : s === "resolved" ? `Resolved ${d.resolved}` : "All"}
              </button>
            ))}
          </div>
          <select value={type} onChange={(e) => setType(e.target.value)}>
            <option value="">Every kind</option>
            {Object.keys(TYPES).map((t) => (
              <option key={t} value={t}>
                {TYPES[t]}
                {d.by_type[t] ? ` (${d.by_type[t]})` : ""}
              </option>
            ))}
          </select>
        </div>
      </div>

      <p className="muted">
        What people reported, with the file, the plays behind it and what went wrong during them. Reports are read from
        Seerr every five minutes.
      </p>

      {d.items.length === 0 && (
        <p className="note">
          {d.seerr_configured
            ? `Nothing reported${status === "open" ? " and still open" : ""}. Reports made in Seerr appear here within five minutes.`
            : "Seerr is not set up, so there is nothing to read. Add it under Settings, Media apps and reports will appear here."}
        </p>
      )}

      <div className="issue-list">
        {d.items.map((i) => (
          <div key={i.id}>
            <button className={open === i.id ? "issue-row on" : "issue-row"} onClick={() => setOpen(open === i.id ? null : i.id)}>
              <span className={i.status === "open" ? "pill warn" : "pill ok"}>{i.status}</span>
              <span className="pill">{TYPES[i.issue_type]}</span>
              <span className="issue-title clip">
                <strong>{i.title ?? (i.rating_key ? `Item ${i.rating_key}` : "Unknown title")}</strong>
                <span className="muted small clip">{i.message}</span>
              </span>
              <span className="muted small">{i.reporter_name ?? "Someone"}</span>
              <span className="muted small">{when(i.created_at)}</span>
            </button>
            {open === i.id && <IssueCard id={i.id} seerrUrl={d.seerr_url} />}
          </div>
        ))}
      </div>
    </div>
  );
}

function IssueCard({ id, seerrUrl }: { id: number; seerrUrl: string | null }) {
  const nav = useNav();
  const detail = useApi<IssueDetail>(`/issues/${id}`);
  if (detail.error) return <p className="note bad-note">{detail.error}</p>;
  if (!detail.data) return <Loading compact label="Reading the report" />;
  const d = detail.data;
  const mine = d.plays.filter((p) => p.mine);

  return (
    <div className="issue-card">
      <section className="card-section">
        <h3>The report</h3>
        {d.comment_list.length === 0 && <p className="muted small">No message.</p>}
        {d.comment_list.map((c, n) => (
          <p key={n} className="small">
            <strong>{c.author ?? "Someone"}</strong> <span className="muted">{when(c.created_at)}</span>
            <br />
            {c.message}
          </p>
        ))}
        <p className="muted small">
          {d.season && d.episode ? `Season ${d.season}, episode ${d.episode}. ` : ""}
          {d.seerr_id && seerrUrl && (
            <a href={`${seerrUrl}/issues/${d.seerr_id}`} target="_blank" rel="noreferrer">
              Open in Seerr
            </a>
          )}
        </p>
      </section>

      <section className="card-section">
        <h3>{mine.length > 0 ? "How they watched it" : "How it has been watched"}</h3>
        {d.plays.length === 0 && <p className="muted small">No plays recorded for this file.</p>}
        {d.plays.slice(0, 8).map((p) => (
          <p key={p.row_id} className={p.mine ? "issue-play mine" : "issue-play"}>
            {p.mine && <span className="pill">reporter</span>}
            <strong>{p.user_name ?? "Unknown"}</strong> <span className="muted small">{playedAt(p.started)}</span>
            <span className="muted small">
              {[p.player, p.platform, p.location === "wan" ? "remote" : p.location].filter(Boolean).join(" · ")}
            </span>
            <span className={p.transcode_decision === "transcode" ? "pill warn" : "pill"}>
              {p.transcode_decision ?? "unknown"}
            </span>
            {p.stalls > 0 && <span className="pill bad">{p.stalls} stalls, {p.stall_seconds}s</span>}
            {p.percent_complete != null && <span className="muted small">{Math.round(p.percent_complete)}%</span>}
          </p>
        ))}
        {d.rating_key && nav.filterTo && (
          <button className="btn" onClick={() => nav.filterTo?.("History", { rating_key: d.rating_key!, ratingKeyLabel: d.title ?? "" })}>
            Every play in History
          </button>
        )}
      </section>

      {d.other_reports.length > 0 && (
        <section className="card-section">
          <h3>Reported before</h3>
          {d.other_reports.map((o) => (
            <p key={o.id} className="small">
              <span className={o.status === "open" ? "pill warn" : "pill ok"}>{o.status}</span> {TYPES[o.issue_type]}:{" "}
              {o.message} <span className="muted">{o.reporter_name}, {when(o.created_at)}</span>
            </p>
          ))}
        </section>
      )}

      <section className="card-section">
        <h3>The file</h3>
        {d.file ? (
          <FileCardView f={d.file} days={365} />
        ) : (
          <p className="muted small">
            This server has no file for the reported item{d.rating_key ? ` (${d.rating_key})` : ""}. It may have been
            removed, or the report names something never added.
          </p>
        )}
      </section>
    </div>
  );
}
