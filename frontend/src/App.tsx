import { useState } from "react";
import { useApi, type SetupStatus } from "./lib/api";
import Setup from "./routes/Setup";
import Map from "./routes/Map";

const TABS = ["Map", "Settings"] as const;
type Tab = (typeof TABS)[number];

export default function App() {
  const setup = useApi<SetupStatus>("/setup");
  const [tab, setTab] = useState<Tab>("Map");

  if (setup.loading) return <Splash>Starting…</Splash>;
  if (setup.error) return <Splash error>Can't reach the server: {setup.error}</Splash>;
  if (!setup.data) return <Splash error>No response from the server.</Splash>;

  if (!setup.data.configured) return <Setup status={setup.data} onDone={setup.reload} />;

  return (
    <div className="app">
      <header className="topbar">
        <div className="brand">Cartographarr</div>
        <nav>
          {TABS.map((t) => (
            <button
              key={t}
              className={t === tab ? "tab active" : "tab"}
              onClick={() => setTab(t)}
            >
              {t}
            </button>
          ))}
        </nav>
        <ThemeToggle />
      </header>

      <main>{tab === "Map" ? <Map geoipReady={setup.data.geoip_ready} /> : <SettingsStub />}</main>
    </div>
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
