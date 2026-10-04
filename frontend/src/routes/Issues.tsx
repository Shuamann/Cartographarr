import { useState } from "react";
import Loading from "../components/Loading";
import { api, useApi } from "../lib/api";
import { FileCardView, type FileDetail } from "./Library";
import { useNav } from "../lib/nav";
import SettingsLink, { SETTINGS_PAGES } from "../components/SettingsLink";

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

type Context = {
  row_id: number;
  started: number | null;
  player: string | null;
  platform: string | null;
  product: string | null;
  location: string | null;
  transcode_decision: string | null;
  percent_complete: number | null;
  stalls: number;
  stall_seconds: number;
};

type IssueDetail = IssueRow & {
  context: Context | null;
  comment_list: { message: string | null; author: string | null; created_at: string }[];
  tmdb_id: number | null;
  file: FileDetail | null;
  file_title: string | null;
  plays: Play[];
  streams: { platform: string | null; cause: string | null; buffers: number | null; started_at: string | null; user_name: string | null }[];
  other_reports?: IssueRow[];
};

type Listing = {
  items: IssueRow[];
  open: number;
  resolved: number;
  by_type: Record<string, number>;
  seerr_url: string | null;
  seerr_configured: boolean;
  mine_only: boolean;
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
  const [raising, setRaising] = useState(false);
  const query = `/issues?status=${status}${type ? `&issue_type=${type}` : ""}`;
  const data = useApi<Listing>(query, [status, type]);

  if (data.error) return <p className="note bad-note pad" role="alert">{data.error}</p>;
  if (!data.data) return <div className="pad"><Loading label="Reading reported issues" /></div>;
  const d = data.data;

  return (
    <div className="pad">
      <div className="row-between wrap">
        <h1>Issues</h1>
        <div className="row wrap">
          <button className="btn create" onClick={() => setRaising(!raising)}>
            {raising ? "Cancel" : "+ Report"}
          </button>
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
        {d.mine_only
          ? "What you have reported, and what came of it. Reporting from History carries the details of that play with it, so nobody has to ask what device you were on."
          : "What people reported, with the file, the plays behind it and what went wrong during them. Issues are kept here, and anything reported in Seerr is read in every five minutes."}
      </p>

      {raising && (
        <RaiseIssue
          onDone={(id) => {
            setRaising(false);
            data.reload();
            setStatus("open");
            setOpen(id);
          }}
        />
      )}

      {d.items.length === 0 && (
        <p className="note">
          {d.mine_only
            ? "You have not reported anything. If something looks or sounds wrong, report it here, or from a play in your History."
            : d.seerr_configured
              ? `Nothing reported${status === "open" ? " and still open" : ""}. Reports made in Seerr appear here within five minutes.`
              : (
                  <>
                    Seerr is not set up, so there is nothing to read. Add it under{" "}
                    <SettingsLink page={SETTINGS_PAGES.mediaApps}>Settings, Media apps</SettingsLink> and reports will
                    appear here.
                  </>
                )}
        </p>
      )}

      <div className="issue-list">
        {d.items.map((i) => (
          <div key={i.id}>
            <button className={open === i.id ? "issue-row on" : "issue-row"} onClick={() => setOpen(open === i.id ? null : i.id)}>
              <span className={i.status === "open" ? "pill warn" : "pill ok"}>{i.status}</span>
              <span className="pill">{TYPES[i.issue_type]}</span>
              <span className="issue-title clip">
                <strong>{i.title ?? (i.rating_key ? `Item ${i.rating_key}` : "No longer in the library")}</strong>
                <span className="muted small clip">{i.message}</span>
              </span>
              <span className="muted small">{i.reporter_name ?? "Someone"}</span>
              <span className="muted small">{when(i.created_at)}</span>
            </button>
            {open === i.id && (
              <IssueCard id={i.id} seerrUrl={d.seerr_url} mineOnly={d.mine_only} onChanged={data.reload} />
            )}
          </div>
        ))}
      </div>
    </div>
  );
}

