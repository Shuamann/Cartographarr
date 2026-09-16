import { useEffect, useState } from "react";
import { api, useApi, type AuthState, type Capabilities, type SetupStatus } from "./lib/api";
import { CapabilityProvider } from "./components/Gated";
import ErrorBoundary from "./components/ErrorBoundary";
import Dashboard from "./routes/Dashboard";
import Login from "./routes/Login";
import Setup from "./routes/Setup";
import Map from "./routes/Map";
import Activity from "./routes/Activity";
import History from "./routes/History";
import Users from "./routes/Users";
import Devices from "./routes/Devices";
import Rules from "./routes/Rules";
import Settings from "./routes/Settings";
import type { Device, Rule } from "./lib/api";

const TABS = ["Dashboard", "Map", "Activity", "History", "Users", "Devices", "Rules", "Settings"] as const;
type Tab = (typeof TABS)[number];
const ADMIN_TABS: Tab[] = ["Rules", "Settings"];

export default function App() {
  const auth = useApi<AuthState>("/auth/state");
  const [tab, setTab] = useState<Tab>("Dashboard");
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

  return <SignedIn isAdmin={isAdmin} tab={tab} setTab={setTab} caps={caps} user={user} onSignOut={auth.reload} />;
}

function SignedIn({
  isAdmin,
  tab,
  setTab,
  caps,
  user,
  onSignOut,
}: {
  isAdmin: boolean;
  tab: Tab;
  setTab: (t: Tab) => void;
  caps: Capabilities | null;
  user: AuthState["user"];
  onSignOut: () => void;
}) {
  const setup = useApi<SetupStatus>("/setup", [isAdmin]);
  const [prefill, setPrefill] = useState<(Partial<Rule> & { name: string }) | undefined>();
  const [focusUser, setFocusUser] = useState<number | null>(null);

  function openUser(userId: number) {
    setFocusUser(userId);
    setTab("Users");
  }

  // Blocking a device from the inventory opens the rule editor already filled
  // in, so nobody has to copy a machine_id by hand.
  function blockDevice(device: Device) {
    setPrefill({
      name: `Block ${device.player || device.machine_id.slice(0, 8)}`,
      match_machine_id: device.machine_id,
      action: "terminate",
    });
    setTab("Rules");
  }

  if (setup.loading) return <Splash>Loading…</Splash>;

  // Only an admin can run setup. A viewer arriving at an unconfigured install
  // gets told who to ask rather than an error.
  if (setup.data && !setup.data.configured) {
    if (!isAdmin) {
      return <Splash>Cartographarr isn't set up yet. An admin needs to finish setup.</Splash>;
    }
    return <Setup status={setup.data} onDone={setup.reload} />;
  }

  const tabs = TABS.filter((t) => isAdmin || !ADMIN_TABS.includes(t));
  const active = tabs.includes(tab) ? tab : "Dashboard";

  return (
    <CapabilityProvider value={caps}>
      <div className="app">
        <header className="topbar">
          <div className="brand">Cartographarr</div>
          <nav>
            {tabs.map((t) => (
              <button key={t} className={t === active ? "tab active" : "tab"} onClick={() => setTab(t)}>
                {t}
              </button>
            ))}
          </nav>
          <ThemeToggle />
          <SignOut username={user?.username ?? ""} onSignOut={onSignOut} />
        </header>

        <main>
          <ErrorBoundary name={active} key={active}>
            {active === "Dashboard" && <Dashboard onNavigate={(t) => setTab(t as Tab)} />}
            {active === "Map" && (
              <Map geoipReady={setup.data?.geoip_ready ?? false} onOpenUser={openUser} />
            )}
            {active === "Activity" && <Activity />}
            {active === "History" && <History onOpenUser={openUser} />}
            {active === "Users" && <Users focusUserId={focusUser} key={focusUser ?? "users"} />}
            {active === "Devices" && <Devices me={user} onBlock={blockDevice} />}
            {active === "Rules" && <Rules prefill={prefill} key={prefill?.match_machine_id ?? "rules"} />}
            {active === "Settings" && <Settings isAdmin={isAdmin} />}
          </ErrorBoundary>
        </main>
      </div>
    </CapabilityProvider>
  );
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

function ThemeToggle() {
  const [theme, setTheme] = useState(document.documentElement.dataset.theme ?? "light");
  function flip() {
    const next = theme === "dark" ? "light" : "dark";
    document.documentElement.dataset.theme = next;
    localStorage.setItem("theme", next);
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
