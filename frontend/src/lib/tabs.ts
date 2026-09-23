/* Every tab, in nav order. A typed list, so linking to a tab that does not
 * exist fails the build rather than quietly doing nothing, which is how the
 * dashboard kept pointing at Devices after it became People. */
export const TABS = [
  "Home",
  "Dashboard",
  "Map",
  "History",
  "People",
  "Reports",
  "Library",
  "Issues",
  "Rules",
  "Log",
  "Sharing",
  "Settings",
] as const;

export type Tab = (typeof TABS)[number];

export const ADMIN_TABS: Tab[] = ["Library", "Rules", "Log", "Sharing", "Settings"];

/* A People list filter another page can open it with. */
export type PeopleFilter = "new" | "banned" | "deleted" | "live";
