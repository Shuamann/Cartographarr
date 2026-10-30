import BrandIcon from "../components/BrandIcon";
import Globe from "../components/Globe";
import Loading from "../components/Loading";
import { useApi, type Activity } from "../lib/api";
import { useNav } from "../lib/nav";
import { tabLabel, type Tab } from "../lib/tabs";
import SettingsLink, { SETTINGS_PAGES } from "../components/SettingsLink";
import TabIcon, { iconForTab } from "../components/TabIcon";

/* Home: where to go next.
 *
 * Whoever signs in lands here, so it answers the two things anyone opens the
 * app for. Where do I go (the app's own pages, Plex, the request service, and
 * for an admin the services behind it), and is anything waiting for me (what
 * is playing, and anything reported that is still open).
 *
 * It is laid out as a menu rather than a page of cards: the globe turning off
 * the left edge, a short list of destinations set against it, and the two
 * numbers worth knowing before you pick one. Everything takes its colour from
 * the theme, so the accent chosen in Settings is what the whole screen is
 * made of rather than a highlight on the selected line.
 */

type Link = { key: string; label: string; url: string; icon: string; roles: string; custom: boolean };

type Home = {
  app_name: string;
  username: string;
  role: string;
  links: Link[];
  open_issues: number;
};

/* The destinations, in the order somebody would work through them. An admin
 * opens the app to see what is happening; a viewer opens it for their own
 * history and their own reports, so they are offered the two pages they have. */
function destinations(isAdmin: boolean): { tab: Tab; note: string }[] {
  if (!isAdmin) {
    return [
      { tab: "History", note: "What you have watched" },
      { tab: "Issues", note: "Report something, or check yours" },
    ];
  }
  return [
    { tab: "Dashboard", note: "What is happening now" },
    { tab: "Map", note: "Where it is being watched from" },
    { tab: "People", note: "Who is watching, on what, and from where" },
    { tab: "Library", note: "Files worth attention" },
    { tab: "Issues", note: "What viewers have reported" },
    { tab: "Settings", note: "Services, rules of the house, this page" },
  ];
}

export default function HomeRoute({ onNavigate }: { onNavigate: (tab: Tab) => void }) {
  const nav = useNav();
  const home = useApi<Home>("/home");
  const live = useApi<Activity>("/activity", []);

  if (home.error) return <p className="note bad-note pad" role="alert">{home.error}</p>;
  if (!home.data) return <div className="pad"><Loading label="Setting up" /></div>;
  const d = home.data;
  const streams = live.data?.sessions?.length ?? 0;

  return (
    <div className="pad home">
      <Globe isAdmin={nav.isAdmin} />

      <div className="home-stage">
        <div className="home-menu">
          <p className="home-eyebrow">
            {d.app_name}
            <span>{d.username}</span>
          </p>

          <nav className="home-nav" aria-label="Where to go">
            {destinations(nav.isAdmin).map(({ tab, note }) => (
              <button key={tab} className="home-nav-item" onClick={() => onNavigate(tab)}>
                {/* The icon is its own column, so six entries line up down the
                    page instead of each one starting wherever its word does. */}
                <TabIcon name={iconForTab(tab)} />
                <span className="home-nav-words">
                  <span className="home-nav-label">{tabLabel(tab)}</span>
                  <span className="home-nav-note">{note}</span>
                </span>
                {tab === "Issues" && d.open_issues > 0 && <span className="home-nav-count">{d.open_issues}</span>}
              </button>
            ))}
          </nav>
        </div>

        <div className="home-side">
          <div className="home-readout">
            <button
              className="home-stat"
              onClick={() => onNavigate(nav.isAdmin ? "Dashboard" : "History")}
              title="Streams playing right now"
            >
              <span className="home-stat-value">{streams}</span>
              <span className="home-stat-label">{streams === 1 ? "stream playing" : "streams playing"}</span>
            </button>
            <button className="home-stat" onClick={() => onNavigate("Issues")} title="Reports still open">
              <span className="home-stat-value">{d.open_issues}</span>
              <span className="home-stat-label">
                {nav.isAdmin
                  ? d.open_issues === 1
                    ? "issue open"
                    : "issues open"
                  : d.open_issues === 1
                    ? "issue of yours open"
                    : "issues of yours open"}
              </span>
            </button>
          </div>

          <div className="home-launch">
            {d.links.length > 0 && (
              <div className="home-links">
                {d.links.map((link) => (
                  <a key={link.key} className="home-link" href={link.url} target="_blank" rel="noreferrer">
                    {link.icon && <BrandIcon name={link.icon} size={18} />}
                    <span>{link.label}</span>
                  </a>
                ))}
              </div>
            )}
            {d.links.length === 0 && (
              <p className="muted small home-hint">
                {nav.isAdmin
                  ? (
                      <>
                        Nothing to link to yet.{" "}
                        <SettingsLink page={SETTINGS_PAGES.plex}>
                          Set up Plex and the services you use in Settings
                        </SettingsLink>
                        , and they appear here.
                      </>
                    )
                  : "No links set up yet. Ask an admin."}
              </p>
            )}
            {nav.isAdmin && d.links.length > 0 && (
              <p className="muted small home-hint">
                Rename these or add your own under{" "}
                <SettingsLink page={SETTINGS_PAGES.home}>Settings, Home page</SettingsLink>.
              </p>
            )}
          </div>
        </div>
      </div>
    </div>
  );
}
