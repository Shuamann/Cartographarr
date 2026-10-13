import { useState } from "react";
import { askConfirm, tell } from "./Ask";
import { api, queueChanged, useApi } from "../lib/api";
import { useNav } from "../lib/nav";
import Loading from "./Loading";
import TitleRow, { TitleRows } from "./TitleRow";

type Collection = {
  name: string;
  titles: number;
  files: number;
  bytes: number;
  problems: number;
  watched: number;
  last_play: number | null;
  poster_key: number | null;
};

type TidyAnswer = {
  queued: number;
  skipped: number;
  /* Negative is smaller, the same sign one file uses. */
  size_change: number;
  size_unknown: number;
};

function size(bytes: number): string {
  if (bytes >= 1e12) return `${(bytes / 1e12).toFixed(1)} TB`;
  if (bytes >= 1e9) return `${(bytes / 1e9).toFixed(1)} GB`;
  return `${Math.max(1, Math.round(bytes / 1e6))} MB`;
}

function ago(epoch: number | null): string {
  if (!epoch) return "Never";
  const days = Math.floor((Date.now() / 1000 - epoch) / 86400);
  if (days < 1) return "Today";
  if (days === 1) return "Yesterday";
  if (days < 60) return `${days} days ago`;
  return `${Math.round(days / 30)} months ago`;
}

/* Each collection's size, what is wrong in it and how much of it is watched.
 * A collection is where somebody already wrote down what belongs together,
 * so it is the size of question a library is usually thought about in, and
 * since 0.118.0 the size of thing that can be tidied in one go. */
export default function CollectionsSection({ days }: { days: number }) {
  const found = useApi<Collection[]>(`/library/collections?days=${days}`);
  const nav = useNav();
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState<string | null>(null);

  /* Tidying a whole collection.
   *
   * Asked for first as a dry run, so the question is answered with what
   * would actually happen to which files rather than with a number, and each
   * file is queued as its own job with its own steps. A collection over the
   * cap is refused by the server rather than quietly becoming its first two
   * hundred titles, and that refusal is what gets shown. */
  async function tidy(name: string) {
    setError(null);
    setBusy(name);
    try {
      const preview = await api.post<TidyAnswer>("/library/tidy/many", { collection: name, dry_run: true });
      if (!preview.queued) {
        void tell("Nothing to do", `Nothing in ${name} has anything worth changing.`);
        return;
      }
      if (
        !(await askConfirm({
          title: `Tidy ${preview.queued} ${preview.queued === 1 ? "file" : "files"} in ${name}?`,
          body: (
            <>
              <p>
                Each one is read and written once, with the steps worked out from that file rather than the same
                thing done to all of them. The picture is never re-encoded, and the original is replaced only
                after the result is checked.
              </p>
              <p>
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
      const done = await api.post<TidyAnswer>("/library/tidy/many", { collection: name });
      queueChanged();
      void tell("Queued", `${done.queued} queued. The Remediation queue shows how far along it is.`);
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setBusy(null);
    }
  }

  if (found.error) return <p className="note bad-note" role="alert">{found.error}</p>;
  if (!found.data) return <Loading label="Adding up collections" />;
  if (found.data.length === 0)
    return <p className="muted">No collections yet. They are read from Plex by the library scan.</p>;
  return (
    <>
      <p className="muted">
        Largest first. Problems are files that caused trouble in the period chosen above. Watched counts titles anybody
        played in the last year, and a show half watched counts as watched.
      </p>
      {error && <p className="note bad-note" role="alert">{error}</p>}
      <TitleRows>
        {found.data.map((c) => (
          <TitleRow
            key={c.name}
            ratingKey={c.poster_key}
            item={{ title: c.name, full_title: c.name, media_type: "collection" }}
            note={c.files !== c.titles ? `${c.titles.toLocaleString()} titles, ${c.files.toLocaleString()} files` : `${c.titles.toLocaleString()} titles`}
            facts={[
              { label: "Size", value: size(c.bytes) },
              { label: "Watched", value: `${c.watched} of ${c.titles}` },
              {
                label: "Problems",
                value: c.problems ? <span className="warn-text">{c.problems}</span> : "None",
              },
              { label: "Last", value: ago(c.last_play) },
            ]}
            action={
              nav.isAdmin && c.files > 0 ? (
                <button
                  className="tab"
                  disabled={busy !== null}
                  onClick={(e) => {
                    e.stopPropagation();
                    void tidy(c.name);
                  }}
                >
                  {busy === c.name ? "Working out…" : "Tidy all"}
                </button>
              ) : null
            }
          />
        ))}
      </TitleRows>
    </>
  );
}
