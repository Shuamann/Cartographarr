import { askConfirm, tell } from "./Ask";
import { useState } from "react";
import { api, useApi, type TravelFlag } from "../lib/api";
import SignalDetail from "./SignalDetail";

type Ignore = {
  id: number;
  user_id: number;
  user_name: string;
  label: string | null;
  reason: string | null;
  created_by: string | null;
  closed: number;
};

/* Accounts being used in two places at once, or moving impossibly fast.
 *
 * Two findings, not one. An overlap is one account playing in two places
 * simultaneously, which needs no explanation about speed. A gap that is real
 * but far too short for the distance is the travel case. They are labelled
 * separately because they are different claims.
 *
 * Each row opens the plays behind it. Reviewed and Ignore live in there, next
 * to what they each do.
 */
export default function TravelFlags({
  isAdmin,
  onOpenUser,
}: {
  isAdmin: boolean;
  onOpenUser?: (userId: number) => void;
}) {
  const [showAll, setShowAll] = useState(false);
  const [open, setOpen] = useState<number | null>(null);
  const [showIgnores, setShowIgnores] = useState(false);
  const flags = useApi<TravelFlag[]>(`/travel-flags${showAll ? "" : "?status=new"}`, [showAll]);
  const ignores = useApi<Ignore[]>("/signal-ignores");

  function changed() {
    flags.reload();
    ignores.reload();
  }

  async function stopIgnoring(pattern: Ignore) {
    if (!(await askConfirm({
      title: `Stop ignoring ${pattern.label} for ${pattern.user_name}?`,
      body: "Signals it closed reopen.",
      confirm: "Stop ignoring",
    }))) return;
    await api.del(`/signal-ignores/${pattern.id}`);
    changed();
  }

  const rows = flags.data ?? [];
  const patterns = ignores.data ?? [];

  return (
    <section>
      <div className="row-between">
        <h2 className="section-head">Shared account signals</h2>
        <div className="row">
          {patterns.length > 0 && (
            <button className="tab" onClick={() => setShowIgnores(!showIgnores)}>
              {showIgnores ? "Hide ignored patterns" : `Ignored patterns ${patterns.length}`}
            </button>
          )}
          {/* Not one of these had ever been reviewed on the server this was
              written for, so the count had been a constant since there were
              signals, and a constant says nothing. Getting to nought is what
              makes the next one worth looking at. */}
          {!showAll && rows.length > 1 && (
            <button
              className="tab"
              title="Mark them all reviewed, so the next signal stands out"
              onClick={async () => {
                if (!(await askConfirm({
                  title: `Mark all ${rows.length} signals as reviewed?`,
                  body: "They stay on the list, but the next new one stands out.",
                  confirm: "Mark them reviewed",
                }))) return;
                try {
                  await api.post("/travel-flags/review-all", {});
                  changed();
                } catch (err) {
                  void tell("That did not work", (err as Error).message);
                }
              }}
            >
              Mark all reviewed
            </button>
          )}
          <button className="tab" onClick={() => setShowAll(!showAll)}>
            {showAll ? "Unreviewed only" : "Show all"}
          </button>
        </div>
      </div>

      {showIgnores && (
        <div className="mini-list signal-ignores">
          {patterns.map((p) => (
            <div key={p.id} className="mini">
              <div className="min0">
                <strong>{p.user_name}</strong> between {p.label}
                <p className="muted small">
                  {[p.reason, p.created_by ? `set by ${p.created_by}` : null, `${p.closed} signal${p.closed === 1 ? "" : "s"} closed`]
                    .filter(Boolean)
                    .join(" \u00b7 ")}
                </p>
              </div>
              {isAdmin && (
                <button className="tab" onClick={() => stopIgnoring(p)}>
                  Stop ignoring
                </button>
              )}
            </div>
          ))}
        </div>
      )}

      {rows.length === 0 && (
        <p className="muted">
          {showAll ? "Nothing flagged." : "Nothing new. Everything flagged has been reviewed or ignored."}
        </p>
      )}

      <div className="log-list">
        {rows.slice(0, 25).map((f) => (
          <article key={f.id} className={open === f.id ? "log-entry open" : "log-entry"}>
            <button className="log-summary signal-summary" onClick={() => setOpen(open === f.id ? null : f.id)} aria-expanded={open === f.id}>
              <span className="log-when muted small">
                {f.to_started ? new Date(f.to_started * 1000).toLocaleString() : ""}
              </span>
              <span className="log-what clip">
                <strong className="clip">
                  {onOpenUser ? (
                    <span
                      className="linkish"
                      role="link"
                      onClick={(e) => {
                        e.stopPropagation();
                        onOpenUser(f.user_id);
                      }}
                    >
                      {f.user_name}
                    </span>
                  ) : (
                    f.user_name
                  )}
                </strong>
                <span className="muted small clip">
                  {f.kind === "concurrent"
                    ? `${f.from_city ?? "an unnamed place"} and ${f.to_city ?? "an unnamed place"} at the same time, ${Math.round(f.km ?? 0).toLocaleString()} km apart`
                    : `${f.from_city ?? "an unnamed place"} to ${f.to_city ?? "an unnamed place"}, ${Math.round(f.km ?? 0).toLocaleString()} km in ${f.hours?.toFixed(1)} h`}
                </span>
              </span>
              <span className="log-result">
                <span className="pill">{f.kind === "concurrent" ? "at once" : "too fast"}</span>
                {f.hosting_involved && (
                  <span className="pill vpn" title="A VPN explains this without a shared password">
                    VPN
                  </span>
                )}
                {(f.times_seen ?? 1) >= 3 && (
                  <span
                    className="pill"
                    title={
                      "This account has been flagged between these two places " +
                      `${f.times_seen} times. A route that keeps coming back is usually how their connection is ` +
                      "carried, a phone on a mobile network or a VPN with a favourite exit, rather than two people. " +
                      "Open it and ignore the pattern if that is what it is."
                    }
                  >
                    seen {f.times_seen}&times;
                  </span>
                )}
                {f.status !== "new" && <span className="pill">{f.status}</span>}
              </span>
              <span className="log-caret" aria-hidden="true">
                {open === f.id ? "\u25b4" : "\u25be"}
              </span>
            </button>
            {open === f.id && (
              <div className="log-detail">
                <div className="min0">
                  <SignalDetail id={f.id} onChanged={changed} />
                </div>
              </div>
            )}
          </article>
        ))}
      </div>
    </section>
  );
}
