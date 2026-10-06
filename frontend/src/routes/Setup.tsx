import { useCallback, useEffect, useState } from "react";
import Loading from "../components/Loading";
import { api, ApiError, type SetupStatus, type TautulliTest } from "../lib/api";

type Props = { status: SetupStatus; onDone: () => void };

type Way = "plex" | "tautulli";

type Server = {
  name: string;
  machine_identifier: string;
  owned: boolean;
  addresses: { uri: string; local: boolean; relay: boolean }[];
};

/* First run asks one question before anything else: connect to Plex itself,
 * or go through Tautulli. Everything after follows from the answer, and an
 * install that answers Plex is never shown a Tautulli field. Map locations
 * stay optional either way. */
export default function Setup({ status, onDone }: Props) {
  const [locked] = useState(() => new Set(status.locked));
  // The environment may already have half answered: Tautulli's address and
  // not its key, say. That is a hint, not a choice made for anybody.
  const [way, setWay] = useState<Way | null>(null);
  const [plexReady, setPlexReady] = useState(false);
  const [tautulliReady, setTautulliReady] = useState(false);
  const [tautulliValues, setTautulliValues] = useState<Record<string, string>>({});
  const [geo, setGeo] = useState<Record<string, string> | null>(null);
  const [saving, setSaving] = useState(false);
  const [saveError, setSaveError] = useState<string | null>(null);

  const ready = way === "plex" ? plexReady : way === "tautulli" ? tautulliReady : false;
  // Stable, because the steps report back from an effect and a new function
  // every render would have them report for ever.
  const tautulliChanged = useCallback((ok: boolean, values: Record<string, string>) => {
    setTautulliReady(ok);
    setTautulliValues(values);
  }, []);

  async function finish() {
    setSaving(true);
    setSaveError(null);
    const values: Record<string, string> = { ...(way === "tautulli" ? tautulliValues : {}), ...(geo ?? {}) };
    try {
      if (Object.keys(values).length) await api.put("/settings", values);
      // Started and not waited on: either can run for minutes, and the app is
      // usable while they do.
      if (way === "plex") api.post("/tasks/library_scan/run").catch(() => {});
      else api.post("/sync/run").catch(() => {});
      onDone();
    } catch (err) {
      setSaveError(err instanceof ApiError ? err.message : String(err));
      setSaving(false);
    }
  }

  return (
    <div className="setup">
      <div className="setup-card">
        <header>
          <h1>Cartographarr</h1>
          <p className="muted">Let&apos;s connect it to your Plex server.</p>
        </header>

        <section>
          <h2>How should it connect?</h2>
          <div className="setup-choices" role="radiogroup" aria-label="How to connect">
            <label className={way === "plex" ? "setup-choice on" : "setup-choice"}>
              <input type="radio" name="way" checked={way === "plex"} onChange={() => setWay("plex")} />
              <span>
                <strong>
                  Connect to Plex directly <span className="req">recommended</span>
                </strong>
                <span className="muted small">
                  Live streams, rules and bans, and the whole library down to every audio and subtitle track, straight
                  from Plex. Every play is recorded from today, so History, the map and Endpoints fill as people
                  watch. Nothing else to install.
                </span>
              </span>
            </label>
            <label className={way === "tautulli" ? "setup-choice on" : "setup-choice"}>
              <input type="radio" name="way" checked={way === "tautulli"} onChange={() => setWay("tautulli")} />
              <span>
                <strong>Connect through Tautulli</strong>
                <span className="muted small">
                  Everything above, and the only way to bring in plays from before today. Needs Tautulli running and
                  watching your server.
                </span>
              </span>
            </label>
          </div>
        </section>

        {way === "plex" && <PlexSteps locked={locked} onReady={setPlexReady} />}
        {way === "tautulli" && (
          <TautulliStep locked={locked} onReady={tautulliChanged} />
        )}

        {way && <MapLocations ready={status.geoip_ready} onChange={setGeo} />}

        {way && status.clock && (
          <section>
            <h2>
              The server&apos;s clock <span className="opt">check this</span>
            </h2>
            <p className="muted">
              This container thinks it is <strong>{new Date(status.clock.now).toLocaleString()}</strong> (
              {status.clock.zone}). Every rule with a time of day means that clock, so if this is wrong by hours, set TZ
              on the container and restart it.
            </p>
          </section>
        )}

        {way === "plex" && (
          <section>
            <h2>
              Bring in your history <span className="opt">later</span>
            </h2>
            <p className="muted">
              Plex keeps no record of where a play came from or how it went, so plays from before today live only in
              Tautulli. If you have it, connect it any time under Settings, Plex and Tautulli.
            </p>
          </section>
        )}

        {saveError && (
          <p className="note bad-note" role="alert">
            {saveError}
          </p>
        )}

        <footer>
          <button className="btn primary" onClick={finish} disabled={!ready || saving}>
            {saving ? "Saving" : "Finish setup"}
          </button>
          {!ready && (
            <span className="muted small">
              {way === null
                ? "Choose how to connect."
                : way === "plex"
                  ? "Link your Plex account and choose the server."
                  : "Test your Tautulli connection first."}
            </span>
          )}
        </footer>
      </div>
    </div>
  );
}

