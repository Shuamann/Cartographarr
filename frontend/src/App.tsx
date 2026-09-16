import { useEffect, useState } from "react";
import { api, useApi, type Capabilities, type SetupStatus } from "./lib/api";
import { CapabilityProvider } from "./components/Gated";
import ErrorBoundary from "./components/ErrorBoundary";
import Dashboard from "./routes/Dashboard";
import Setup from "./routes/Setup";
import Map from "./routes/Map";
import Activity from "./routes/Activity";
import Rules from "./routes/Rules";

const TABS = ["Dashboard", "Map", "Activity", "Rules", "Settings"] as const;
type Tab = (typeof TABS)[number];

export default function App() {
  const setup = useApi<SetupStatus>("/setup");
  const [tab, setTab] = useState<Tab>("Dashboard");
  const [caps, setCaps] = useState<Capabilities | null>(null);

  const configured = setup.data?.configured ?? false;

  useEffect(() => {
    if (!configured) return;
    api.get<Capabilities>("/capabilities").then(setCaps).catch(() => setCaps(null));
  }, [configured]);

  if (setup.loading) return <Splash>Starting…</Splash>;
  if (setup.error) return <Splash error>Can't reach the server: {setup.error}</Splash>;
  if (!setup.data) return <Splash error>No response from the server.</Splash>;
  if (!setup.data.configured) return <Setup status={setup.data} onDone={setup.reload} />;

  return (
    <CapabilityProvider value={caps}>
      <div className="app">
        <header className="topbar">
          <div className="brand">Cartographarr</div>
          <nav>
            {TABS.map((t) => (
              <button key={t} className={t === tab ? "tab active" : "tab"} onClick={() => setTab(t)}>
                {t}
              </button>
            ))}
          </nav>
          <ThemeToggle />
        </header>

        <main>
          <ErrorBoundary name={tab} key={tab}>
            {tab === "Dashboard" && <Dashboard onNavigate={(t) => setTab(t as Tab)} />}
            {tab === "Map" && <Map geoipReady={setup.data.geoip_ready} />}
            {tab === "Activity" && <Activity />}
            {tab === "Rules" && <Rules />}
            {tab === "Settings" && <SettingsStub />}
          </ErrorBoundary>
        </main>
      </div>
    </CapabilityProvider>
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

function SettingsStub() {
  return <div className="pad muted">Settings coming next.</div>;
}

function Splash({ children, error }: { children: React.ReactNode; error?: boolean }) {
  return (
    <div className="splash">
      <div className={error ? "note bad-note" : "muted"}>{children}</div>
    </div>
  );
}
