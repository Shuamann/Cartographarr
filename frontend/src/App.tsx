import BanDialog, { type BanRequest } from "./components/BanDialog";
import Loading from "./components/Loading";
import { lazy, Suspense, useEffect, useState } from "react";
import { api, useApi, type AuthState, type Capabilities, type SetupStatus } from "./lib/api";
import { CapabilityProvider } from "./components/Gated";
import { brandingUrl, useBranding } from "./lib/useBranding";
import { applyAccent, setScheme } from "./theme/accent";
import { useUrlFilters } from "./lib/useUrlFilters";
import ErrorBoundary from "./components/ErrorBoundary";
import Dashboard from "./routes/Dashboard";
import Login from "./routes/Login";
import Setup from "./routes/Setup";
// MapLibre is most of the bundle and the app opens on the dashboard, so the
// map arrives only when someone asks for it.
/* A tab left open across a deploy still holds the old module graph, and the
 * chunk it wants to fetch went out with the last build. Nothing to recover:
 * fetch the page again, once, and the new build answers. The flag makes it
 * once rather than a loop when the chunk is genuinely missing. */
function fresh<T>(load: () => Promise<T>): () => Promise<T> {
  return () =>
    load().catch((error) => {
      const stale = sessionStorage.getItem("reloaded-for-chunk");
      if (!stale) {
        sessionStorage.setItem("reloaded-for-chunk", "1");
        location.reload();
      }
      throw error;
    });
}

const Map = lazy(fresh(() => import("./routes/Map")));
const Reports = lazy(fresh(() => import("./routes/Reports")));
const Library = lazy(fresh(() => import("./routes/Library")));
const Home = lazy(fresh(() => import("./routes/Home")));
const Issues = lazy(fresh(() => import("./routes/Issues")));
import History from "./routes/History";
import People, { type Selection } from "./routes/People";
import Rules from "./routes/Rules";
import Log from "./routes/Log";
import Settings from "./routes/Settings";
import Sharing from "./routes/Sharing";
import type { LiveSession } from "./lib/api";
import { EMPTY, type FilterState } from "./lib/filters";
import { NavContext } from "./lib/nav";
import { unban } from "./lib/bans";

import { ADMIN_TABS, TABS, type PeopleFilter, type Tab } from "./lib/tabs";

export default function App() {
  const auth = useApi<AuthState>("/auth/state");
  const [tab, setTab] = useState<Tab>(() => {
    let wanted = new URLSearchParams(window.location.search).get("tab");
    // Users and Devices became one tab. Old bookmarks still land somewhere.
    if (wanted === "Users" || wanted === "Devices") wanted = "People";
    return (TABS as readonly string[]).includes(wanted ?? "") ? (wanted as Tab) : "Home";
  });

  // Kept in the address bar so a link opens where it was sent from. Filters do
  // the same from inside whichever route is showing.
  useEffect(() => {
    const params = new URLSearchParams(window.location.search);
    params.set("tab", tab);
    window.history.replaceState(null, "", `${window.location.pathname}?${params}`);
  }, [tab]);
  const [caps, setCaps] = useState<Capabilities | null>(null);

  const user = auth.data?.user ?? null;
  const isAdmin = user?.role === "admin";

  useEffect(() => {
    if (!user) return;
    api.get<Capabilities>("/capabilities").then(setCaps).catch(() => setCaps(null));
  }, [user?.id]);

  if (auth.loading) return <Splash>Starting…</Splash>;
  if (auth.error) return <Splash error>Can't reach the server: {auth.error}</Splash>;
  if (!auth.data) return <Splash error>No response from the server.</Splash>;

  // Sign in before anything else, so the setup wizard that accepts API keys is
  // never open to whoever reaches the URL first.
  if (!auth.data.authenticated) return <Login state={auth.data} onDone={auth.reload} />;

  return (
    <SignedIn
      isAdmin={isAdmin}
      tab={tab}
      setTab={setTab}
      caps={caps}
      user={user}
      privacy={auth.data.privacy}
      onSignOut={auth.reload}
    />
  );
}

