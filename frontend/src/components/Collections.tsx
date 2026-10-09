import { useApi } from "../lib/api";
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
 * so it is the size of question a library is usually thought about in. */
export default function CollectionsSection({ days }: { days: number }) {
  const found = useApi<Collection[]>(`/library/collections?days=${days}`);
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
          />
        ))}
      </TitleRows>
    </>
  );
}
