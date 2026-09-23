import { useState } from "react";
import { api, useApi } from "../lib/api";
import ModeSwitch from "./ModeSwitch";

/* Blocked countries: the ban list, by place.
 *
 * Each country says what should happen, because most places are worth watching
 * rather than cutting off: flag records the stream, warn tells the viewer, stop
 * ends it. The list runs through the same path as any rule, so record only, the
 * cooldown and the Log all behave the same way.
 */

type Country = {
  code: string;
  name: string | null;
  mode: "flag" | "warn" | "stop";
  vpn_mode: "flag" | "warn" | "stop" | "ignore" | null;
  reason: string | null;
  blocked_by: string | null;
  blocked_at: string | null;
  plays: number;
  last_play: number | null;
};

type Listing = {
  items: Country[];
  allow_list: boolean;
  message: string;
  record_only: boolean;
  dry_run_locked: boolean;
};

type Seen = { code: string; name: string; plays: number; last_play: number | null; blocked: boolean };

type Preview = { plays: number; users: number; days: number; countries: { code: string; name: string; plays: number; users: number }[] };

const MODES: { id: Country["mode"]; label: string; blurb: string }[] = [
  { id: "flag", label: "Flag", blurb: "recorded in the Log, nothing else" },
  { id: "warn", label: "Warn", blurb: "the viewer is messaged" },
  { id: "stop", label: "Stop", blurb: "the stream is ended" },
];