function SignedIn({
  isAdmin,
  tab,
  setTab,
  caps,
  user,
  privacy,
  onSignOut,
}: {
  isAdmin: boolean;
  tab: Tab;
  setTab: (t: Tab) => void;
  caps: Capabilities | null;
  user: AuthState["user"];
  privacy: AuthState["privacy"];
  onSignOut: () => void;
}) {
  const setup = useApi<SetupStatus>("/setup", [isAdmin]);
  // Flags Settings when GitHub has something newer. Stored server side, so cheap to ask on each tab change.
  const updateStatus = useApi<{ status: string | null }>(isAdmin ? "/about/status" : null, [isAdmin, tab]);
  // Held here rather than inside each route, so the same filters apply
  // wherever you go rather than resetting on every tab change.
  const [filters, setFilters] = useUrlFilters();
  // Handed to the map so it can fly to one live stream and open its card.
  // Cleared once the map has used it, or going back to the tab later would
  // yank the view somewhere unexpected.
  const [focusSession, setFocusSession] = useState<LiveSession | null>(null);
  const [focusPlace, setFocusPlace] = useState<{ lat: number; lon: number } | null>(null);
  // Which user or device People opens on, when another page sent us there.
  const [focusPerson, setFocusPerson] = useState<Selection | null>(null);
  const [peopleFilter, setPeopleFilter] = useState<PeopleFilter | null>(null);

  function openPeople(filter?: PeopleFilter) {
    setPeopleFilter(filter ?? null);
    setTab("People");
  }

  function openUser(userId: number) {
    setFocusPerson({ kind: "user", id: userId });
    setTab("People");
  }

  function openDevice(machineId: string) {
    setFocusPerson({ kind: "device", id: machineId });
    setTab("People");
  }

  function openAddress(ip: string) {
    setFocusPerson({ kind: "address", id: ip });
    setTab("People");
  }

  // A profile's Map and History buttons: fresh filters narrowed to one
  // person or device, rather than added to whatever was set before.
  function filterTo(target: "Map" | "History", patch: Partial<FilterState>) {
    setFilters({ ...EMPTY, ...patch });
    setTab(target);
  }

  function showPlace(place: { lat: number; lon: number }, patch: Partial<FilterState> = {}) {
    setFilters({ ...EMPTY, ...patch });
    setFocusPlace(place);
    setTab("Map");
  }

  function showOnMap(session: LiveSession) {
    // Narrowed to whoever is streaming, since a single live session is not
    // something the history filters can express on their own.
    setFilters({ ...EMPTY, user_id: session.user_id != null ? [session.user_id] : [] });
    setFocusSession(session);
    setTab("Map");
  }

  // Banning adds the device to one managed list, which the enforcer treats as
  // a rule of its own. It used to open a new rule per device, which filled the
  // Rules page with one-device rules.
  // The Ban dialog, open while a request waits for its answer.
  const [banRequest, setBanRequest] = useState<BanRequest | null>(null);
  function banMachine(machineId: string, label: string): Promise<boolean> {
    return new Promise((resolve) => setBanRequest({ machineId, label, resolve }));
  }

  async function unbanMachine(machineId: string, label: string): Promise<boolean> {
    if (!window.confirm(`Unban ${label}? It will be able to stream again.`)) return false;
    try {
      await unban(machineId);
      return true;
    } catch (err) {
      window.alert((err as Error).message);
      return false;
    }
  }

  if (setup.loading) return <Splash><Loading /></Splash>;

  // Only an admin can run setup. A viewer arriving at an unconfigured install
  // gets told who to ask rather than an error.
  if (setup.data && !setup.data.configured) {
    if (!isAdmin) {
      return <Splash>Cartographarr isn't set up yet. An admin needs to finish setup.</Splash>;
    }
    return <Setup status={setup.data} onDone={setup.reload} />;
  }

  const tabs = TABS.filter((t) => isAdmin || !ADMIN_TABS.includes(t));
  const updateAvailable = updateStatus.data?.status === "update_available";
  const active = tabs.includes(tab) ? tab : "Dashboard";

  return (
    <CapabilityProvider value={caps}>
      <NavContext.Provider
        value={{
          isAdmin,
          openUser,
          openDevice,
          openAddress,
          showOnMap,
          showPlace,
          blockDevice: isAdmin ? banMachine : undefined,
          unbanDevice: isAdmin ? unbanMachine : undefined,
          filterTo,
          openPeople,
          goTo: setTab,
        }}
      >
      <div className="app">
        <BanDialog request={banRequest} onClose={() => setBanRequest(null)} />
        <header className="topbar">
          <Brand />
          <nav>
            {tabs.map((t) => (
              <button
                key={t}
                className={t === active ? "tab active" : "tab"}
                aria-current={t === active ? "page" : undefined}
                // On a phone the tabs scroll sideways; keep the current one in view.
                ref={t === active ? (el) => el?.scrollIntoView({ block: "nearest", inline: "nearest" }) : undefined}
                onClick={() => setTab(t)}
              >
                {t}
                {t === "Settings" && updateAvailable && <span className="update-dot" title="Update available" />}
              </button>
            ))}
          </nav>
          <ThemeToggle />
          <SignOut username={user?.username ?? ""} onSignOut={onSignOut} />
        </header>

        {privacy && privacy.mode !== "all" && !isAdmin && (
          <div className={privacy.linked ? "privacy-bar" : "privacy-bar warn"}>
            {!privacy.linked
              ? "Your account is not linked to a Plex user, so there is nothing of yours to show. Ask an admin to link it under Settings, Accounts."
              : privacy.mode === "own"
                ? "You are seeing only your own plays, devices and streams."
                : "Other people are anonymised. Totals and the map cover the whole server."}
          </div>
        )}
        <main>
          <ErrorBoundary name={active} key={active}>
            <Suspense fallback={<div className="pad"><Loading /></div>}>
            {active === "Dashboard" && (
              <Dashboard
                onNavigate={setTab}
                isAdmin={isAdmin}
                onOpenUser={openUser}
                filters={filters}
                onFilters={setFilters}
              />
            )}
            {active === "Map" && (
              <Map
                geoipReady={setup.data?.geoip_ready ?? false}
                onOpenUser={openUser}
                focusSession={focusSession}
                onFocusUsed={() => setFocusSession(null)}
                focusPlace={focusPlace}
                onFocusPlaceUsed={() => setFocusPlace(null)}
                filters={filters}
                onFilters={setFilters}
              />
            )}
            {active === "History" && (
              <History onOpenUser={openUser} filters={filters} onFilters={setFilters} />
            )}
            {active === "People" && (
              <People
                initial={focusPerson}
                onInitialUsed={() => setFocusPerson(null)}
                initialFilter={peopleFilter}
                onInitialFilterUsed={() => setPeopleFilter(null)}
              />
            )}
            {active === "Reports" && <Reports />}
            {active === "Home" && <Home onNavigate={setTab} />}
            {active === "Library" && <Library />}
            {active === "Issues" && <Issues />}
            {active === "Rules" && <Rules />}
            {active === "Log" && <Log onOpenUser={openUser} />}
            {active === "Sharing" && <Sharing />}
            {active === "Settings" && <Settings isAdmin={isAdmin} />}
            </Suspense>
          </ErrorBoundary>
        </main>
      </div>
      </NavContext.Provider>
    </CapabilityProvider>
  );
}

