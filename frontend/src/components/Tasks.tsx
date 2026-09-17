import { Fragment, useEffect, useState } from "react";
import { api, useApi } from "../lib/api";
import Loading from "./Loading";

/* Scheduled background tasks: how often each runs, how the last run went,
 * when the next is, and each task's recent runs with any error. */

type TaskInfo = {
  key: string;
  name: string;
  description: string;
  every_seconds: number;
  next_run: string | null;
  running: boolean;
  runs: number;
  failures: number;
  last: { started_at: string; duration_ms: number; status: string; message: string | null; trigger: string } | null;
  stores_every_run: boolean;
};

type Run = { id: number; started_at: string | null; duration_ms: number | null; status: string; message: string | null; trigger: string | null };

function toTime(iso: string | null | undefined): number | null {
  if (!iso) return null;
  return new Date(/[zZ]|[+-]\d\d:\d\d$/.test(iso) ? iso : `${iso}Z`).getTime();
}

function every(seconds: number): string {
  if (seconds < 60) return `${seconds} seconds`;
  if (seconds < 3600) return `${Math.round(seconds / 60)} minute${seconds >= 120 ? "s" : ""}`;
  const hours = seconds / 3600;
  return `${hours % 1 ? hours.toFixed(1) : hours} hour${hours === 1 ? "" : "s"}`;
}

function relative(iso: string | null | undefined, now: number): string {
  const t = toTime(iso);
  if (t === null) return "never";
  const s = Math.round((t - now) / 1000);
  const abs = Math.abs(s);
  const text = abs < 60 ? `${abs}s` : abs < 3600 ? `${Math.round(abs / 60)} min` : abs < 86400 ? `${Math.round(abs / 3600)} h` : `${Math.round(abs / 86400)} d`;
  return s >= 0 ? `in ${text}` : `${text} ago`;
}

function duration(ms: number | null | undefined): string {
  if (ms == null) return "";
  return ms < 1000 ? `${ms} ms` : `${(ms / 1000).toFixed(1)} s`;
}

const TONE: Record<string, string> = { ok: "pill ok", failed: "pill bad", skipped: "pill" };

export default function Tasks() {
  const tasks = useApi<TaskInfo[]>("/tasks");
  const [open, setOpen] = useState<string | null>(null);
  const [now, setNow] = useState(Date.now());
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    const timer = setInterval(() => {
      tasks.reload();
      setNow(Date.now());
    }, 5000);
    return () => clearInterval(timer);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  async function runNow(task: TaskInfo) {
    setError(null);
    try {
      await api.post(`/tasks/${task.key}/run`);
      setTimeout(tasks.reload, 500);
    } catch (err) {
      setError((err as Error).message);
    }
  }

  if (tasks.error) return <p className="note bad-note">{tasks.error}</p>;
  if (!tasks.data) return <Loading label="Reading background tasks" />;

  return (
    <section className="card-section">
      {error && <p className="note bad-note">{error}</p>}
      <table className="table tasks">
        <thead>
          <tr>
            <th>Task</th>
            <th>Every</th>
            <th>Last run</th>
            <th>Next run</th>
            <th className="num">Since start</th>
            <th />
          </tr>
        </thead>
        <tbody>
          {tasks.data.map((t) => (
            <Fragment key={t.key}>
              <tr className="task-row" onClick={() => setOpen(open === t.key ? null : t.key)} aria-expanded={open === t.key}>
                <td>
                  <strong>{t.name}</strong>
                  <div className="muted small">{t.description}</div>
                </td>
                <td>{every(t.every_seconds)}</td>
                <td>
                  {t.running ? (
                    <span className="pill warn">running</span>
                  ) : t.last ? (
                    <>
                      <span className={TONE[t.last.status] ?? "pill"}>{t.last.status}</span>{" "}
                      <span className="small">{relative(t.last.started_at, now)}</span>
                      <div className="muted small">
                        {duration(t.last.duration_ms)}
                        {t.last.status !== "failed" && t.last.message ? ` \u00b7 ${t.last.message}` : ""}
                      </div>
                    </>
                  ) : (
                    <span className="muted small">not since start</span>
                  )}
                </td>
                <td className="small">{relative(t.next_run, now)}</td>
                <td className="num small">
                  {t.runs.toLocaleString()} runs
                  {t.failures > 0 && <div className="danger-text">{t.failures} failed</div>}
                </td>
                <td>
                  <button
                    className="btn"
                    disabled={t.running}
                    onClick={(e) => {
                      e.stopPropagation();
                      runNow(t);
                    }}
                  >
                    Run now
                  </button>
                </td>
              </tr>
              {open === t.key && (
                <tr>
                  <td colSpan={6}>
                    <TaskRuns task={t} />
                  </td>
                </tr>
              )}
            </Fragment>
          ))}
        </tbody>
      </table>
    </section>
  );
}

function TaskRuns({ task }: { task: TaskInfo }) {
  const runs = useApi<Run[]>(`/tasks/${task.key}/runs`, [task.last?.started_at]);
  if (runs.error) return <p className="note bad-note">{runs.error}</p>;
  if (!runs.data) return <Loading compact label="Reading runs" />;
  return (
    <div className="task-runs">
      {!task.stores_every_run && (
        <p className="muted small">This one runs every few seconds, so only failures and runs started by hand are kept.</p>
      )}
      {runs.data.length === 0 && <p className="muted small">No runs recorded yet.</p>}
      {runs.data.map((r) => (
        <div key={r.id} className="task-run">
          <div className="row">
            <span className={TONE[r.status] ?? "pill"}>{r.status}</span>
            <span className="small">{r.started_at ? new Date(toTime(r.started_at) as number).toLocaleString() : ""}</span>
            <span className="muted small">
              {duration(r.duration_ms)}
              {r.trigger && r.trigger !== "schedule" ? ` \u00b7 ${r.trigger}` : ""}
            </span>
          </div>
          {r.message &&
            (r.status === "failed" ? <pre className="task-error">{r.message}</pre> : <p className="muted small">{r.message}</p>)}
        </div>
      ))}
    </div>
  );
}
