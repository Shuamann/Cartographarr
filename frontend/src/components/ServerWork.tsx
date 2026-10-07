import { useEffect } from "react";
import { useApi } from "../lib/api";

/* What the Plex server is doing for itself.
 *
 * Scanning a library or analysing media reads every file it touches off the
 * same disks a stream is being read from, and until now nothing here could
 * say so: Plex lists what is running this second and keeps no history of it,
 * so a scan at three in the morning left no trace anywhere. "It buffered and
 * nothing was wrong" was an answer this app could give.
 *
 * Shown only when something is running. A line that says "the server is idle"
 * every few seconds is a line nobody reads, and this one is meant to be
 * noticed.
 */

type Job = {
  kind: string | null;
  title: string | null;
  subtitle: string | null;
  progress: number | null;
  section_id: number | null;
  started_at?: string | null;
  last_seen?: string | null;
  minutes?: number | null;
};

type Work = { now: Job[]; recent: Job[]; reason?: string };

export default function ServerWork() {
  const work = useApi<Work>("/server-work?hours=48");

  // Ten seconds, which is the poll that watches streams. Asking Plex costs
  // about six milliseconds and the answer is usually that nothing is running.
  // A job shorter than one round is missed here, and that is the right trade:
  // a scan of a small library finished in six seconds on the server this was
  // written against, and a job that brief is not what made anything buffer.
  // What ran at all is written down on the stream poll and listed under
  // Storage, so nothing is lost, only this one live line.
  useEffect(() => {
    const again = setInterval(work.reload, 10000);
    return () => clearInterval(again);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const running = work.data?.now ?? [];
  if (!running.length) return null;
  return (
    <p className="note server-work" role="status">
      {running.map((job, i) => (
        <span key={job.title ?? i} className="server-work-job">
          {i > 0 ? " · " : ""}
          <strong>{job.title || "Plex is busy"}</strong>
          {job.progress !== null && job.progress !== undefined ? ` ${job.progress}%` : ""}
          {job.subtitle ? <span className="muted">, on {job.subtitle}</span> : null}
        </span>
      ))}
      <span className="muted small">
        {" "}
        The server is reading its own files, which share the disks a stream comes off.
      </span>
    </p>
  );
}

/* The same thing, lately rather than now, for a page about what went wrong. */
export function ServerWorkLately({ hours = 48 }: { hours?: number }) {
  const work = useApi<Work>(`/server-work?hours=${hours}`, [hours]);
  if (work.error) return null;
  const rows = work.data?.recent ?? [];
  if (!rows.length) {
    return (
      <p className="muted small">
        The server has not run any work of its own in the last {hours} hours, as far as this app has seen. It is
        recorded on the same poll that watches streams, so nothing is known from before this was installed.
      </p>
    );
  }
  return (
    <div className="mini-list">
      {rows.map((job, i) => (
        <div key={(job.title ?? "") + i} className="mini">
          <div className="min0">
            <strong>{job.title || job.kind || "Something"}</strong>
            <p className="muted small">
              {[
                job.started_at ? new Date(job.started_at + "Z").toLocaleString() : null,
                job.minutes !== null && job.minutes !== undefined
                  ? job.minutes < 1
                    ? "under a minute"
                    : `${job.minutes} minutes`
                  : null,
                job.subtitle ? `last on ${job.subtitle}` : null,
              ]
                .filter(Boolean)
                .join(" · ")}
            </p>
          </div>
        </div>
      ))}
    </div>
  );
}