function Brand() {
  const branding = useBranding();
  const name = branding.data?.app_name ?? "Cartographarr";

  useEffect(() => {
    sessionStorage.removeItem("reloaded-for-chunk");
  }, []);

  useEffect(() => {
    if (!branding.data) return;
    // Kept where the rest of the branding is applied, and remembered so a
    // reload paints in the right colour before the first request answers.
    setScheme(branding.data.theme);
    applyAccent(branding.data.accent);
    try {
      if (branding.data.accent) localStorage.setItem("accent", branding.data.accent);
      else localStorage.removeItem("accent");
      if (branding.data.theme) localStorage.setItem("theme.colours", branding.data.theme);
      else localStorage.removeItem("theme.colours");
    } catch {
      /* remembering the colour is a convenience only */
    }
    document.title = name;
    if (branding.data.images.icon) {
      // Replaced rather than added, so repeated renders do not stack links.
      const link =
        document.querySelector<HTMLLinkElement>("link[rel='icon']") ??
        document.head.appendChild(Object.assign(document.createElement("link"), { rel: "icon" }));
      link.href = brandingUrl("icon");
    }
  }, [branding.data, name]);

  if (branding.data?.images.logo) {
    return <img className="brand-mark" src={brandingUrl("logo")} alt={name} />;
  }
  return <div className="brand">{name}</div>;
}

function SignOut({ username, onSignOut }: { username: string; onSignOut: () => void }) {
  async function go() {
    await api.post("/auth/logout").catch(() => {});
    onSignOut();
  }
  return (
    <button className="tab" onClick={go} title={`Signed in as ${username}`}>
      Sign out
    </button>
  );
}

function accentNow(): string | null {
  try {
    return localStorage.getItem("accent");
  } catch {
    return null;
  }
}

function ThemeToggle() {
  const [theme, setTheme] = useState(document.documentElement.dataset.theme ?? "light");
  function flip() {
    const next = theme === "dark" ? "light" : "dark";
    document.documentElement.dataset.theme = next;
    localStorage.setItem("theme", next);
    // The accent's hover and wash are worked out against the page behind them,
    // so they are worked out again when that page changes colour.
    applyAccent(accentNow());
    setTheme(next);
  }
  return (
    <button className="tab" onClick={flip} title="Switch theme">
      {theme === "dark" ? "Light" : "Dark"}
    </button>
  );
}

function Splash({ children, error }: { children: React.ReactNode; error?: boolean }) {
  return (
    <div className="splash">
      <div className={error ? "note bad-note" : "muted"}>{children}</div>
    </div>
  );
}
