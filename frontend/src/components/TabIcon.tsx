/* An icon for each of the app's own pages.
 *
 * Not BrandIcon: that carries other people's logos, filled, in their own
 * colours. These are this app's own pages, so they are drawn here rather than
 * taken from anywhere, as a stroked line at a single weight. Twenty four by
 * twenty four, a stroke of 1.75, round caps and joins, so six of them stacked
 * read as one set rather than six borrowed marks.
 *
 * Issues is the exception and is meant to be. It is a warning triangle in the
 * warning colour, because a reported problem is the one thing on this page
 * somebody needs to notice without reading, and the count beside it says
 * whether there is anything waiting.
 */

type Props = { name: string; size?: number };

/* Each entry is the shapes inside a 24x24 box. Drawn plainly: a page is a
   rectangle, a globe is a circle with a meridian, people are heads and
   shoulders. Nothing here is clever, and that is the point of a set. */
const SHAPES: Record<string, React.ReactNode> = {
  dashboard: (
    <>
      <rect x="3" y="3" width="7.5" height="8.5" rx="1.5" />
      <rect x="13.5" y="3" width="7.5" height="5" rx="1.5" />
      <rect x="13.5" y="11" width="7.5" height="10" rx="1.5" />
      <rect x="3" y="14.5" width="7.5" height="6.5" rx="1.5" />
    </>
  ),
  map: (
    <>
      <circle cx="12" cy="12" r="9" />
      <path d="M3 12h18" />
      <path d="M12 3a14 14 0 0 1 0 18a14 14 0 0 1 0-18Z" />
    </>
  ),
  people: (
    <>
      <circle cx="9" cy="8" r="3.2" />
      <path d="M3 20a6 6 0 0 1 12 0" />
      <path d="M16.5 5.5a3.2 3.2 0 0 1 0 6.2" />
      <path d="M18 14.6A6 6 0 0 1 21 20" />
    </>
  ),
  /* Three spines on a shelf. An angled third volume was tried and drew as a
     sliver at this size, which read as a smudge rather than a book. */
  library: (
    <>
      <rect x="3.5" y="4" width="4.5" height="16" rx="1.2" />
      <rect x="9.75" y="4" width="4.5" height="16" rx="1.2" />
      <rect x="16" y="4" width="4.5" height="16" rx="1.2" />
      <path d="M3.5 8.5h4.5M9.75 8.5h4.5M16 8.5h4.5" />
    </>
  ),
  history: (
    <>
      <circle cx="12" cy="12" r="9" />
      <path d="M12 7v5.2l3.4 2" />
    </>
  ),
  /* Sliders rather than a cog. A circle with eight rays around it is the mark
     every app uses for brightness, and at this size that is what it looked
     like; three rows with a knob on each reads as settings and nothing else. */
  settings: (
    <>
      <path d="M4 7h10M18 7h2M4 12h3M11 12h9M4 17h8M16 17h4" />
      <circle cx="16" cy="7" r="2" />
      <circle cx="9" cy="12" r="2" />
      <circle cx="14" cy="17" r="2" />
    </>
  ),
  /* The one that is not a line drawing of its page. A reported problem is the
     thing on this page somebody has to notice without reading it. */
  issues: (
    <>
      <path d="M12 3.8 2.6 20a1 1 0 0 0 .9 1.5h17a1 1 0 0 0 .9-1.5Z" />
      <path d="M12 9.6v4.8" />
      <path d="M12 17.6h.01" />
    </>
  ),
};

/* Which icon a page gets. Keyed on the tab rather than on its label, since
   Endpoints has been called two things and the icon should not care. */
const FOR_TAB: Record<string, string> = {
  Home: "dashboard",
  Dashboard: "dashboard",
  Map: "map",
  History: "history",
  Endpoints: "people",
  People: "people",
  Reports: "dashboard",
  Library: "library",
  Issues: "issues",
  Settings: "settings",
};

export function iconForTab(tab: string): string {
  return FOR_TAB[tab] ?? "dashboard";
}

export default function TabIcon({ name, size = 22 }: Props) {
  const shape = SHAPES[name];
  if (!shape) return null;
  const warning = name === "issues";
  return (
    <svg
      className={warning ? "tab-icon tab-icon-warn" : "tab-icon"}
      width={size}
      height={size}
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth="1.75"
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden="true"
    >
      {shape}
    </svg>
  );
}
