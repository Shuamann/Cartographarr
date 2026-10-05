/* How a title reads everywhere: an episode carries its show and its season
 * and episode number, "Grey's Anatomy - S03E05 - Where the Boys Are", so two
 * plays of the same show can be told apart at a glance.
 *
 * Takes anything with the usual Tautulli title fields. Rows synced before the
 * numbers were kept, or live TV with none, fall back to the plain full title.
 */

export type Titled = {
  media_type?: string | null;
  full_title?: string | null;
  title?: string | null;
  grandparent_title?: string | null;
  parent_media_index?: number | string | null;
  media_index?: number | string | null;
};

function index(value: number | string | null | undefined): number | null {
  if (value === null || value === undefined || value === "") return null;
  const n = Number(value);
  return Number.isFinite(n) ? n : null;
}

const pad = (n: number) => String(n).padStart(2, "0");

/* S03E05, or null when this is not an episode with both numbers. */
export function episodeCode(x: Titled): string | null {
  if (x.media_type !== "episode") return null;
  const season = index(x.parent_media_index);
  const episode = index(x.media_index);
  if (season === null || episode === null) return null;
  return `S${pad(season)}E${pad(episode)}`;
}

/* "Season 3, Episode 5", for detail cards. */
export function episodeLabel(x: Titled): string | null {
  if (x.media_type !== "episode") return null;
  const season = index(x.parent_media_index);
  const episode = index(x.media_index);
  if (season === null || episode === null) return null;
  return season === 0 ? `Special, episode ${episode}` : `Season ${season}, Episode ${episode}`;
}

export function displayTitle(x: Titled): string {
  const code = episodeCode(x);
  const full = x.full_title || x.title || "";
  if (!code) return full;
  const show = x.grandparent_title || (full.includes(" - ") ? full.split(" - ")[0] : null);
  const episode = x.title || (full.includes(" - ") ? full.slice(full.indexOf(" - ") + 3) : full);
  return [show, code, episode].filter(Boolean).join(" - ");
}

/* The same title, split where it can be acted on: the show, the season and
 * episode code, and the episode's own name. Anything that is not an episode
 * comes back as one piece, which is what it is. */
export function titleParts(x: Titled): { show: string | null; code: string | null; episode: string } {
  const code = episodeCode(x);
  const full = x.full_title || x.title || "";
  if (!code) return { show: null, code: null, episode: full };
  const show = x.grandparent_title || (full.includes(" - ") ? full.split(" - ")[0] : null);
  const episode = x.title || (full.includes(" - ") ? full.slice(full.indexOf(" - ") + 3) : full);
  return { show, code, episode };
}