/* ---- Plex --------------------------------------------------------------- */

/* Link the account, then choose the server.
 *
 * Linking is Plex's own device code: the person types a short code at
 * plex.tv/link while signed in there, and this app is handed a token. The
 * password never comes here, and the token never comes back to this page: the
 * server keeps it. Pasting a token stays possible for anybody who has one. */
function PlexSteps({ locked, onReady }: { locked: Set<string>; onReady: (ok: boolean) => void }) {
  const [linked, setLinked] = useState(locked.has("plex_token"));
  const [chosen, setChosen] = useState<{ name: string | null; ms: number | null; url: string } | null>(null);
  const onLinked = useCallback(() => setLinked(true), []);

  useEffect(() => onReady(chosen !== null), [chosen, onReady]);

  return (
    <>
      <section>
        <h2>Link your Plex account</h2>
        {locked.has("plex_token") ? (
          <p className="note ok-note">The token is set by the environment. Nothing to do here.</p>
        ) : linked ? (
          <p className="note ok-note">Linked. The token is kept on this server.</p>
        ) : (
          <PlexLink onLinked={onLinked} />
        )}
      </section>

      {linked && (
        <section>
          <h2>Choose the server</h2>
          {chosen ? (
            <p className="note ok-note">
              Connected to {chosen.name ?? "Plex"} at {chosen.url}
              {chosen.ms != null ? `, which answered in ${chosen.ms} ms` : ""}.
            </p>
          ) : (
            <PlexServers onChosen={setChosen} />
          )}
        </section>
      )}
    </>
  );
}

function PlexLink({ onLinked }: { onLinked: () => void }) {
  const [link, setLink] = useState<{ id: string; code: string; url: string } | null>(null);
  const [asking, setAsking] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [pasting, setPasting] = useState(false);
  const [token, setToken] = useState("");
  const [checking, setChecking] = useState(false);

  async function newCode() {
    setAsking(true);
    setError(null);
    try {
      setLink(await api.post<{ id: string; code: string; url: string }>("/setup/plex/link"));
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setAsking(false);
    }
  }

  // Asks every two seconds whether the code has been entered. Stops when it
  // has, when the code lapses, or when the page moves on.
  useEffect(() => {
    if (!link) return;
    let stopped = false;
    let timer: number | undefined;
    async function poll() {
      try {
        const answer = await api.post<{ linked: boolean }>(`/setup/plex/link/${link!.id}`);
        if (stopped) return;
        if (answer.linked) return onLinked();
        timer = window.setTimeout(poll, 2000);
      } catch (err) {
        if (stopped) return;
        setLink(null);
        setError((err as Error).message);
      }
    }
    timer = window.setTimeout(poll, 2000);
    return () => {
      stopped = true;
      window.clearTimeout(timer);
    };
  }, [link, onLinked]);

  async function usePasted() {
    setChecking(true);
    setError(null);
    try {
      await api.post("/setup/plex/token", { plex_token: token });
      onLinked();
    } catch (err) {
      setError((err as Error).message);
      setChecking(false);
    }
  }

  return (
    <>
      <p className="muted">
        Plex gives this app a token for your account when you enter a short code at plex.tv, signed in as the server&apos;s
        owner. Your password never comes here.
      </p>
      {error && (
        <p className="note bad-note" role="alert">
          {error}
        </p>
      )}
      {link ? (
        <div className="setup-code">
          <span className="muted small">Go to</span>
          <a href={link.url} target="_blank" rel="noreferrer">
            plex.tv/link
          </a>
          <span className="muted small">and enter</span>
          <strong className="setup-code-value" aria-label={`The code is ${link.code.split("").join(" ")}`}>
            {link.code}
          </strong>
          <span className="muted small setup-waiting">Waiting for Plex</span>
        </div>
      ) : (
        <div className="setup-row">
          <button className="btn primary" onClick={newCode} disabled={asking}>
            {asking ? "Asking Plex" : "Get a code"}
          </button>
          {!pasting && (
            <button className="btn" onClick={() => setPasting(true)}>
              I already have a token
            </button>
          )}
        </div>
      )}
      {pasting && !link && (
        <div className="setup-row">
          <input
            type="password"
            autoComplete="off"
            aria-label="Plex token"
            placeholder="Paste a Plex token"
            value={token}
            onChange={(e) => setToken(e.target.value)}
          />
          <button className="btn" onClick={usePasted} disabled={checking || !token.trim()}>
            {checking ? "Checking" : "Use this token"}
          </button>
        </div>
      )}
    </>
  );
}

