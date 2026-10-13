import { useState } from "react";
import { askConfirm } from "./Ask";
import Loading from "./Loading";
import { api, useApi } from "../lib/api";

/* Fixing a wrong Plex match, from the two places the app already names one.
 *
 * A file matched to the wrong entry carries the wrong external ids, so Radarr
 * or Sonarr has nothing under them and the file card says so; two items
 * matched to the same entry are the "Two entries for one title" list. Both
 * were dead ends: the remedy lives in Plex Web, and the app sent nobody there.
 *
 * Nothing here chooses. Twenty candidates come back and a fifth of them have no
 * year, so the one case this exists for, two filmed productions of one play in
 * one year, is the case a confident-looking sort would get wrong. The summary
 * is shown because it is what tells those two apart, and the choice is a
 * press on the one somebody read.
 */

type Candidate = {
  guid: string;
  name: string | null;
  year: number | null;
  media_type: string | null;
  summary: string | null;
  current: boolean;
};

type Candidates = {
  rating_key: number;
  media_type: string | null;
  title: string | null;
  year: number | null;
  asked_about: number;
  /* Set when what was asked about has no match of its own: an episode's ids
     come from its show, and so does its match. */
  instead_of: string | null;
  plex_title: string | null;
  plex_year: number | null;
  current_guid: string | null;
  agent: string | null;
  candidates: Candidate[];
};

type Applied = { name: string | null; year: number | null; ids_arrived: boolean; episodes_cleared: number };

function named(c: { name: string | null; year: number | null }): string {
  return c.year ? `${c.name} (${c.year})` : (c.name ?? "something unnamed");
}

export default function FixMatch({
  ratingKey,
  onClose,
  onDone,
}: {
  ratingKey: number;
  onClose: () => void;
  onDone?: () => void;
}) {
  const found = useApi<Candidates>(`/library/file/${ratingKey}/match`, [ratingKey]);
  const [busy, setBusy] = useState<string | null>(null);
  const [message, setMessage] = useState<{ text: string; ok: boolean } | null>(null);

  async function choose(candidate: Candidate) {
    const d = found.data;
    if (!d) return;
    const current = d.candidates.find((c) => c.current);
    /* The confirmation names both ends of it. "Change this match?" on its own
       is a question nobody can answer, and this writes to somebody's
       library. */
    const ok = await askConfirm({
      title: `Match this to ${named(candidate)}?`,
      body: (
        <>
          <p>
            {d.plex_title ?? d.title ?? `Item ${d.rating_key}`}
            {d.plex_year ? ` (${d.plex_year})` : ""} is matched to{" "}
            <strong>{current ? named(current) : "something Plex is no longer offering"}</strong> and would become{" "}
            <strong>{named(candidate)}</strong>.
          </p>
          <p>
            Plex re-reads the artwork, the summary and the external ids from the new match, and this app reads the
            item again so its own copy agrees.
            {d.instead_of === "episode"
              ? " This is the show's match, which is where an episode's ids come from, so it changes every episode under it."
              : ""}
          </p>
        </>
      ),
      confirm: "Change the match",
      danger: true,
    });
    if (!ok) return;
    setBusy(candidate.guid);
    setMessage(null);
    try {
      const done = await api.post<Applied>(`/library/file/${ratingKey}/match`, { guid: candidate.guid });
      setMessage({
        text:
          `Matched to ${named(done)}.` +
          (done.ids_arrived
            ? " Its ids are in."
            : " Plex had not fetched its ids yet, so they arrive with the next read.") +
          (done.episodes_cleared ? ` ${done.episodes_cleared} episodes will be read again.` : ""),
        ok: true,
      });
      found.reload();
      onDone?.();
    } catch (err) {
      setMessage({ text: (err as Error).message, ok: false });
    } finally {
      setBusy(null);
    }
  }

  const d = found.data;
  return (
    <section className="match-fix">
      <div className="row wrap track-group-head">
        <h4>What Plex thinks this is</h4>
        <button className="btn" onClick={onClose}>
          Done
        </button>
      </div>
      {found.error && (
        <p className="note bad-note" role="alert">
          {found.error}
        </p>
      )}
      {!d && !found.error && <Loading compact label="Asking Plex what else this could be" />}
      {d && (
        <>
          {d.instead_of === "episode" && (
            <p className="muted small">
              An episode has no match of its own, so this is {d.title ?? "the show"}, which is where its ids come
              from.
            </p>
          )}
          {d.candidates.length === 0 ? (
            /* Said plainly. An empty list drawn as a list is the one state
               where the app knows something and shows nothing. */
            <p className="note warn-note">
              Plex has nothing to offer for this one{d.agent ? `, searching with ${d.agent}` : ""}. Its agent found
              no candidates, so there is nothing to choose between here.
            </p>
          ) : (
            <>
              <p className="muted small">
                {d.candidates.length} {d.candidates.length === 1 ? "candidate" : "candidates"} from Plex
                {d.agent ? `, matched with ${d.agent}` : ""}. Nothing is picked for you: two filmed productions of
                one play in one year is exactly this list, and the one in use is marked.
              </p>
              <div className="mini-list">
                {d.candidates.map((c) => (
                  <div key={c.guid} className={c.current ? "mini match-row on" : "mini match-row"}>
                    <div className="min0">
                      <strong>
                        {c.name ?? "Unnamed"}{" "}
                        {/* Missing from about a fifth of them, and saying so beats
                            an empty space that reads as a year nobody noticed. */}
                        <span className="muted">{c.year ?? "year not given"}</span>
                        {c.current && <span className="pill"> in use now</span>}
                      </strong>
                      {c.summary && <p className="muted small clamp">{c.summary}</p>}
                    </div>
                    <button
                      className="btn"
                      disabled={c.current || busy !== null}
                      title={c.current ? "This is the match it has now" : undefined}
                      onClick={() => choose(c)}
                    >
                      {busy === c.guid ? "Matching" : c.current ? "In use" : "Use this one"}
                    </button>
                  </div>
                ))}
              </div>
            </>
          )}
          {message && <p className={message.ok ? "note ok-note" : "note bad-note"}>{message.text}</p>}
        </>
      )}
    </section>
  );
}