function IssueCard({
  id,
  seerrUrl,
  mineOnly,
  onChanged,
}: {
  id: number;
  seerrUrl: string | null;
  mineOnly: boolean;
  onChanged: () => void;
}) {
  const nav = useNav();
  const detail = useApi<IssueDetail>(`/issues/${id}`);
  const [note, setNote] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [warning, setWarning] = useState<string | null>(null);

  async function act(run: () => Promise<{ warning?: string | null }>) {
    setBusy(true);
    setError(null);
    try {
      // The decision is recorded here whatever Seerr does, so a Seerr failure
      // is a note rather than an error.
      const answer = await run();
      setWarning(answer?.warning ?? null);
      detail.reload();
      onChanged();
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setBusy(false);
    }
  }

  if (detail.error) return <p className="note bad-note" role="alert">{detail.error}</p>;
  if (!detail.data) return <Loading compact label="Reading the report" />;
  const d = detail.data;
  const mine = d.plays.filter((p) => p.mine);
  const fromSeerr = d.source === "seerr" && d.seerr_id != null;

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
        {d.context && (
          <p className="note">
            Reported while watching on{" "}
            <strong>{[d.context.player, d.context.platform].filter(Boolean).join(" · ") || "an unknown device"}</strong>
            {d.context.started ? `, ${new Date(d.context.started * 1000).toLocaleString()}` : ""}
            {d.context.location === "wan" ? ", remotely" : d.context.location === "lan" ? ", on the local network" : ""}
            {d.context.transcode_decision ? `, ${d.context.transcode_decision}` : ""}
            {d.context.percent_complete != null ? `, ${Math.round(d.context.percent_complete)}% through` : ""}
            {d.context.stalls > 0
              ? `. It stalled ${d.context.stalls} ${d.context.stalls === 1 ? "time" : "times"} during that play, for ${d.context.stall_seconds}s.`
              : "."}
          </p>
        )}
        <p className="muted small">
          {d.season && d.episode ? `Season ${d.season}, episode ${d.episode}. ` : ""}
          {d.seerr_id && seerrUrl && (
            <a href={`${seerrUrl}/issues/${d.seerr_id}`} target="_blank" rel="noreferrer">
              Open in Seerr
            </a>
          )}
        </p>
        {error && <p className="note bad-note" role="alert">{error}</p>}
        {warning && <p className="note warn-note">{warning}</p>}
        <div className="row wrap">
          <input placeholder="Add a note" value={note} onChange={(e) => setNote(e.target.value)} />
          <button
            className="btn"
            disabled={busy || !note.trim()}
            onClick={async () => {
              await act(() => api.post(`/issues/${id}/comment`, { message: note }));
              setNote("");
            }}
          >
            Comment
          </button>
          {/* Whoever runs the server decides when something is closed. */}
          {!mineOnly && (
            <button
              className="tab"
              disabled={busy}
              onClick={() => act(() => api.post(`/issues/${id}/status`, { status: d.status === "open" ? "resolved" : "open" }))}
            >
              {d.status === "open" ? "Mark resolved" : "Reopen"}
            </button>
          )}
        </div>
        {fromSeerr && (
          <p className="muted small">
            This came from Seerr, so comments and resolutions go back there too, signed with your name.
          </p>
        )}
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

      {(d.other_reports ?? []).length > 0 && (
        <section className="card-section">
          <h3>Reported before</h3>
          {(d.other_reports ?? []).map((o) => (
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


/* Report a problem from here, starting from what was watched.
 *
 * A text box asks someone to name a file, which is the one thing they are
 * least likely to know. What they do know is "that thing playing now", or
 * "that show, the one with the fire". So: what is playing and what was watched
 * lately first, then shows and films by name, then episodes under a show, with
 * posters all the way through. */
type Card = {
  rating_key: number;
  title: string;
  show: string | null;
  season: number | null;
  episode: number | null;
  media_type: string | null;
  year: number | null;
  summary: string | null;
  playing?: boolean;
};

type Show = { rating_key: number; title: string; episodes: number; season_count: number };

function poster(ratingKey: number, width = 120): string {
  return `/api/media/${ratingKey}/image?width=${width}&height=${Math.round(width * 1.5)}`;
}

function Poster({ ratingKey, alt }: { ratingKey: number; alt: string }) {
  return (
    <img
      className="pick-poster"
      src={poster(ratingKey)}
      alt={alt}
      loading="lazy"
      onError={(e) => ((e.currentTarget as HTMLImageElement).style.visibility = "hidden")}
    />
  );
}

function episodeLabel(card: Card): string {
  if (card.season == null || card.episode == null) return card.title;
  const code = `S${String(card.season).padStart(2, "0")}E${String(card.episode).padStart(2, "0")}`;
  return `${code} ${card.title.includes(" - ") ? card.title.split(" - ").slice(-1)[0] : card.title}`;
}

function RaiseIssue({ onDone }: { onDone: (id: number) => void }) {
  const [term, setTerm] = useState("");
  const [picked, setPicked] = useState<Card | null>(null);
  const [show, setShow] = useState<Show | null>(null);
  const [kind, setKind] = useState("other");
  const [message, setMessage] = useState("");
  const [error, setError] = useState<string | null>(null);

  const searching = term.trim().length > 1;
  const recent = useApi<{ items: Card[] }>(!picked && !show && !searching ? "/issues/recent" : null);
  const found = useApi<{ shows: Show[]; films: Card[] }>(
    !picked && !show && searching ? `/issues/search?q=${encodeURIComponent(term.trim())}` : null,
    [term],
  );
  const listing = useApi<{ show: string; episodes: Card[] }>(show && !picked ? `/issues/shows/${show.rating_key}/episodes` : null, [show]);

  async function report() {
    setError(null);
    try {
      const made = await api.post<{ id: number }>("/issues", {
        rating_key: picked!.rating_key,
        issue_type: kind,
        message,
      });
      onDone(made.id);
    } catch (err) {
      setError((err as Error).message);
    }
  }

  return (
    <section className="card-section raise">
      <h3>Raise an issue</h3>
      {error && <p className="note bad-note" role="alert">{error}</p>}

      {picked ? (
        <>
          <div className="pick chosen">
            <Poster ratingKey={picked.rating_key} alt="" />
            <div className="min0">
              <strong>{picked.show ? `${picked.show} ${episodeLabel(picked)}` : picked.title}</strong>
              {picked.year && <span className="muted small"> {picked.year}</span>}
              {picked.summary && <p className="muted small clamp">{picked.summary}</p>}
            </div>
            <button className="tab" onClick={() => setPicked(null)}>
              Change
            </button>
          </div>
          <div className="row wrap">
            <select value={kind} onChange={(e) => setKind(e.target.value)}>
              {Object.keys(TYPES).map((t) => (
                <option key={t} value={t}>
                  {TYPES[t]}
                </option>
              ))}
            </select>
            <input placeholder="What is wrong?" value={message} onChange={(e) => setMessage(e.target.value)} />
            <button className="btn" disabled={!message.trim()} onClick={report}>
              Report it
            </button>
          </div>
        </>
      ) : show ? (
        <>
          <p className="row">
            <button className="tab" onClick={() => setShow(null)}>
              Back
            </button>
            <strong>{show.title}</strong>
            <span className="muted small">
              {show.episodes} episodes across {show.season_count} {show.season_count === 1 ? "season" : "seasons"}
            </span>
          </p>
          {!listing.data && <Loading compact label="Reading episodes" />}
          <div className="pick-list">
            {(listing.data?.episodes ?? []).map((e) => (
              <button key={e.rating_key} className="pick" onClick={() => setPicked(e)}>
                <Poster ratingKey={e.rating_key} alt="" />
                <span className="min0">
                  <strong>{episodeLabel(e)}</strong>
                  {e.summary && <span className="muted small clamp">{e.summary}</span>}
                </span>
              </button>
            ))}
          </div>
        </>
      ) : (
        <>
          <input placeholder="Search for a film or a show" value={term} onChange={(e) => setTerm(e.target.value)} />
          {!searching && (
            <>
              <h4 className="pick-head">Playing now, and lately watched</h4>
              {!recent.data && <Loading compact label="Reading what has been watched" />}
              <div className="pick-list">
                {(recent.data?.items ?? []).map((c) => (
                  <button key={c.rating_key} className="pick" onClick={() => setPicked(c)}>
                    <Poster ratingKey={c.rating_key} alt="" />
                    <span className="min0">
                      <strong>{c.show ? `${c.show} ${episodeLabel(c)}` : c.title}</strong>
                      {c.playing && <span className="pill ok">playing</span>}
                      {c.summary && <span className="muted small clamp">{c.summary}</span>}
                    </span>
                  </button>
                ))}
                {recent.data?.items?.length === 0 && <p className="muted small">Nothing has been watched yet.</p>}
              </div>
            </>
          )}
          {searching && (
            <>
              {!found.data && <Loading compact label="Looking" />}
              {(found.data?.shows ?? []).length > 0 && <h4 className="pick-head">Shows</h4>}
              <div className="pick-list">
                {(found.data?.shows ?? []).map((sh) => (
                  <button key={sh.rating_key} className="pick" onClick={() => setShow(sh)}>
                    <Poster ratingKey={sh.rating_key} alt="" />
                    <span className="min0">
                      <strong>{sh.title}</strong>
                      <span className="muted small">
                        {sh.episodes} episodes, pick one
                      </span>
                    </span>
                  </button>
                ))}
              </div>
              {(found.data?.films ?? []).length > 0 && <h4 className="pick-head">Films</h4>}
              <div className="pick-list">
                {(found.data?.films ?? []).map((f) => (
                  <button key={f.rating_key} className="pick" onClick={() => setPicked(f)}>
                    <Poster ratingKey={f.rating_key} alt="" />
                    <span className="min0">
                      <strong>{f.title}</strong>
                      {f.year && <span className="muted small"> {f.year}</span>}
                      {f.summary && <span className="muted small clamp">{f.summary}</span>}
                    </span>
                  </button>
                ))}
              </div>
              {found.data && found.data.shows.length === 0 && found.data.films.length === 0 && (
                <p className="muted small">Nothing by that name. It may not have been added, or synced yet.</p>
              )}
            </>
          )}
        </>
      )}
    </section>
  );
}
