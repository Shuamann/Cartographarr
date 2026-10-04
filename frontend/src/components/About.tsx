import { useState } from "react";
import { api, useApi } from "../lib/api";
import Loading from "./Loading";

/* Settings, About: this version, whether GitHub has a newer one, what it
 * brings, and the changelog. */

type Entry = { version: string; date: string | null; sections: { title: string; items: string[] }[] };

type Commit = { sha: string; message: string; date: string | null; url: string | null };

type UpdateState = {
  checked_at: string;
  status: "up_to_date" | "update_available" | "error";
  message: string | null;
  compared_by?: "commit" | "version";
  latest_version?: string | null;
  latest_commit?: string | null;
  latest_date?: string | null;
  commits_behind?: number | null;
  commits?: Commit[];
  newer?: Entry[];
  repository_url?: string;
};

export type AboutInfo = {
  version: string;
  commit: string | null;
  changelog: Entry[];
  check_enabled: boolean;
  repository: string;
  update: UpdateState | null;
};

function toTime(iso: string | null | undefined): number | null {
  if (!iso) return null;
  return new Date(/[zZ]|[+-]\d\d:\d\d$/.test(iso) ? iso : `${iso}Z`).getTime();
}

function ago(iso: string | null | undefined): string {
  const t = toTime(iso);
  if (t === null) return "never";
  const s = Math.max(0, Math.round((Date.now() - t) / 1000));
  if (s < 60) return "just now";
  if (s < 3600) return `${Math.round(s / 60)} min ago`;
  if (s < 86400) return `${Math.round(s / 3600)} h ago`;
  return `${Math.round(s / 86400)} d ago`;
}

function day(iso: string | null | undefined): string {
  const t = toTime(iso);
  return t === null ? "" : new Date(t).toLocaleDateString(undefined, { year: "numeric", month: "short", day: "numeric" });
}

function Badge({ info }: { info: AboutInfo }) {
  const u = info.update;
  if (!info.check_enabled && !u) return <span className="pill">Checks off</span>;
  if (!u) return <span className="pill">Not checked yet</span>;
  if (u.status === "update_available") return <span className="pill warn">Update available</span>;
  if (u.status === "up_to_date") return <span className="pill ok">Up to date</span>;
  return <span className="pill bad">Couldn't check</span>;
}

export default function About() {
  const about = useApi<AboutInfo>("/about");
  const [checking, setChecking] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [older, setOlder] = useState(false);

  async function checkNow() {
    setChecking(true);
    setError(null);
    try {
      await api.post("/about/check");
      about.reload();
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setChecking(false);
    }
  }

  if (about.error) return <p className="note bad-note" role="alert">{about.error}</p>;
  if (!about.data) return <Loading label="Reading version" />;
  const info = about.data;
  const u = info.update;
  const repo = u?.repository_url ?? `https://github.com/${info.repository}`;
  const shown = older ? info.changelog : info.changelog.slice(0, 2);

  return (
    <>
      <section className="card-section">
        <div className="row-between">
          <div>
            <div className="about-version">
              Cartographarr {info.version} <Badge info={info} />
            </div>
            <div className="muted small">
              {info.commit ? (
                <>
                  Built from{" "}
                  <a href={`${repo}/commit/${info.commit}`} target="_blank" rel="noreferrer">
                    <code>{info.commit.slice(0, 7)}</code>
                  </a>
                </>
              ) : (
                "Build commit unknown, so updates are judged by version number"
              )}
            </div>
          </div>
          <button className="btn" onClick={checkNow} disabled={checking}>
            {checking ? "Checking" : "Check now"}
          </button>
        </div>

        {error && <p className="note bad-note" role="alert">{error}</p>}
        {u?.status === "error" && <p className="note bad-note" role="alert">{u.message}</p>}

        {u && (
          <dl className="about-facts">
            <div>
              <dt>Latest on GitHub</dt>
              <dd>
                {u.latest_version ?? "No version"}
                {u.latest_commit && (
                  <>
                    {" \u00b7 "}
                    <a href={`${repo}/commit/${u.latest_commit}`} target="_blank" rel="noreferrer">
                      <code>{u.latest_commit.slice(0, 7)}</code>
                    </a>
                  </>
                )}
                {u.latest_date && <span className="muted small"> {day(u.latest_date)}</span>}
              </dd>
            </div>
            {u.commits_behind != null && (
              <div>
                <dt>Commits behind</dt>
                <dd>{u.commits_behind.toLocaleString()}</dd>
              </div>
            )}
            <div>
              <dt>Last checked</dt>
              <dd>{ago(u.checked_at)}</dd>
            </div>
          </dl>
        )}

        {!info.commit && (
          <p className="muted small">
            To compare by commit, build with <code>--build-arg GIT_COMMIT=$(git rev-parse HEAD)</code>.
          </p>
        )}
      </section>

      {u?.status === "update_available" && (
        <section className="card-section">
          <h3>What the update brings</h3>
          {(u.newer ?? []).map((entry) => (
            <ChangelogEntry key={entry.version} entry={entry} />
          ))}
          {(u.commits ?? []).length > 0 && (
            <>
              <h4 className="about-sub">Commits since this build</h4>
              <ul className="about-commits">
                {u.commits!.map((c) => (
                  <li key={c.sha}>
                    <a href={c.url ?? `${repo}/commit/${c.sha}`} target="_blank" rel="noreferrer">
                      <code>{c.sha.slice(0, 7)}</code>
                    </a>{" "}
                    {c.message}
                    {c.date && <span className="muted small"> {day(c.date)}</span>}
                  </li>
                ))}
              </ul>
              {(u.commits_behind ?? 0) > u.commits!.length && (
                <p className="muted small">
                  And {(u.commits_behind! - u.commits!.length).toLocaleString()} older.{" "}
                  <a href={`${repo}/commits`} target="_blank" rel="noreferrer">
                    All commits
                  </a>
                </p>
              )}
            </>
          )}
          <p className="muted small">
            Update the way it was installed: pull and rebuild the image, or pull the new image. The{" "}
            <a href={`${repo}#install`} target="_blank" rel="noreferrer">
              install guide
            </a>{" "}
            has the commands.
          </p>
        </section>
      )}

      <section className="card-section">
        <h3>Changelog</h3>
        {info.changelog.length === 0 && <p className="muted">No changelog in this build.</p>}
        {shown.map((entry) => (
          <ChangelogEntry key={entry.version} entry={entry} current={entry.version === info.version} />
        ))}
        {info.changelog.length > 2 && (
          <button className="btn" onClick={() => setOlder(!older)}>
            {older ? "Show fewer" : `Show ${info.changelog.length - 2} older`}
          </button>
        )}
      </section>
    </>
  );
}

function ChangelogEntry({ entry, current }: { entry: Entry; current?: boolean }) {
  return (
    <article className="about-entry">
      <h4>
        {entry.version}
        {entry.date && <span className="muted small"> {entry.date}</span>}
        {current && <span className="pill ok">Installed</span>}
      </h4>
      {entry.sections.map((s) => (
        <div key={s.title}>
          <h5>{s.title}</h5>
          <ul>
            {s.items.map((item, i) => (
              <li key={i}>{item}</li>
            ))}
          </ul>
        </div>
      ))}
    </article>
  );
}
