import { useEffect, useRef, useState } from "react";
import { BAN_LENGTHS, ban } from "../lib/bans";

export type BanRequest = { machineId: string; label: string; resolve: (banned: boolean) => void };

/* Ban one device: a reason for the Log and how long. Used by every Ban button
 * (People, stream cards, the map), which used to ask with a browser prompt
 * and could only ban for good.
 *
 * A native <dialog>, so Escape closes it and focus stays inside while open. */
export default function BanDialog({ request, onClose }: { request: BanRequest | null; onClose: () => void }) {
  const ref = useRef<HTMLDialogElement>(null);
  const [reason, setReason] = useState("");
  const [hours, setHours] = useState(0);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    const dialog = ref.current;
    if (!dialog) return;
    if (request && !dialog.open) {
      setReason("");
      setHours(0);
      setError(null);
      dialog.showModal();
    } else if (!request && dialog.open) {
      dialog.close();
    }
  }, [request]);

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
      await ban(request.machineId, reason, hours);
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
            Any stream from this device is stopped, or only recorded if the ban list is set to record only on the Rules
            page. You can unban it from People or the ban list.
          </p>
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
          {error && <p className="note bad-note">{error}</p>}
          <div className="row dialog-actions">
            <button type="button" className="btn" onClick={() => finish(false)} disabled={busy}>
              Cancel
            </button>
            <button type="submit" className="btn danger" disabled={busy}>
              {busy ? "Banning…" : "Ban device"}
            </button>
          </div>
        </form>
      )}
    </dialog>
  );
}