/* Finding the server is the slow call, about twenty seconds, because Plex
 * lists addresses that cannot be reached from outside the house and each one
 * has to be waited out. It happens once: the address chosen here is kept, and
 * every later connection takes a fraction of a second. */
function PlexServers({ onChosen }: { onChosen: (c: { name: string | null; ms: number | null; url: string }) => void }) {
  const [servers, setServers] = useState<Server[] | null>(null);
  const [looking, setLooking] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [trying, setTrying] = useState<string | null>(null);
  const [typed, setTyped] = useState("");

  async function find() {
    setLooking(true);
    setError(null);
    try {
      setServers((await api.get<{ servers: Server[] }>("/plex/servers")).servers);
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setLooking(false);
    }
  }

  useEffect(() => {
    void find();
  }, []);

  async function use(url: string) {
    setTrying(url);
    setError(null);
    try {
      const answer = await api.post<{ name: string | null; ms: number | null }>("/setup/plex/use", { plex_url: url });
      onChosen({ name: answer.name, ms: answer.ms, url });
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setTrying(null);
    }
  }

  return (
    <>
      {error && (
        <p className="note bad-note" role="alert">
          {error}
        </p>
      )}
      {looking && <Loading compact label="Asking Plex for your servers. This takes about twenty seconds." />}
      {servers && servers.length === 0 && (
        <p className="note">This account cannot reach any servers. Type the address below instead.</p>
      )}
      {servers?.map((s) => (
        <div key={s.machine_identifier} className="setup-server">
          <strong>
            {s.name}
            {!s.owned && <span className="opt">shared with you</span>}
          </strong>
          {/* Local addresses first, a relay last: the quick ones from inside
              the house, and the slow one only if nothing else answers. */}
          {s.addresses.map((a) => (
            <div key={a.uri} className="setup-row">
              <button className="btn" onClick={() => use(a.uri)} disabled={trying !== null}>
                {trying === a.uri ? "Trying" : "Use"}
              </button>
              <span className="setup-address" title={a.uri}>
                {a.uri}
              </span>
              <span className="muted small">{a.relay ? "relay, slow" : a.local ? "local" : "remote"}</span>
            </div>
          ))}
        </div>
      ))}
      {servers && (
        <div className="setup-row">
          <button className="btn" onClick={find} disabled={looking}>
            Look again
          </button>
        </div>
      )}
      <div className="setup-row">
        <input
          aria-label="Plex address"
          placeholder="Or type the address, like http://192.168.1.10:32400"
          value={typed}
          onChange={(e) => setTyped(e.target.value)}
        />
        <button className="btn" onClick={() => use(typed)} disabled={trying !== null || !typed.trim()}>
          {trying === typed ? "Trying" : "Use"}
        </button>
      </div>
    </>
  );
}

/* ---- Tautulli ----------------------------------------------------------- */

function TautulliStep({
  locked,
  onReady,
}: {
  locked: Set<string>;
  onReady: (ok: boolean, values: Record<string, string>) => void;
}) {
  const [url, setUrl] = useState("");
  const [localUrl, setLocalUrl] = useState("");
  const [apiKey, setApiKey] = useState("");
  const [test, setTest] = useState<TautulliTest | null>(null);
  const [testing, setTesting] = useState(false);

  // Env vars are already applied and locked; if they cover Tautulli entirely
  // there is nothing to ask for.
  const fromEnv = locked.has("tautulli_url") && locked.has("tautulli_api_key");

  useEffect(() => {
    const values: Record<string, string> = {};
    if (!locked.has("tautulli_url")) values.tautulli_url = url;
    if (!locked.has("tautulli_api_key")) values.tautulli_api_key = apiKey;
    if (localUrl && !locked.has("tautulli_local_url")) values.tautulli_local_url = localUrl;
    // Choosing Tautulli puts both sources back on it, in case an earlier
    // visit to this page chose Plex.
    if (!locked.has("activity_source")) values.activity_source = "tautulli";
    if (!locked.has("library_source")) values.library_source = "tautulli";
    onReady(fromEnv || test?.ok === true, values);
  }, [fromEnv, test, url, apiKey, localUrl, locked, onReady]);

  async function runTest() {
    setTesting(true);
    setTest(null);
    try {
      setTest(
        await api.post<TautulliTest>("/setup/test-tautulli", {
          tautulli_url: url,
          tautulli_api_key: apiKey,
          tautulli_local_url: localUrl,
        }),
      );
    } catch (err) {
      setTest({ ok: false, remote: { tried: true, ok: false, error: (err as Error).message }, local: { tried: false } });
    } finally {
      setTesting(false);
    }
  }

  return (
    <section>
      <h2>Tautulli</h2>
      {fromEnv ? (
        <p className="note ok-note">Already configured by environment variables. Nothing to do here.</p>
      ) : (
        <>
          <label>
            Tautulli URL
            <input
              autoComplete="off"
              spellCheck={false}
              value={locked.has("tautulli_url") ? "Set by the environment" : url}
              disabled={locked.has("tautulli_url")}
              onChange={(e) => setUrl(e.target.value)}
              placeholder="https://tautulli.example.com"
            />
            <small>The address this app can always reach.</small>
          </label>
          <label>
            API key
            <input
              type="password"
              autoComplete="new-password"
              value={apiKey}
              disabled={locked.has("tautulli_api_key")}
              onChange={(e) => setApiKey(e.target.value)}
              placeholder="In Tautulli: Settings, Web Interface, API"
            />
          </label>
          <label>
            Local URL <span className="opt">optional</span>
            <input value={localUrl} onChange={(e) => setLocalUrl(e.target.value)} placeholder="192.168.1.10:8181" />
            <small>Preferred when reachable, so traffic skips your reverse proxy. Safe to leave blank.</small>
          </label>
          <button
            className="btn"
            onClick={runTest}
            disabled={testing || (!url.trim() && !locked.has("tautulli_url")) || !apiKey.trim()}
          >
            {testing ? "Testing" : "Test connection"}
          </button>
          {test && <TestResult test={test} />}
        </>
      )}
    </section>
  );
}

