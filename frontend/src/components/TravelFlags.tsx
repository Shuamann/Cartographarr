import { useState } from "react";
import { api, useApi, type TravelFlag } from "../lib/api";

/* Accounts being used in two places at once, or moving impossibly fast.
 *
 * Two findings, not one. An overlap is one account playing in two places
 * simultaneously, which needs no explanation about speed. A gap that is real
 * but far too short for the distance is the travel case. They are labelled
 * separately because they are different claims.
 */
export default function TravelFlags({
  isAdmin,
  onOpenUser,
}: {
  isAdmin: boolean;
  onOpenUser?: (userId: number) => void;
}) {
  const [showAll, setShowAll] = useState(false);
  const flags = useApi<TravelFlag[]>(`/travel-flags${showAll ? "" : "?status=new"}`, [showAll]);

  async function review(flag: TravelFlag, status: "reviewed" | "ignored") {
    await api.patch(`/travel-flags/${flag.id}`, { status });
    flags.reload();
  }

  const rows = flags.data ?? [];

  return (
    <section>
      <div className="row-between">
        <h2 className="section-head">Shared account signals</h2>
        <button className="tab" onClick={() => setShowAll(!showAll)}>
          {showAll ? "Unreviewed only" : "Show all"}
        </button>
      </div>

      {rows.length === 0 && (
        <p className="muted">
          {showAll ? "Nothing flagged." : "Nothing new. Everything flagged has been reviewed."}
        </p>
      )}

      <div className="mini-list">
        {rows.slice(0, 25).map((f) => (
          <div key={f.id} className="mini">
            <div className="min0">
              <strong>
                {onOpenUser ? (
                  <button className="linkish" onClick={() => onOpenUser(f.user_id)}>
                    {f.user_name}
                  </button>
                ) : (
                  f.user_name
                )}
              </strong>
              <p className="muted small">
                {f.kind === "concurrent" ? (
                  <>
                    Playing in {f.from_city ?? "an unnamed place"} and{" "}
                    {f.to_city ?? "an unnamed place"} at the same time,{" "}
                    {Math.round(f.km ?? 0).toLocaleString()} km apart
                  </>
                ) : (
                  <>
                    {f.from_city ?? "an unnamed place"} to {f.to_city ?? "an unnamed place"},{" "}
                    {Math.round(f.km ?? 0).toLocaleString()} km in {f.hours?.toFixed(1)} h, about{" "}
                    {Math.round(f.kmh ?? 0).toLocaleString()} km/h
                  </>
                )}
              </p>
              <p className="muted small">
                <span className="pill">{f.kind === "concurrent" ? "at once" : "too fast"}</span>
                {f.hosting_involved && (
                  <span className="pill vpn" title="A VPN explains this without a shared password">
                    VPN involved
                  </span>
                )}
                {f.status !== "new" && <span className="pill">{f.status}</span>}
                {f.to_started ? new Date(f.to_started * 1000).toLocaleString() : ""}
              </p>
            </div>

            {isAdmin && f.status === "new" && (
              <div className="row">
                <button className="tab" onClick={() => review(f, "reviewed")}>
                  Reviewed
                </button>
                <button className="tab" onClick={() => review(f, "ignored")}>
                  Ignore
                </button>
              </div>
            )}
          </div>
        ))}
      </div>
    </section>
  );
}
