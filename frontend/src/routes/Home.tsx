import BrandIcon from "../components/BrandIcon";
import Loading from "../components/Loading";
import { useApi, type Activity } from "../lib/api";
import { useNav } from "../lib/nav";
import type { Tab } from "../lib/tabs";

/* Home: where to go next.
 *
 * Whoever signs in lands here, so it answers the two things anyone opens the
 * app for. Where do I go (Plex, the request service, and for an admin the
 * services behind it), and is anything waiting for me (what is playing, and
 * anything reported that is still open).
 */

type Link = { key: string; label: string; url: string; icon: string; roles: string; custom: boolean };

type Home = {
  app_name: string;
  username: string;
  role: string;
  links: Link[];
  open_issues: number;
};

export default function HomeRoute({ onNavigate }: { onNavigate: (tab: Tab) => void }) {
  const nav = useNav();
  const home = useApi<Home>("/home");
  const live = useApi<Activity>("/activity", []);

  if (home.error) return <p className="note bad-note pad">{home.error}</p>;
  if (!home.data) return <div className="pad"><Loading label="Setting up" /></div>;
  const d = home.data;
  const streams = live.data?.sessions?.length ?? 0;

  return (
    <div className="pad home">
      <h1>
        {d.app_name}
        <span className="muted"> for {d.username}</span>
      </h1>

      <div className="home-cards">
        <button className="home-card" onClick={() => onNavigate(nav.isAdmin ? "Dashboard" : "History")}>
          <span className="card-big">{streams}</span>
          <span className="card-sub">{streams === 1 ? "stream playing" : "streams playing"}</span>
        </button>
        {nav.isAdmin && (
          <>
            <button className="home-card" onClick={() => onNavigate("Issues")}>
              <span className="card-big">{d.open_issues}</span>
              <span className="card-sub">{d.open_issues === 1 ? "issue open" : "issues open"}</span>
            </button>
            <button className="home-card accent" onClick={() => onNavigate("Issues")}>
              <span className="card-sub">Something wrong with a film or an episode?</span>
              <span className="card-big small-big">Raise an issue</span>
            </button>
          </>
        )}
      </div>

      <h2 className="section-head">Where to go</h2>
      {d.links.length === 0 ? (
        <p className="muted">
          {nav.isAdmin
            ? "Nothing to link to yet. Set up Plex and the services you use in Settings, and they appear here."
            : "No links set up yet. Ask an admin."}
        </p>
      ) : (
        <div className="home-links">
          {d.links.map((link) => (
            <a key={link.key} className="home-link" href={link.url} target="_blank" rel="noreferrer">
              {link.icon && <BrandIcon name={link.icon} size={20} />}
              <span>{link.label}</span>
            </a>
          ))}
        </div>
      )}
      {nav.isAdmin && (
        <p className="muted small">
          Rename these, choose who sees each one, or add your own under Settings, Home page.
        </p>
      )}
    </div>
  );
}
