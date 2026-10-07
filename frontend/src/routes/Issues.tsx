import { useState } from "react";
import Loading from "../components/Loading";
import { api, useApi } from "../lib/api";
import { type FileDetail, fileFormat, mbps, size } from "./Library";
import { useNav } from "../lib/nav";
import SettingsLink, { SETTINGS_PAGES } from "../components/SettingsLink";

/* Issues: what people reported, next to what this server knows.
 *
 * Seerr collects the sentence ("audio is out of sync"). Everything that
 * explains it is already here: the file's tracks and bitrate, who played it on
 * what, whether it transcoded for them, and whether it stalled while they
 * watched. One page, so the report and its evidence are read together.
 *
 * A row answers the first question before it is opened: is it the file, or is
 * it them? The reporter's plays sit beside everybody else's, so somebody who
 * stalled three times while four other people played it cleanly reads
 * differently from a file that stalls for everyone.
 */

type Kind = "video" | "audio" | "subtitles" | "other";

type IssueRow = {
  id: number;
  seerr_id: number | null;
  source: string;
  issue_type: Kind;
  status: "open" | "resolved";
  message: string | null;
  title: string | null;
  show_title: string | null;
  episode_title: string | null;
  in_library: boolean;
  media_type: string | null;
  rating_key: number | null;
  season: number | null;
  episode: number | null;
  year: number | null;
  reporter_name: string | null;
  reporter_user_id: number | null;
  comments: number;
  created_at: string | null;
  updated_at: string | null;
  // From Seerr, and Seerr no longer lists it. Kept here regardless.
  seerr_gone?: boolean;
  // The reporter's plays of the file against everybody else's. A viewer is
  // only ever sent their own, so the second half is missing for them.
  reporter_plays?: number;
  reporter_stalls?: number;
  other_people?: number;
  other_plays?: number;
  other_stalls?: number;
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
  other_reports?: IssueRow[];
  // Whether the file is on the disk now, which the library's own row cannot
  // say: it records where the file was at the last scan.
  whereis?: { state: "present" | "gone" | "unreachable" | "unknown"; path: string | null; size: number | null; changed?: boolean };
  found_under?: number | null;
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

const TYPES: Record<Kind, string> = { video: "Video", audio: "Audio", subtitles: "Subtitles", other: "Other" };
const KINDS = Object.keys(TYPES) as Kind[];

function plural(n: number, one: string, many = `${one}s`): string {
  return `${n} ${n === 1 ? one : many}`;
}

function parsed(iso: string | null): Date | null {
  if (!iso) return null;
  return new Date(/[zZ]|[+-]\d\d:\d\d$/.test(iso) ? iso : `${iso}Z`);
}

function when(iso: string | null): string {
  return parsed(iso)?.toLocaleString() ?? "";
}

/* Short enough to sit on one line of a row. The full time is in the detail. */
function ago(iso: string | null): string {
  const t = parsed(iso);
  if (!t) return "";
  const minutes = Math.round((Date.now() - t.getTime()) / 60000);
  if (minutes < 2) return "just now";
  if (minutes < 60) return `${minutes} minutes ago`;
  const hours = Math.round(minutes / 60);
  if (hours < 24) return plural(hours, "hour") + " ago";
  const days = Math.round(hours / 24);
  if (days === 1) return "yesterday";
  if (days < 30) return `${days} days ago`;
  return t.toLocaleDateString();
}

function playedAt(seconds: number | null): string {
  return seconds ? new Date(seconds * 1000).toLocaleString() : "";
}

/* How a set of plays went, in a few words: "2 plays, stalled 3 times". */
function playsText(plays: number, stalls: number): string {
  if (!plays) return stalls ? `no plays, ${plural(stalls, "stall")}` : "None recorded";
  return `${plural(plays, "play")}, ${stalls ? `stalled ${plural(stalls, "time")}` : "no stalls"}`;
}

function othersText(r: IssueRow): string {
  if (!r.other_people) return "Nobody else has played it";
  return `${plural(r.other_people, "person", "people")}, ${r.other_stalls ? `stalled ${plural(r.other_stalls, "time")}` : "no stalls"}`;
}

function code(season: number, episode: number): string {
  return `S${String(season).padStart(2, "0")}E${String(episode).padStart(2, "0")}`;
}

/* The title, in parts that give way in the right order.
 *
 * A report keeps one string, "The Show - The Episode", and clipping that from
 * the end can cut off the season and episode, which say which one is being
 * reported. Split into parts, the same classes as the stream tiles decide
 * what gives way: the episode's own name first, a very long show name only
 * past most of the line, and the numbers never. */
function IssueTitle({ r }: { r: IssueRow }) {
  const full = r.title ?? (r.rating_key ? `Item ${r.rating_key}` : "No longer in the library");
  const numbered = r.season != null && r.episode != null;
  const show = r.show_title ?? (numbered && full.includes(" - ") ? full.slice(0, full.indexOf(" - ")) : null);
  if (!numbered || !show) {
    return <span className="media-row-title" title={full}>{full}</span>;
  }
  const name = r.episode_title ?? (full.includes(" - ") ? full.slice(full.indexOf(" - ") + 3) : null);
  return (
    <span className="media-row-title card-title" title={[show, code(r.season!, r.episode!), name].filter(Boolean).join(" - ")}>
      <span className="card-title-show">{show}</span>
      <span className="muted card-title-sep">-</span>
      <span className="card-title-code">{code(r.season!, r.episode!)}</span>
      {name ? (
        <>
          <span className="muted card-title-sep">-</span>
          <span className="card-title-name">{name}</span>
        </>
      ) : null}
    </span>
  );
}

function StatusPill({ status }: { status: IssueRow["status"] }) {
  return <span className={status === "open" ? "pill warn" : "pill ok"}>{status === "open" ? "Open" : "Resolved"}</span>;
}

export default function Issues() {
  const [status, setStatus] = useState<"open" | "resolved" | "all">("open");
  const [type, setType] = useState<"" | Kind>("");
  const [open, setOpen] = useState<number | null>(null);
  const [raising, setRaising] = useState(false);
  const [busy, setBusy] = useState<number | null>(null);
  // What came of acting from a row, said under that row: there is nowhere
  // else on the page it belongs.
  const [notice, setNotice] = useState<{ id: number; text: string; bad: boolean } | null>(null);
  const query = `/issues?status=${status}${type ? `&issue_type=${type}` : ""}`;
  const data = useApi<Listing>(query, [status, type]);

  if (data.error) return <p className="note bad-note pad" role="alert">{data.error}</p>;
  if (!data.data) return <div className="pad"><Loading label="Reading reported issues" /></div>;
  const d = data.data;
  const admin = !d.mine_only;

  /* Closing and reopening are on the row, because they are what an admin
     came to do and the evidence for most of them is already on it. Nothing
     asks first: either way is one click to undo. */
  async function mark(r: IssueRow) {
    setBusy(r.id);
    setNotice(null);
    try {
      const answer = await api.post<{ warning?: string | null }>(`/issues/${r.id}/status`, {
        status: r.status === "open" ? "resolved" : "open",
      });
      // Recorded here whatever Seerr made of it, so a Seerr failure is a note
      // rather than an error.
      if (answer?.warning) setNotice({ id: r.id, text: answer.warning, bad: false });
      data.reload();
    } catch (err) {
      setNotice({ id: r.id, text: (err as Error).message, bad: true });
    } finally {
      setBusy(null);
    }
  }

  return (
    <div className="pad">
      <div className="row-between wrap">
        <h1>Issues</h1>
        <button className={raising ? "btn create" : "btn primary create"} onClick={() => setRaising(!raising)}>
          {raising ? "Cancel" : "Report a problem"}
        </button>
      </div>

      <div className="issue-filters">
        <div className="segmented" role="group" aria-label="Which issues">
          {(["open", "resolved", "all"] as const).map((s) => (
            <button key={s} className={status === s ? "seg on" : "seg"} onClick={() => setStatus(s)}>
              {s === "open" ? `Open ${d.open}` : s === "resolved" ? `Resolved ${d.resolved}` : "All"}
            </button>
          ))}
        </div>
        <div className="segmented" role="group" aria-label="What kind">
          <button className={type === "" ? "seg on" : "seg"} onClick={() => setType("")}>
            Every kind
          </button>
          {KINDS.map((t) => (
            <button key={t} className={type === t ? "seg on" : "seg"} onClick={() => setType(t)}>
              {TYPES[t]}
              {d.by_type[t] ? ` ${d.by_type[t]}` : ""}
            </button>
          ))}
        </div>
      </div>

      <p className="muted">
        {admin
          ? "What people reported, beside the file, the plays behind it and what went wrong during them. Reports made in Seerr are read in every five minutes."
          : "What you have reported, and what came of it. Reporting from a play in History carries that play with it, so nobody has to ask what you were watching on."}
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
          {!admin
            ? "You have not reported anything. If something looks or sounds wrong, report it here, or from a play in your History."
            : d.seerr_configured
              ? `Nothing reported${status === "open" ? " and still open" : ""}. Reports made in Seerr appear here within five minutes.`
              : (
                  <>
                    Nothing reported here yet. Reports made in Seerr can be read in too: add it under{" "}
                    <SettingsLink page={SETTINGS_PAGES.mediaApps}>Settings, Media apps</SettingsLink>.
                  </>
                )}
        </p>
      )}

      <div className="issue-list">
        {d.items.map((r) => {
          const toggle = () => setOpen(open === r.id ? null : r.id);
          const replies = Math.max(0, r.comments - 1);
          return (
            <div key={r.id}>
              {/* A div rather than a button, because the action on it is a
                  button and a button inside a button is neither valid nor well
                  behaved. It keeps the keyboard behaviour a button has. */}
              <div
                className={open === r.id ? "media-row on" : "media-row"}
                role="button"
                tabIndex={0}
                aria-expanded={open === r.id}
                onClick={toggle}
                onKeyDown={(e) => {
                  // Only the row's own keys: Enter on the button inside it
                  // bubbles up here too, and would open the row as well.
                  if (e.target !== e.currentTarget) return;
                  if (e.key === "Enter" || e.key === " ") {
                    e.preventDefault();
                    toggle();
                  }
                }}
              >
                {r.rating_key ? (
                  <span
                    className="media-row-art"
                    aria-hidden="true"
                    style={{ backgroundImage: `url(/api/media/${r.rating_key}/image?kind=art&width=900&height=506)` }}
                  />
                ) : null}
                {r.rating_key ? (
                  <img
                    className="media-row-poster"
                    src={`/api/media/${r.rating_key}/image?width=92&height=138`}
                    alt=""
                    loading="lazy"
                    onError={(e) => ((e.currentTarget as HTMLImageElement).style.visibility = "hidden")}
                  />
                ) : (
                  <span className="media-row-poster" />
                )}

                <span className="media-row-what">
                  {r.year ? <span className="media-row-year">{r.year}</span> : null}
                  <IssueTitle r={r} />
                  {/* The one thing that is wrong. The kind leads, so it
                      survives a long message being cut short. */}
                  <span className="media-row-note" title={r.message ?? undefined}>
                    <strong>{TYPES[r.issue_type]}</strong>
                    {r.message ? `: ${r.message}` : ""}
                  </span>
                </span>

                <dl className="media-row-facts">
                  <dt>Status</dt>
                  <dd>
                    <StatusPill status={r.status} />
                    {replies > 0 && <span className="muted">{plural(replies, "reply", "replies")}</span>}
                  </dd>
                  <dt>Reported</dt>
                  <dd>{admin ? `${ago(r.created_at)} by ${r.reporter_name ?? "someone"}` : ago(r.created_at)}</dd>
                  {r.rating_key && !r.in_library ? (
                    <>
                      <dt>File</dt>
                      <dd>
                        <span className="pill bad">Not in the library</span>
                      </dd>
                    </>
                  ) : (
                    <>
                      <dt>{admin ? "Reporter" : "Your plays"}</dt>
                      <dd className={r.reporter_stalls ? "issue-stalled" : undefined}>
                        {playsText(r.reporter_plays ?? 0, r.reporter_stalls ?? 0)}
                      </dd>
                      {admin && (
                        <>
                          <dt>Others</dt>
                          <dd className={r.other_stalls ? "issue-stalled" : undefined}>{othersText(r)}</dd>
                        </>
                      )}
                    </>
                  )}
                </dl>

                <span className="media-row-do">
                  {admin ? (
                    <button
                      className={r.status === "open" ? "btn primary" : "btn"}
                      disabled={busy === r.id}
                      onClick={(e) => {
                        e.stopPropagation();
                        void mark(r);
                      }}
                    >
                      {r.status === "open" ? "Resolve" : "Reopen"}
                    </button>
                  ) : (
                    <span className={open === r.id ? "btn" : "btn primary"} aria-hidden="true">
                      {open === r.id ? "Hide" : "View"}
                    </span>
                  )}
                </span>
              </div>
              {notice?.id === r.id && (
                <p className={notice.bad ? "note bad-note" : "note warn-note"} role={notice.bad ? "alert" : undefined}>
                  {notice.text}
                </p>
              )}
              {open === r.id && <IssueCard id={r.id} seerrUrl={d.seerr_url} admin={admin} onChanged={data.reload} />}
            </div>
          );
        })}
      </div>
    </div>
  );
}

