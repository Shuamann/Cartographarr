import { Fragment, useState } from "react";
import FixMatch from "./FixMatch";
import Loading from "./Loading";
import TitleRow, { TitleRows } from "./TitleRow";
import { useApi } from "../lib/api";
import { useNav } from "../lib/nav";
import { size } from "../routes/Library";

/* What the library is missing, and what it is holding twice.
 *
 * Two questions a media server will not answer about itself, on one page
 * because the work they lead to is the same: go and look at a show, or go and
 * delete a file. Neither needed anything new to be recorded. The episode
 * numbers and the count of files behind each item were already in what the
 * scan writes down, and nobody had ever asked them a question.
 */

type GapSeason = {
  show_rating_key: number;
  season_rating_key: number | null;
  title: string | null;
  season: number;
  section_id: number | null;
  have: number;
  first: number;
  last: number;
  total: number;
  missing: number[];
  paired: number;
};

type Gaps = {
  seasons: GapSeason[];
  seasons_found: number;
  episodes_missing: number;
  shows: number;
  seasons_checked: number;
  double_episode_seasons: number;
  double_episode_holes: number;
};

type CopyFile = {
  path: string | null;
  size: number | null;
  container: string | null;
  bitrate: number | null;
  resolution: string | null;
  video_codec: string | null;
  audio_codec: string | null;
  audio_channels: number | null;
};

type CopyRow = {
  rating_key: number;
  title: string | null;
  full_title: string | null;
  show: string | null;
  season: number | null;
  episode: number | null;
  year: number | null;
  media_type: string | null;
  versions: number | null;
  files: CopyFile[] | null;
  extra_bytes: number | null;
  sizes_known: boolean;
};

type SameId = {
  matched_on: string;
  id: string;
  title: string | null;
  year: number | null;
  media_type: string | null;
  items: { rating_key: number; title: string | null; file_size: number | null; file_path: string | null }[];
};

type Copies = {
  multi: CopyRow[];
  multi_found: number;
  extra_files: number;
  extra_bytes: number | null;
  sizes_partial: number | null;
  same_id: SameId[];
};

/* "18 to 25, 30, 44 to 46" rather than sixty five numbers in a row. One show
   here is missing sixty five, and a list somebody has to count is a list
   nobody reads. */
export function runs(numbers: number[], most = 12): string {
  const out: string[] = [];
  let start = 0;
  for (let i = 0; i < numbers.length; i++) {
    if (i === numbers.length - 1 || numbers[i + 1] !== numbers[i] + 1) {
      out.push(start === i ? String(numbers[start]) : numbers[start] + " to " + numbers[i]);
      start = i + 1;
    }
  }
  if (out.length <= most) return out.join(", ");
  return out.slice(0, most).join(", ") + ", and " + (out.length - most) + " more";
}

export default function GapsSection() {
  const [tab, setTab] = useState<"missing" | "copies">("missing");
  const gaps = useApi<Gaps>("/library/gaps");
  const copies = useApi<Copies>("/library/copies");

  return (
    <>
      <p className="muted">
        Holes in a season, and files the library is paying for twice. Both come out of what the scan already wrote
        down, so neither waits on anything.
      </p>
      <div className="segmented" role="tablist" aria-label="What to look at">
        <button
          role="tab"
          aria-selected={tab === "missing"}
          className={tab === "missing" ? "seg on" : "seg"}
          onClick={() => setTab("missing")}
        >
          Missing episodes
          {gaps.data ? <span className="pill">{gaps.data.episodes_missing}</span> : null}
        </button>
        <button
          role="tab"
          aria-selected={tab === "copies"}
          className={tab === "copies" ? "seg on" : "seg"}
          onClick={() => setTab("copies")}
        >
          Here twice
          {copies.data ? <span className="pill">{copies.data.multi_found + copies.data.same_id.length}</span> : null}
        </button>
      </div>
      {tab === "missing" ? <MissingEpisodes data={gaps} /> : <HereTwice data={copies} />}
    </>
  );
}

function MissingEpisodes({ data }: { data: ReturnType<typeof useApi<Gaps>> }) {
  const nav = useNav();
  if (data.error)
    return (
      <p className="note bad-note" role="alert">
        {data.error}
      </p>
    );
  if (!data.data) return <Loading label="Counting episodes" />;
  const g = data.data;
  if (!g.seasons.length) {
    return (
      <p className="note">
        Nothing is missing out of the middle of a season, across {g.seasons_checked.toLocaleString()} seasons.
      </p>
    );
  }
  return (
    <>
      <p className="note">
        {g.episodes_missing.toLocaleString()} episodes missing from {g.seasons_found.toLocaleString()} seasons of{" "}
        {g.shows.toLocaleString()} shows. Only a gap between two episodes that are here counts, so a season still
        going out is never listed as missing the rest of itself.
        {g.double_episode_seasons > 0 && (
          <>
            {" "}
            A further {g.double_episode_seasons}{" "}
            {g.double_episode_seasons === 1 ? "season reads" : "seasons read"} as every second episode gone, which is
            how Plex files a double episode, so {g.double_episode_holes.toLocaleString()} apparent holes are left out.
          </>
        )}
      </p>
      <TitleRows>
        {g.seasons.map((s) => (
          <TitleRow
            key={s.show_rating_key + "-" + s.season}
            ratingKey={s.show_rating_key}
            item={{ media_type: "show", title: s.title, full_title: s.title }}
            note={
              <>
                Missing {runs(s.missing)}
                {/* Most of a season of double episodes reads as every second
                    file gone. Saying how many of the holes are that shape
                    beats either hiding the season or letting it claim forty
                    missing episodes. */}
                {s.paired > 2 && s.paired >= s.missing.length / 2 && (
                  <span className="muted">
                    {" · "}
                    {s.paired} of those sit between two episodes that are here, which is how a double episode is filed
                  </span>
                )}
              </>
            }
            facts={[
              { label: "Season", value: s.season },
              { label: "Here", value: s.have + " of " + s.total },
              { label: "Missing", value: s.missing.length },
              { label: "Numbered", value: s.first + " to " + s.last },
            ]}
            action={
              <button
                className="tab"
                onClick={(e) => {
                  e.stopPropagation();
                  nav.openLibrary?.({ show: s.show_rating_key, title: s.title, mediaType: "show" });
                }}
              >
                Open the show
              </button>
            }
          />
        ))}
      </TitleRows>
    </>
  );
}