function TestResult({ test }: { test: TautulliTest }) {
  const { remote, local } = test;
  return (
    <div className="test-result">
      <p className={`note ${remote.ok ? "ok-note" : "bad-note"}`}>
        {remote.ok
          ? `Connected to ${remote.server_name ?? "Tautulli"}${remote.version ? ` (Plex ${remote.version})` : ""}.`
          : `Could not connect: ${remote.error}`}
      </p>
      {/* A local URL that fails is not an error; it just won't be preferred.
          Saying so prevents a pointless round of debugging. */}
      {local.tried && !local.ok && (
        <p className="note warn-note">
          The local URL is not reachable from here, so the main URL will be used. That is expected if this app runs
          outside your LAN.
        </p>
      )}
      {local.tried && local.ok && <p className="note ok-note">Local URL reachable, so it will be preferred.</p>}
    </div>
  );
}

/* ---- map locations ------------------------------------------------------ */

function MapLocations({ ready, onChange }: { ready: boolean; onChange: (values: Record<string, string> | null) => void }) {
  const [accountId, setAccountId] = useState("");
  const [licenseKey, setLicenseKey] = useState("");
  const [result, setResult] = useState<{ ok: boolean; error?: string | null } | null>(null);
  const [testing, setTesting] = useState(false);

  async function runTest() {
    setTesting(true);
    setResult(null);
    try {
      const answer = await api.post<{ ok: boolean; error?: string | null }>("/setup/test-maxmind", {
        maxmind_account_id: accountId,
        maxmind_license_key: licenseKey,
      });
      setResult(answer);
      onChange(answer.ok ? { maxmind_account_id: accountId, maxmind_license_key: licenseKey } : null);
    } catch (err) {
      setResult({ ok: false, error: (err as Error).message });
      onChange(null);
    } finally {
      setTesting(false);
    }
  }

  return (
    <section>
      <h2>
        Map locations <span className="opt">optional</span>
      </h2>
      <p className="muted">
        A free{" "}
        <a href="https://www.maxmind.com/en/geolite2/signup" target="_blank" rel="noreferrer">
          MaxMind GeoLite2
        </a>{" "}
        account turns IP addresses into map pins. Skip it and everything else still works; you can add it later.
      </p>
      {ready ? (
        <p className="note ok-note">Location database already installed.</p>
      ) : (
        <>
          <label>
            Account ID
            <input autoComplete="off" value={accountId} onChange={(e) => setAccountId(e.target.value)} />
          </label>
          <label>
            License key
            <input
              type="password"
              autoComplete="new-password"
              value={licenseKey}
              onChange={(e) => setLicenseKey(e.target.value)}
            />
          </label>
          <button className="btn" onClick={runTest} disabled={testing || !accountId.trim() || !licenseKey.trim()}>
            {testing ? "Downloading" : "Verify and download"}
          </button>
          {result && (
            <p className={`note ${result.ok ? "ok-note" : "bad-note"}`}>
              {result.ok
                ? "Location databases downloaded."
                : `${result.error} A brand new key can take a few minutes to start working.`}
            </p>
          )}
        </>
      )}
    </section>
  );
}
