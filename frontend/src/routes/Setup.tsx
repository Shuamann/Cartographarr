import { useState } from "react";
import { api, ApiError, type SetupStatus, type TautulliTest } from "../lib/api";

type Props = { status: SetupStatus; onDone: () => void };

/* Two steps, because only the first one is required: Tautulli is what the app
 * reads, MaxMind only adds map pins. Someone can finish setup without a
 * MaxMind account and add it later in Settings. */
export default function Setup({ status, onDone }: Props) {
  const locked = new Set(status.locked);

  const [url, setUrl] = useState("");
  const [localUrl, setLocalUrl] = useState("");
  const [apiKey, setApiKey] = useState("");
  const [test, setTest] = useState<TautulliTest | null>(null);
  const [testing, setTesting] = useState(false);

  const [accountId, setAccountId] = useState("");
  const [licenseKey, setLicenseKey] = useState("");
  const [geoResult, setGeoResult] = useState<{ ok: boolean; error?: string | null } | null>(null);
  const [geoTesting, setGeoTesting] = useState(false);

  const [saving, setSaving] = useState(false);
  const [saveError, setSaveError] = useState<string | null>(null);

  // Env vars are already applied and locked; if they cover Tautulli entirely
  // there is nothing to ask for.
  const tautulliFromEnv = locked.has("tautulli_url") && locked.has("tautulli_api_key");
  const canContinue = tautulliFromEnv || test?.ok === true;

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
      setTest({
        ok: false,
        remote: { tried: true, ok: false, error: (err as Error).message },
        local: { tried: false },
      });
    } finally {
      setTesting(false);
    }
  }

  async function runGeoTest() {
    setGeoTesting(true);
    setGeoResult(null);
    try {
      setGeoResult(
        await api.post<{ ok: boolean; error?: string | null }>("/setup/test-maxmind", {
          maxmind_account_id: accountId,
          maxmind_license_key: licenseKey,
        }),
      );
    } catch (err) {
      setGeoResult({ ok: false, error: (err as Error).message });
    } finally {
      setGeoTesting(false);
    }
  }

  async function finish() {
    setSaving(true);
    setSaveError(null);
    const values: Record<string, string> = {};
    if (!tautulliFromEnv) {
      values.tautulli_url = url;
      values.tautulli_api_key = apiKey;
      if (localUrl) values.tautulli_local_url = localUrl;
    }
    if (geoResult?.ok) {
      values.maxmind_account_id = accountId;
      values.maxmind_license_key = licenseKey;
    }

    try {
      if (Object.keys(values).length) await api.put("/settings", values);
      // Kick the backfill but don't wait on it, since it can run for minutes.
      api.post("/sync/run").catch(() => {});
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
          <p className="muted">Let's connect it to your server.</p>
        </header>

        <section>
          <h2>
            Tautulli <span className="req">required</span>
          </h2>

          {tautulliFromEnv ? (
            <p className="note ok-note">
              Already configured by environment variables. Nothing to do here.
            </p>
          ) : (
            <>
              <label>
                Tautulli URL
                <input
                  value={url}
                  onChange={(e) => setUrl(e.target.value)}
                  placeholder="https://tautulli.example.com"
                  autoFocus
                />
                <small>The address this app can always reach.</small>
              </label>

              <label>
                API key
                <input
                  type="password"
                  value={apiKey}
                  onChange={(e) => setApiKey(e.target.value)}
                  placeholder="Settings → Web Interface → API"
                />
              </label>

              <label>
                Local URL <span className="opt">optional</span>
                <input
                  value={localUrl}
                  onChange={(e) => setLocalUrl(e.target.value)}
                  placeholder="192.168.1.10:8181"
                />
                <small>
                  Preferred when reachable, so traffic skips your reverse proxy. Safe to leave
                  blank.
                </small>
              </label>

              <button
                className="btn"
                onClick={runTest}
                disabled={testing || !url.trim() || !apiKey.trim()}
              >
                {testing ? "Testing…" : "Test connection"}
              </button>

              {test && <TestResult test={test} />}
            </>
          )}
        </section>

        <section>
          <h2>
            Map locations <span className="opt">optional</span>
          </h2>
          <p className="muted">
            A free{" "}
            <a href="https://www.maxmind.com/en/geolite2/signup" target="_blank" rel="noreferrer">
              MaxMind GeoLite2
            </a>{" "}
            account turns IP addresses into map pins. Skip it and everything else still works,
            you can add it later.
          </p>

          {status.geoip_ready ? (
            <p className="note ok-note">Location database already installed.</p>
          ) : (
            <>
              <label>
                Account ID
                <input value={accountId} onChange={(e) => setAccountId(e.target.value)} />
              </label>
              <label>
                License key
                <input
                  type="password"
                  value={licenseKey}
                  onChange={(e) => setLicenseKey(e.target.value)}
                />
              </label>
              <button
                className="btn"
                onClick={runGeoTest}
                disabled={geoTesting || !accountId.trim() || !licenseKey.trim()}
              >
                {geoTesting ? "Downloading…" : "Verify and download"}
              </button>

              {geoResult && (
                <p className={`note ${geoResult.ok ? "ok-note" : "bad-note"}`}>
                  {geoResult.ok
                    ? "Location databases downloaded."
                    : `${geoResult.error} A brand-new key can take a few minutes to start working.`}
                </p>
              )}
            </>
          )}
        </section>

        {saveError && <p className="note bad-note">{saveError}</p>}

        <footer>
          <button className="btn primary" onClick={finish} disabled={!canContinue || saving}>
            {saving ? "Saving…" : "Finish setup"}
          </button>
          {!canContinue && <span className="muted">Test your Tautulli connection first.</span>}
        </footer>
      </div>
    </div>
  );
}

function TestResult({ test }: { test: TautulliTest }) {
  const { remote, local } = test;
  return (
    <div className="test-result">
      <p className={`note ${remote.ok ? "ok-note" : "bad-note"}`}>
        {remote.ok
          ? `Connected to ${remote.server_name ?? "Tautulli"}${
              remote.version ? ` (Plex ${remote.version})` : ""
            }.`
          : `Couldn't connect: ${remote.error}`}
      </p>

      {/* A local URL that fails is not an error; it just won't be preferred.
          Saying so prevents a pointless round of debugging. */}
      {local.tried && !local.ok && (
        <p className="note warn-note">
          The local URL isn't reachable from here, so the main URL will be used. That's expected
          if this app runs outside your LAN.
        </p>
      )}
      {local.tried && local.ok && <p className="note ok-note">Local URL reachable, so it will be preferred.</p>}
    </div>
  );
}
