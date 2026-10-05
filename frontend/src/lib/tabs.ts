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

/* What a tab is called on screen, where that is not its name here.
 *
 * The People tab is about three things, not one: a person, a device and an
 * address are three ways of asking the same question. Its id stays People so
 * that every link, bookmark and stored tab keeps working; only the word
 * changes. App.tsx accepts the new word in a URL as well. */
export const TAB_LABELS: Partial<Record<Tab, string>> = {
  People: "Endpoints",
};

export function tabLabel(tab: Tab): string {
  return TAB_LABELS[tab] ?? tab;
}

export const ADMIN_TABS: Tab[] = ["Library", "Rules", "Log", "Sharing", "Settings"];

/* A People list filter another page can open it with. */
export type PeopleFilter = "new" | "banned" | "deleted" | "live";
