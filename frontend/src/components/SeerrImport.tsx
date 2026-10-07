import { useState } from "react";
import { api } from "../lib/api";

type Imported = {
  asked: boolean;
  reason?: string;
  read?: number;
  new?: number;
  already_here?: number;
  unmatched?: number;
  unmatched_titles?: string[];
  matched_by?: Record<string, number>;
  no_longer_in_seerr?: number;
};

const HOW: Record<string, string> = {
  rating_key: "by Plex's own key",
  tmdb: "by TMDB id",
  tvdb: "by TVDB id",
  imdb: "by IMDb id",
  title: "by the show's name",
};

function n(count: number | undefined, one: string, many = `${one}s`): string {
  return `${count ?? 0} ${count === 1 ? one : many}`;
}

/* Bring in every report Seerr holds, answered where it was asked.
 *
 * The same shape as the history check beside the source choice: one button,
 * and the answer in parts underneath it, because "12" says nothing about
 * whether those were new, already here, or could not be put against a file. */
export default function SeerrImport() {
  const [busy, setBusy] = useState(false);
  const [found, setFound] = useState<Imported | null>(null);
  const [failed, setFailed] = useState<string | null>(null);

  async function run() {
    setBusy(true);
    setFailed(null);
    try {
      setFound(await api.post<Imported>("/seerr/issues/import", {}));
    } catch (err) {
      setFailed((err as Error).message);
    } finally {
      setBusy(false);
    }
  }

  const how = Object.entries(found?.matched_by ?? {})
    .sort((a, b) => b[1] - a[1])
    .map(([key, count]) => `${count} ${HOW[key] ?? key}`)
    .join(", ");

  return (
    <div className="history-check">
      <div className="row">
        <button type="button" className="btn" onClick={run} disabled={busy}>
          {busy ? "Reading Seerr" : "Bring in Seerr's issues"}
        </button>
      </div>
      {failed && (
        <p className="note bad-note" role="alert">
          {failed}
        </p>
      )}
      {found && !found.asked && <p className="muted small">{found.reason}</p>}
      {found?.asked && (
        <>
          <p className="muted small">
            Read {n(found.read, "report")}: {found.new} new, {found.already_here} already here.
            {how ? ` Matched to a file ${how}.` : ""}
          </p>
          {Boolean(found.unmatched) && (
            <>
              <p className="small warn-text">
                {n(found.unmatched, "report")} could not be put against a file here, and{" "}
                {found.unmatched === 1 ? "is" : "are"} kept anyway under the name Seerr knows.
              </p>
              <ul className="muted small check-days">
                {found.unmatched_titles?.map((title, i) => (
                  <li key={`${title}-${i}`}>{title}</li>
                ))}
              </ul>
            </>
          )}
          {Boolean(found.no_longer_in_seerr) && (
            <p className="muted small">
              {n(found.no_longer_in_seerr, "report")} Seerr no longer lists {found.no_longer_in_seerr === 1 ? "is" : "are"}{" "}
              kept here.
            </p>
          )}
        </>
      )}
    </div>
  );
}