function Pair({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div className="spec-pair">
      <dt>{label}</dt>
      <dd>{children}</dd>
    </div>
  );
}

function IssueCard({
  id,
  seerrUrl,
  admin,
  onChanged,
}: {
  id: number;
  seerrUrl: string | null;
  admin: boolean;
  onChanged: () => void;
}) {
  const nav = useNav();
  const detail = useApi<IssueDetail>(`/issues/${id}`);
  const [note, setNote] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [warning, setWarning] = useState<string | null>(null);

  async function act(steps: (() => Promise<{ warning?: string | null }>)[]) {
    setBusy(true);
    setError(null);
    try {
      // The decision is recorded here whatever Seerr does, so a Seerr failure
      // is a note rather than an error.
      let said: string | null = null;
      for (const step of steps) said = (await step())?.warning ?? said;
      setWarning(said);
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
  const fromSeerr = d.source === "seerr" && d.seerr_id != null;
  const typed = note.trim();
  const comment = () => api.post<{ warning?: string | null }>(`/issues/${id}/comment`, { message: typed });
  const flip = () =>
    api.post<{ warning?: string | null }>(`/issues/${id}/status`, { status: d.status === "open" ? "resolved" : "open" });
  const c = d.context;

  /* Everything the row already says (status, who reported it and when, how
     their plays went against everybody else's) stays on the row. The card
     holds only what the row has no room for. */
  return (
    <div className="issue-card">
      <section className="card-section">
        <div className="issue-thread">
          {d.comment_list.length === 0 && <p className="muted small">No message.</p>}
          {d.comment_list.map((n, i) => (
            <div key={i} className="issue-note">
              <div className="issue-note-head">
                <strong>{n.author ?? "Someone in Seerr"}</strong>
                <span className="muted small" title={when(n.created_at)}>
                  {ago(n.created_at)}
                </span>
              </div>
              <p>{n.message}</p>
            </div>
          ))}
        </div>

        {error && <p className="note bad-note" role="alert">{error}</p>}
        {warning && <p className="note warn-note">{warning}</p>}
        <div className="issue-reply">
          <input
            placeholder={admin ? "Add a note, or say what was done" : "Add a note"}
            aria-label="A note on this report"
            value={note}
            onChange={(e) => setNote(e.target.value)}
          />
          <button
            className="btn"
            disabled={busy || !typed}
            onClick={async () => {
              await act([comment]);
              setNote("");
            }}
          >
            Comment
          </button>
          {/* Whoever runs the server decides when something is closed. A note
              typed first goes with it, so saying what was done and closing it
              is one click rather than two. */}
          {admin && (
            <button
              className={d.status === "open" ? "btn primary" : "btn"}
              disabled={busy}
              onClick={async () => {
                await act(typed ? [comment, flip] : [flip]);
                setNote("");
              }}
            >
              {d.status === "open" ? (typed ? "Comment and resolve" : "Resolve") : "Reopen"}
            </button>
          )}
        </div>
        {fromSeerr && admin && d.seerr_gone && (
          <p className="muted small issue-aside">
            From Seerr, which no longer lists it. It is kept here, and notes and resolutions stay here too.
          </p>
        )}
        {fromSeerr && admin && !d.seerr_gone && (
          <p className="muted small issue-aside">
            From Seerr: notes and resolutions go back there, signed with your name.
            {seerrUrl && (
              <>
                {" "}
                <a href={`${seerrUrl}/issues/${d.seerr_id}`} target="_blank" rel="noreferrer">
                  Open in Seerr
                </a>
              </>
            )}
          </p>
        )}
      </section>

      {/* The play it was reported from, which is the half nobody remembers to
          write down. */}
      {c && (
        <section className="card-section">
          <h3>The play it was reported from</h3>
          <dl className="spec">
            <Pair label="Device">{[c.player, c.product ?? c.platform].filter(Boolean).join(", ") || "Not recorded"}</Pair>
            <Pair label="Network">{c.location === "wan" ? "Remote" : c.location === "lan" ? "Local" : "Not recorded"}</Pair>
            <Pair label="Playback">
              <span className={c.transcode_decision === "transcode" ? "pill warn" : "pill"}>{c.transcode_decision ?? "not recorded"}</span>
            </Pair>
            <Pair label="Stalls">
              <span className={c.stalls ? "issue-stalled" : undefined}>
                {c.stalls ? `${plural(c.stalls, "time")}, ${c.stall_seconds}s in all` : "None"}
              </span>
            </Pair>
            {c.percent_complete != null && <Pair label="Watched">{Math.round(c.percent_complete)}%</Pair>}
          </dl>
        </section>
      )}

      {d.plays.length > 0 && (
        <section className="card-section">
          <h3>{admin ? "Plays of this file" : "Your plays of this file"}</h3>
          <div className="issue-plays-wrap">
            <table className="issue-plays">
              <thead>
                <tr>
                  {admin && <th>Who</th>}
                  <th>When</th>
                  <th>On</th>
                  <th>Where</th>
                  <th>Playback</th>
                  <th>Stalls</th>
                  <th>Watched</th>
                </tr>
              </thead>
              <tbody>
                {d.plays.slice(0, 10).map((p) => (
                  <tr key={p.row_id} className={p.mine && admin ? "mine" : undefined}>
                    {admin && (
                      <td>
                        {p.user_name ?? "Unknown"}
                        {p.mine && <> <span className="pill">reporter</span></>}
                      </td>
                    )}
                    <td>{playedAt(p.started)}</td>
                    <td className="issue-plays-device">{[p.player, p.platform].filter(Boolean).join(", ") || "Unknown"}</td>
                    <td>{p.location === "wan" ? "Remote" : p.location === "lan" ? "Local" : ""}</td>
                    <td>
                      <span className={p.transcode_decision === "transcode" ? "pill warn" : "pill"}>{p.transcode_decision ?? "unknown"}</span>
                    </td>
                    <td className={p.stalls ? "issue-stalled" : "muted"}>{p.stalls ? `${p.stalls}, ${p.stall_seconds}s` : "None"}</td>
                    <td>{p.percent_complete != null ? `${Math.round(p.percent_complete)}%` : ""}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          {d.rating_key && nav.filterTo && (
            <button className="btn" onClick={() => nav.filterTo?.("History", { rating_key: d.rating_key!, ratingKeyLabel: d.title ?? "" })}>
              {d.plays.length > 10 ? `All ${d.plays.length} in History` : "Open in History"}
            </button>
          )}
        </section>
      )}

      {(d.other_reports ?? []).length > 0 && (
        <section className="card-section">
          <h3>Reported before</h3>
          <dl className="spec">
            {(d.other_reports ?? []).map((o) => (
              <Pair key={o.id} label={TYPES[o.issue_type]}>
                <StatusPill status={o.status} />
                <span className="clip" title={o.message ?? undefined}>{o.message}</span>
                <span className="muted">
                  {o.reporter_name ?? "someone"}, {ago(o.created_at)}
                </span>
              </Pair>
            ))}
          </dl>
        </section>
      )}

      <section className="card-section">
        <h3>The file</h3>
        <IssueFile d={d} admin={admin} />
      </section>
    </div>
  );
}

const SEVERITY: Record<string, { label: string; tone: string }> = {
  high: { label: "Fix first", tone: "pill bad" },
  medium: { label: "Worth fixing", tone: "pill warn" },
  low: { label: "Tidy up", tone: "pill" },
};

/* The file, as evidence rather than as a workshop.
 *
 * What it is, whether it is on the disk, and what is already known to be wrong
 * with it, each on a line. Replacing it, searching for another copy and
 * rewriting its tracks are the Library's job and stay there, one click away:
 * pulled in here they were most of the card, and none of them is what a
 * report is asking. */
function IssueFile({ d, admin }: { d: IssueDetail; admin: boolean }) {
  const nav = useNav();
  const f = d.file;
  const w = d.whereis;
  if (!f) {
    return (
      <p className="muted small">
        {d.found_under
          ? `Nothing in the library under the reported key, but the same title is here under ${d.found_under}, so Plex has renumbered it since the report.`
          : "This server has no file for it. It may have been removed, or the report names something never added."}
      </p>
    );
  }
  const name = w?.path ? w.path.split(/[\\/]/).pop() : null;
  return (
    <>
      <dl className="spec">
        <Pair label="Format">{fileFormat(f) || "Not checked yet"}</Pair>
        <Pair label="Size">{[size(w?.size ?? f.file_size), mbps(f.file_bitrate)].filter(Boolean).join(", ") || "Not known"}</Pair>
        {w && w.state !== "unknown" && (w.state !== "unreachable" || admin) && (
          <Pair label="Disk">
            {w.state === "present" ? (
              w.changed ? "There, replaced since the last scan" : "There"
            ) : w.state === "gone" ? (
              <span className="pill bad">Missing</span>
            ) : (
              <span title="This container cannot reach where the file is kept. Mount it, or set the path map, under Settings, Library.">
                Cannot be checked from here
              </span>
            )}
          </Pair>
        )}
        {admin && name && (
          <Pair label="File">
            {/* The name, which is the part that says which file. The folders
                above it are in the tooltip. */}
            <span className="issue-file-name" title={w?.path ?? undefined}>{name}</span>
          </Pair>
        )}
      </dl>
      {f.findings.length > 0 ? (
        <ul className="issue-findings">
          {f.findings.map((x) => (
            <li key={x.key}>
              {admin && <span className={(SEVERITY[x.severity] ?? SEVERITY.low).tone}>{(SEVERITY[x.severity] ?? SEVERITY.low).label}</span>}
              <span>{x.title}</span>
            </li>
          ))}
        </ul>
      ) : (
        <p className="muted small">Nothing about the file itself stands out.</p>
      )}
      {admin && nav.openLibrary && (
        <button className="btn" onClick={() => nav.openLibrary?.({ ratingKey: f.rating_key, mediaType: f.media_type ?? "movie" })}>
          Fix it in the Library
        </button>
      )}
    </>
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
  const [kind, setKind] = useState<Kind>("other");
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
            <button className="btn" onClick={() => setPicked(null)}>
              Change
            </button>
          </div>
          {/* Four kinds is a choice to see all at once, not to open a list
              for, and a select sits at a different height from the buttons
              beside it. */}
          <div className="issue-reply">
            <div className="segmented" role="group" aria-label="What kind of problem">
              {KINDS.map((t) => (
                <button key={t} className={kind === t ? "seg on" : "seg"} onClick={() => setKind(t)}>
                  {TYPES[t]}
                </button>
              ))}
            </div>
            <input
              placeholder="What is wrong?"
              aria-label="What is wrong"
              value={message}
              onChange={(e) => setMessage(e.target.value)}
            />
            <button className="btn primary" disabled={!message.trim()} onClick={report}>
              Report it
            </button>
          </div>
        </>
      ) : show ? (
        <>
          <p className="row">
            <button className="btn" onClick={() => setShow(null)}>
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
          <input placeholder="Search for a film or a show" aria-label="Search for a film or a show" value={term} onChange={(e) => setTerm(e.target.value)} />
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
