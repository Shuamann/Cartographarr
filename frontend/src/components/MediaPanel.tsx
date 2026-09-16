import { useApi, type MediaDetail } from "../lib/api";

const LINKS: { key: string; label: string }[] = [
  { key: "plex", label: "Plex" },
  { key: "imdb", label: "IMDb" },
  { key: "tmdb", label: "TMDB" },
  { key: "trakt", label: "Trakt" },
  { key: "radarr", label: "Radarr" },
  { key: "sonarr", label: "Sonarr" },
];

/* Everything known about one title, plus the ways out to other services.
 *
 * Only links the backend could actually build are rendered. A missing IMDb id
 * means no IMDb button, never a button that goes nowhere.
 */
export default function MediaPanel({
  ratingKey,
  onFilterToTitle,
}: {
  ratingKey: number;
  onFilterToTitle?: (ratingKey: number, title: string) => void;
}) {
  const media = useApi<MediaDetail>(`/media/${ratingKey}`);

  if (media.error) return <p className="muted small">{media.error}</p>;
  if (!media.data) return <p className="muted small">Loading…</p>;

  const m = media.data;
  const links = LINKS.filter((l) => m.links[l.key]);

  return (
    <div className="media">
      <img
        className="poster"
        src={`/api/media/${m.rating_key}/image`}
        alt=""
        // Not lazy: the panel lives inside a scrolling drawer, so the browser
        // decides the poster is offscreen and never loads it.
        onError={(e) => {
          // No artwork is normal for live TV and deleted items.
          (e.currentTarget as HTMLImageElement).style.display = "none";
        }}
      />

      <div className="media-body">
        <h3>{m.full_title || m.title}</h3>
        <p className="muted small">
          {[m.year, m.media_type, m.content_rating].filter(Boolean).join(" · ")}
        </p>

        <div className="row wrap linkrow">
          {links.map((l) => (
            <a key={l.key} className="ms-btn" href={m.links[l.key]} target="_blank" rel="noreferrer">
              {l.label}
            </a>
          ))}
          {onFilterToTitle && (
            <button
              className="ms-btn"
              onClick={() => onFilterToTitle(m.rating_key, m.full_title || m.title || "")}
            >
              Show on map
            </button>
          )}
        </div>
      </div>
    </div>
  );
}