export default function CountryList() {
  const list = useApi<Listing>("/geoblocks");
  const seen = useApi<Seen[]>("/geoblocks/countries");
  const [open, setOpen] = useState(false);
  const [preview, setPreview] = useState<Preview | null>(null);
  const [error, setError] = useState<string | null>(null);

  async function reload() {
    list.reload();
    seen.reload();
  }

  async function act(run: () => Promise<unknown>) {
    setError(null);
    try {
      await run();
      await reload();
      setPreview(null);
    } catch (err) {
      setError((err as Error).message);
    }
  }

  const d = list.data;
  const blocked = d?.items ?? [];
  const allowList = d?.allow_list ?? false;

  return (
    <div className="rule system-rule">
      <div className="min0">
        <div className="row">
          <h2>Blocked countries</h2>
          <span className="pill">built in, runs first</span>
          <span className={blocked.length ? "pill banned" : "pill"}>
            {blocked.length} {allowList ? "allowed" : "listed"}
          </span>
          {d && <span className={d.record_only ? "pill" : "pill warn"}>{d.record_only ? "records only" : "acts"}</span>}
        </div>
        <p className="small">
          <span className="muted">When </span>
          {allowList ? "a stream comes from anywhere not on the list" : "a stream comes from a listed country"}
          <span className="muted"> then </span>
          {allowList ? "record it" : "do what that country says: flag, warn or stop."}
        </p>
        <p className="muted small">Add a country here, or from a place on the map.</p>
        {error && <p className="note bad-note">{error}</p>}

        {open && (
          <>
            <div className="mini-list">
              {blocked.length === 0 && <p className="muted pad-s">No countries listed.</p>}
              {blocked.map((c) => (
                <div key={c.code} className="mini">
                  <div className="min0">
                    <strong>{c.name || c.code}</strong>
                    <p className="muted small">
                      {[
                        `${c.plays.toLocaleString()} ${c.plays === 1 ? "play" : "plays"} from here`,
                        c.reason,
                        c.blocked_by ? `by ${c.blocked_by}` : null,
                      ]
                        .filter(Boolean)
                        .join(" · ")}
                    </p>
                  </div>
                  <div className="row">
                    {!allowList && (
                      <>
                        <div className="segmented">
                          {MODES.map((m) => (
                            <button
                              key={m.id}
                              className={c.mode === m.id ? "seg on" : "seg"}
                              title={m.blurb}
                              onClick={() =>
                                act(() =>
                                  api.post("/geoblocks", {
                                    code: c.code,
                                    mode: m.id,
                                    reason: c.reason ?? "",
                                    vpn_mode: c.vpn_mode,
                                  }),
                                )
                              }
                            >
                              {m.label}
                            </button>
                          ))}
                        </div>
                        <select
                          value={c.vpn_mode ?? ""}
                          title="What to do when the address is a VPN or hosting provider"
                          onChange={(e) =>
                            act(() =>
                              api.post("/geoblocks", {
                                code: c.code,
                                mode: c.mode,
                                reason: c.reason ?? "",
                                vpn_mode: e.target.value || null,
                              }),
                            )
                          }
                        >
                          <option value="">VPN: same</option>
                          <option value="flag">VPN: flag only</option>
                          <option value="warn">VPN: warn</option>
                          <option value="stop">VPN: stop</option>
                          <option value="ignore">VPN: leave alone</option>
                        </select>
                      </>
                    )}
                    <button className="tab" onClick={() => act(() => api.del(`/geoblocks/${c.code}`))}>
                      Remove
                    </button>
                  </div>
                </div>
              ))}
            </div>

            <AddCountry seen={seen.data ?? []} onAdd={(code, mode, reason) => act(() => api.post("/geoblocks", { code, mode, reason }))} />

            <div className="row wrap">
              <button
                className="tab"
                onClick={async () => {
                  setError(null);
                  try {
                    setPreview(await api.get<Preview>("/geoblocks/preview"));
                  } catch (err) {
                    setError((err as Error).message);
                  }
                }}
              >
                What would this have caught?
              </button>
              <label className="check">
                <input
                  type="checkbox"
                  checked={allowList}
                  onChange={(e) => {
                    const on = e.target.checked;
                    if (on && !window.confirm("Turn the list around? Everywhere NOT listed is flagged instead.")) return;
                    act(() => api.put("/geoblocks/settings", { allow_list: on }));
                  }}
                />
                Treat the list as the only places allowed
              </label>
            </div>

            {preview && (
              <div className="note">
                {preview.plays === 0 ? (
                  "Nothing in the last 90 days would have matched."
                ) : (
                  <>
                    {preview.plays.toLocaleString()} {preview.plays === 1 ? "play" : "plays"} in the last {preview.days}{" "}
                    days would have matched:{" "}
                    {preview.countries.map((c) => `${c.name} (${c.plays})`).join(", ")}
                  </>
                )}
              </div>
            )}
          </>
        )}
      </div>

      <div className="row">
        {d && (
          <ModeSwitch
            recordOnly={d.record_only}
            locked={d.dry_run_locked}
            onChange={(recordOnly) => {
              if (!recordOnly && !window.confirm("Let the country list act? Streams from countries set to stop will be ended.")) return;
              act(() => api.put("/geoblocks/settings", { record_only: recordOnly }));
            }}
          />
        )}
        <button className="tab" onClick={() => setOpen(!open)}>
          {open ? "Hide list" : "Show list"}
        </button>
      </div>
    </div>
  );
}

function AddCountry({
  seen,
  onAdd,
}: {
  seen: Seen[];
  onAdd: (code: string, mode: string, reason: string) => void;
}) {
  const [code, setCode] = useState("");
  const [mode, setMode] = useState("flag");
  const [reason, setReason] = useState("");
  const options = seen.filter((c) => !c.blocked);

  return (
    <div className="row wrap add-country">
      <select value={code} onChange={(e) => setCode(e.target.value)}>
        <option value="">Country played from...</option>
        {options.map((c) => (
          <option key={c.code} value={c.code}>
            {c.name} ({c.plays.toLocaleString()})
          </option>
        ))}
      </select>
      <select value={mode} onChange={(e) => setMode(e.target.value)}>
        {MODES.map((m) => (
          <option key={m.id} value={m.id}>
            {m.label}: {m.blurb}
          </option>
        ))}
      </select>
      <input placeholder="Reason, for the log" value={reason} onChange={(e) => setReason(e.target.value)} />
      <button
        className="btn"
        disabled={code.length !== 2}
        onClick={() => {
          onAdd(code, mode, reason);
          setCode("");
          setReason("");
        }}
      >
        Add
      </button>
    </div>
  );
}