function HereTwice({ data }: { data: ReturnType<typeof useApi<Copies>> }) {
  const [open, setOpen] = useState<number | null>(null);
  /* Which entry's match somebody is looking at. Separate from `open`, which
     is a row's files: these are two different lists and sharing one piece of
     state would close one by opening the other. */
  const [matching, setMatching] = useState<number | null>(null);
  if (data.error)
    return (
      <p className="note bad-note" role="alert">
        {data.error}
      </p>
    );
  if (!data.data) return <Loading label="Looking for second copies" />;
  const c = data.data;
  if (!c.multi.length && !c.same_id.length) {
    return <p className="note">Nothing in the library has a second file behind it.</p>;
  }
  return (
    <>
      <p className="note">
        {c.multi_found.toLocaleString()} {c.multi_found === 1 ? "title has" : "titles have"} more than one file, which
        is {c.extra_files.toLocaleString()} beyond the one being kept.{" "}
        {c.extra_bytes === null ? (
          <>Plex could not be asked how big they are, so the room they take is not known.</>
        ) : (
          <>Keeping the best copy of each would give back {size(c.extra_bytes)}.</>
        )}
        {c.sizes_partial ? (
          <>
            {" "}
            {c.sizes_partial} of them gave no size for at least one file, so that is a floor rather than the whole of
            it.
          </>
        ) : null}
      </p>
      <TitleRows>
        {c.multi.map((row) => (
          <Fragment key={row.rating_key}>
            <TitleRow
              ratingKey={row.rating_key}
              item={{
                media_type: row.media_type,
                title: row.title,
                full_title: row.full_title,
                grandparent_title: row.show,
                parent_media_index: row.season,
                media_index: row.episode,
                year: row.year,
              }}
              facts={[
                { label: "Files", value: row.versions },
                {
                  label: "Room to be had",
                  value: row.extra_bytes === null ? <span className="muted">not known</span> : size(row.extra_bytes),
                },
              ]}
              open={open === row.rating_key}
              onToggle={() => setOpen(open === row.rating_key ? null : row.rating_key)}
            />
            {open === row.rating_key && (
              <div className="mini-list">
                {(row.files ?? []).map((f, i) => (
                  <div key={(f.path ?? "") + i} className="mini">
                    <div className="min0">
                      <strong>
                        {[f.resolution, f.container, f.video_codec].filter(Boolean).join(" · ") || "A file"}
                      </strong>
                      <p className="muted small mono">{f.path || "Plex did not say where this one is"}</p>
                    </div>
                    <span className="muted small">{f.size ? size(f.size) : "size not given"}</span>
                  </div>
                ))}
                {!row.files?.length && <p className="muted small">Plex did not answer about this one.</p>}
              </div>
            )}
          </Fragment>
        ))}
      </TitleRows>
      {c.same_id.length > 0 && (
        <>
          <h3>Two entries for one title</h3>
          <p className="note">
            Separate items in one library sharing an external id, which is what a stray copy in the wrong folder, or a
            match made twice, looks like. Matched on the id rather than the name, because two films can share a name
            and two entries for one film cannot share an id by accident.
          </p>
          {/* Naming them was all this did. Where the cause is a match made
              twice, the remedy is to point one of the two at what it actually
              is, and that is Plex's own list of candidates. Per entry rather
              than per group: which of the two is the wrong one is the
              judgement nothing here can make. */}
          <div className="mini-list">
            {c.same_id.map((s) => (
              <div key={s.matched_on + "-" + s.id} className="mini">
                <div className="min0">
                  <strong>
                    {s.title} {s.year ? <span className="muted">{s.year}</span> : null}
                  </strong>
                  <p className="muted small">
                    {s.items.length} entries, matched on {s.matched_on.toUpperCase()} {s.id}
                  </p>
                  {s.items.map((i) => (
                    <Fragment key={i.rating_key}>
                      <div className="row wrap same-id-item">
                        <p className="muted small mono min0">
                          {i.file_path || "Item " + i.rating_key} {i.file_size ? "(" + size(i.file_size) + ")" : ""}
                        </p>
                        <button
                          className="linkish"
                          onClick={() => setMatching(matching === i.rating_key ? null : i.rating_key)}
                        >
                          {matching === i.rating_key ? "Hide the candidates" : "Fix this one's match"}
                        </button>
                      </div>
                      {matching === i.rating_key && (
                        <FixMatch
                          ratingKey={i.rating_key}
                          onClose={() => setMatching(null)}
                          onDone={() => data.reload()}
                        />
                      )}
                    </Fragment>
                  ))}
                </div>
              </div>
            ))}
          </div>
        </>
      )}
    </>
  );
}
