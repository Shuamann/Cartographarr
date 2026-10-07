import { useState } from "react";
import { askConfirm } from "./Ask";
import { api, useApi } from "../lib/api";

type Kept = { enabled: boolean; folder: string; note: string | null; files: number; bytes: number; removed?: number };

function megabytes(bytes: number): string {
  if (bytes < 1024 * 1024) return `${Math.max(1, Math.round(bytes / 1024))} KB`;
  if (bytes < 1024 * 1024 * 1024) return `${(bytes / 1024 / 1024).toFixed(1)} MB`;
  return `${(bytes / 1024 / 1024 / 1024).toFixed(2)} GB`;
}

/* What the poster cache holds and where, beside the switch for it.
 *
 * The folder is said in full because it is the container's side of a mapping,
 * and the one thing worth checking is that it is the folder the mapping points
 * at: one that does not exist is passed over, and this says so. */
export default function PosterCache() {
  const kept = useApi<Kept>("/posters");
  const [busy, setBusy] = useState(false);
  const [failed, setFailed] = useState<string | null>(null);

  async function clear() {
    if (
      !(await askConfirm({
        title: "Clear the kept posters?",
        body: "Each one is fetched again from Plex or Tautulli the next time it is shown. Nothing else in the folder is touched.",
        confirm: "Clear",
      }))
    )
      return;
    setBusy(true);
    setFailed(null);
    try {
      await api.del<Kept>("/posters");
      kept.reload();
    } catch (err) {
      setFailed((err as Error).message);
    } finally {
      setBusy(false);
    }
  }

  const k = kept.data;
  return (
    <div className="history-check">
      {k && (
        <p className="muted small">
          {k.files === 0 ? (
            <>Nothing kept yet, in <code>{k.folder}</code>.</>
          ) : (
            <>
              {k.files.toLocaleString()} {k.files === 1 ? "picture" : "pictures"}, {megabytes(k.bytes)}, in <code>{k.folder}</code>.
            </>
          )}
          {!k.enabled && " Not adding to it while keeping is off."}
        </p>
      )}
      {k?.note && <p className="small warn-text">{k.note}.</p>}
      <div className="row">
        <button type="button" className="btn" onClick={clear} disabled={busy || !k?.files}>
          {busy ? "Clearing" : "Clear kept posters"}
        </button>
      </div>
      {(failed || kept.error) && (
        <p className="note bad-note" role="alert">
          {failed || kept.error}
        </p>
      )}
    </div>
  );
}
