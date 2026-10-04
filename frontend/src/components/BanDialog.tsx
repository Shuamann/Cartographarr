import { useEffect, useRef, useState } from "react";
import { BAN_LENGTHS, ban, banAddress, scopesFor } from "../lib/bans";

/* A device or an address: the same two questions either way, so one dialog. */
export type BanRequest = {
  kind: "device" | "address";
  id: string;
  label: string;
  resolve: (banned: boolean) => void;
};

/* Ban one device: a reason for the Log and how long. Used by every Ban button
 * (People, stream cards, the map), which used to ask with a browser prompt
 * and could only ban for good.
 *
 * A native <dialog>, so Escape closes it and focus stays inside while open. */
export default function BanDialog({ request, onClose }: { request: BanRequest | null; onClose: () => void }) {
  const ref = useRef<HTMLDialogElement>(null);
  const [reason, setReason] = useState("");
  const [hours, setHours] = useState(0);
  // Which address the ban is written against: the one asked about, or the
  // block around it. Reset whenever the dialog opens on something new.
  const [scope, setScope] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    const dialog = ref.current;
    if (!dialog) return;
    if (request && !dialog.open) {
      setReason("");
      setHours(0);
      setScope(request.id);
      setError(null);
      dialog.showModal();
    } else if (!request && dialog.open) {
      dialog.close();
    }
  }, [request]);

  const scopes = request && request.kind === "address" ? scopesFor(request.id) : [];

  function finish(banned: boolean) {
    request?.resolve(banned);
    onClose();
  }

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    if (!request) return;
    setBusy(true);
    setError(null);
    try {
      if (request.kind === "address") await banAddress(scope || request.id, reason, hours);
      else await ban(request.id, reason, hours);
      finish(true);
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setBusy(false);
    }
  }

  return (
    <dialog ref={ref} className="dialog" onCancel={() => finish(false)} aria-labelledby="ban-dialog-title">
      {request && (
        <form onSubmit={submit}>
          <h2 id="ban-dialog-title">Ban {request.label}?</h2>
          <p className="muted small">
            {request.kind === "address"
              ? "Any stream from this address is stopped. A range works too, typed as 203.0.113.0/24. You can unban it from the ban list on the Rules page."
              : "Any stream from this device is stopped, or only recorded if the ban list is set to record only on the Rules page. You can unban it from People or the ban list."}
          </p>
          {request.kind === "address" && scopes.length > 1 && (
            <label>
              How far it reaches
              <select value={scope} onChange={(e) => setScope(e.target.value)}>
                {scopes.map((s) => (
                  <option key={s.value} value={s.value}>
                    {s.label}
                  </option>
                ))}
              </select>
              <small>{scopes.find((s) => s.value === scope)?.hint}</small>
            </label>
          )}
          <label>
            Reason, for the Log
            <input value={reason} onChange={(e) => setReason(e.target.value)} placeholder="Optional" autoFocus />
          </label>
          <label>
            For
            <select value={hours} onChange={(e) => setHours(Number(e.target.value))}>
              {BAN_LENGTHS.map((l) => (
                <option key={l.hours} value={l.hours}>
                  {l.label}
                </option>
              ))}
            </select>
          </label>
          {error && <p className="note bad-note" role="alert">{error}</p>}
          <div className="row dialog-actions">
            <button type="button" className="btn" onClick={() => finish(false)} disabled={busy}>
              Cancel
            </button>
            <button type="submit" className="btn danger" disabled={busy}>
              {busy ? "Banning\u2026" : request.kind === "address" ? "Ban address" : "Ban device"}
            </button>
          </div>
        </form>
      )}
    </dialog>
  );
}
