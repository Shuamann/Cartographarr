import { displayTitle, episodeLabel } from "../lib/titles";
import { useApi, type MediaDetail } from "../lib/api";
import BrandIcon from "./BrandIcon";

const LINKS: { key: string; label: string }[] = [
  { key: "plex", label: "Plex" },
  { key: "imdb", label: "IMDb" },
  { key: "tmdb", label: "TMDB" },
  { key: "trakt", label: "Trakt" },
  { key: "radarr", label: "Radarr" },
  { key: "sonarr", label: "Sonarr" },
  { key: "seerr", label: "Seerr" },
];

/* Everything known about one title, plus the ways out to other services.
 *
 * Only links the backend could actually build are rendered. A missing IMDb id
 * means no IMDb button, never a button that goes nowhere.
 */
export default function MediaPanel({
  ratingKey,
  onFilterToTitle,
  filterLabel = "Show on map",
}: {
  ratingKey: number;
  onFilterToTitle?: (ratingKey: number, title: string) => void;
  filterLabel?: string;
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
        <h3>{displayTitle(m)}</h3>
        {episodeLabel(m) && <p className="small">{episodeLabel(m)}</p>}
        <p className="muted small">
          {[m.year, m.media_type, m.content_rating].filter(Boolean).join(" · ")}
        </p>

        {m.request?.requested_by && (
          <p className="muted small">
            Requested by {m.request.requested_by}
            {m.request.requested_at
              ? ` on ${new Date(m.request.requested_at).toLocaleDateString()}`
              : ""}
          </p>
        )}

        <div className="row wrap linkrow">
          {links.map((l) => (
            <a key={l.key} className="ms-btn" href={m.links[l.key]} target="_blank" rel="noreferrer">
              <BrandIcon name={l.key} />
              {l.label}
            </a>
          ))}
          {onFilterToTitle && (
            <button
              className="ms-btn"
              onClick={() => onFilterToTitle(m.rating_key, m.full_title || m.title || "")}
            >
              {filterLabel}
            </button>
          )}
        </div>
      </div>
    </div>
  );
}
