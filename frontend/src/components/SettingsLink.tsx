import { useNav } from "../lib/nav";

/* A phrase that sends you to the right page of Settings.
 *
 * The app is full of sentences like "Connect Radarr in Settings" and "Add a
 * MaxMind key in Settings", which name a destination and then leave the
 * person to go and find it. This makes the phrase itself the way there.
 *
 * For a viewer, or anywhere Settings is not reachable, it renders as the
 * plain words it always was: an unclickable link to a page you cannot open is
 * worse than a sentence.
 */
export default function SettingsLink({ page, children }: { page?: string; children: React.ReactNode }) {
  const nav = useNav();
  if (!nav.openSettings) return <>{children}</>;
  return (
    <button type="button" className="linkish" onClick={() => nav.openSettings?.(page)}>
      {children}
    </button>
  );
}

/* The page ids, so call sites name a page rather than repeating a slug that
 * is generated from a title and would quietly stop matching if the title were
 * reworded. */
export const SETTINGS_PAGES = {
  plex: "plex-and-tautulli",
  map: "map-locations",
  mediaApps: "media-apps",
  alerts: "alerts-and-monitoring",
  syncing: "syncing",
  liveAndRules: "live-and-rules",
  library: "library-and-files",
  people: "people-and-privacy",
  signIn: "sign-in",
  appearance: "appearance",
  accounts: "accounts",
  home: "home",
  tasks: "tasks",
  about: "about",
} as const;
