/* Shared filter state.
 *
 * One shape, serialised once. The map, the stats strip and anything added
 * later all send the same query string, because the backend runs every
 * endpoint through a single predicate builder (app/filters.py).
 */

export type FilterState = {
  start: string;
  end: string;
  user_id: number[];
  media_type: string[];
  platform: string[];
  section_id: number[];
  transcode_decision: string[];
  is_hosting: boolean | null;
  search: string;
  rating_key: number | null;
  ratingKeyLabel: string | null;
  machine_id: string[];
  machineLabel: string | null;
};

export const EMPTY: FilterState = {
  start: "",
  end: "",
  user_id: [],
  media_type: [],
  platform: [],
  section_id: [],
  transcode_decision: [],
  is_hosting: null,
  search: "",
  rating_key: null,
  ratingKeyLabel: null,
  machine_id: [],
  machineLabel: null,
};

export function toQuery(f: FilterState): string {
  const p = new URLSearchParams();
  if (f.start) p.set("start", f.start);
  if (f.end) p.set("end", f.end);
  for (const v of f.user_id) p.append("user_id", String(v));
  for (const v of f.media_type) p.append("media_type", v);
  for (const v of f.platform) p.append("platform", v);
  for (const v of f.section_id) p.append("section_id", String(v));
  for (const v of f.transcode_decision) p.append("transcode_decision", v);
  if (f.is_hosting !== null) p.set("is_hosting", String(f.is_hosting));
  if (f.search.trim()) p.set("search", f.search.trim());
  if (f.rating_key !== null) p.set("rating_key", String(f.rating_key));
  for (const v of f.machine_id) p.append("machine_id", v);
  const q = p.toString();
  return q ? `?${q}` : "";
}

export function activeCount(f: FilterState): number {
  return (
    (f.start ? 1 : 0) +
    (f.end ? 1 : 0) +
    f.user_id.length +
    f.media_type.length +
    f.platform.length +
    f.section_id.length +
    f.transcode_decision.length +
    (f.is_hosting !== null ? 1 : 0) +
    (f.search.trim() ? 1 : 0) +
    (f.rating_key !== null ? 1 : 0) +
    f.machine_id.length
  );
}

/** Rebuild filter state from a query string, ignoring anything unrecognised. */
export function fromQuery(search: string): FilterState {
  const p = new URLSearchParams(search);
  const nums = (key: string) =>
    p.getAll(key).map(Number).filter((n) => Number.isFinite(n));
  const bool = (key: string) => (p.has(key) ? p.get(key) === "true" : null);

  return {
    start: p.get("start") ?? "",
    end: p.get("end") ?? "",
    user_id: nums("user_id"),
    media_type: p.getAll("media_type"),
    platform: p.getAll("platform"),
    section_id: nums("section_id"),
    transcode_decision: p.getAll("transcode_decision"),
    is_hosting: bool("is_hosting"),
    search: p.get("search") ?? "",
    rating_key: p.has("rating_key") ? Number(p.get("rating_key")) : null,
    // Not in the URL: it is a display label, and the title is refetched anyway.
    ratingKeyLabel: p.has("rating_key") ? "selected title" : null,
    machine_id: p.getAll("machine_id"),
    machineLabel: p.has("machine_id") ? "selected device" : null,
  };
}
