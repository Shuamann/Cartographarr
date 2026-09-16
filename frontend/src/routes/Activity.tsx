import { useEffect, useState } from "react";
import { api, useApi, type Activity, type LiveSession } from "../lib/api";
import { useIsAvailable } from "../components/Gated";

export default function ActivityRoute() {
  const live = useApi<Activity>("/activity");

  // Polling rather than SSE: one endpoint, no connection to keep alive, and
  // the payload is already trimmed server-side.
  useEffect(() => {
    const timer = setInterval(live.reload, 5000);
    return () => clearInterval(timer);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const sessions = live.data?.sessions ?? [];

  return (
    <div className="pad scroll">
      <div className="row-between">
        <h1>Now playing</h1>
        <span className="muted">
          {sessions.length === 0 ? "Nothing streaming" : `${sessions.length} streaming`}
          {live.data?.transcode_count ? ` · ${live.data.transcode_count} transcoding` : ""}
        </span>
      </div>

      {live.data?.error && <p className="note bad-note">{live.data.error}</p>}
      {sessions.length === 0 && !live.loading && (
        <p className="muted">Sessions appear here within a few seconds of playback starting.</p>
      )}

      <div className="session-list">
        {sessions.map((s) => (
          <SessionCard key={s.session_key} session={s} onChanged={live.reload} />
        ))}
      </div>
    </div>
  );
}

function SessionCard({ session, onChanged }: { session: LiveSession; onChanged: () => void }) {
  const [open, setOpen] = useState(false);
  const who = session.friendly_name || session.username || "Unknown";
  const where = session.geo
    ? [session.geo.city, session.geo.region].filter(Boolean).join(", ")
    : session.ip_address;
  const progress = Number(session.progress_percent ?? 0);

  return (
    <article className="session">
      <div className="session-main">
        <div>
          <h2>{session.full_title}</h2>
          <p className="muted">
            {who} · {session.player} ({session.platform}) · {session.transcode_decision}
            {session.video_full_resolution ? ` · ${session.video_full_resolution}` : ""}
          </p>
          <p className="muted small">
            {where}
            {session.geo?.is_hosting && (
              <span className="pill warn"> VPN / hosting: {session.geo.asn_org}</span>
            )}
            {session.location && <span className="pill"> {session.location}</span>}
            {session.state && <span className="pill"> {session.state}</span>}
          </p>
        </div>
        <button className="btn" onClick={() => setOpen((o) => !o)}>
          {open ? "Cancel" : "Stop stream"}
        </button>
      </div>

      <div className="progress" aria-hidden="true">
        <div className="progress-fill" style={{ width: `${Math.min(progress, 100)}%` }} />
      </div>

      {open && <StopForm session={session} onDone={() => { setOpen(false); onChanged(); }} />}
    </article>
  );
}

const DEFAULT_MESSAGE = "This device is not permitted to stream. Contact the server owner.";

function StopForm({ session, onDone }: { session: LiveSession; onDone: () => void }) {
  const [message, setMessage] = useState(DEFAULT_MESSAGE);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const plexPass = useIsAvailable("plex_pass");

  async function stop() {
    setBusy(true);
    setError(null);
    try {
      await api.post(`/activity/${session.session_key}/terminate`, { message });
      onDone();
    } catch (err) {
      setError((err as Error).message);
      setBusy(false);
    }
  }

  return (
    <div className="stop-form">
      <label>
        Message shown to the viewer
        <textarea rows={2} value={message} onChange={(e) => setMessage(e.target.value)} />
      </label>

      {/* Plex composes the on-screen text itself; only the middle is ours.
          Showing the whole thing avoids a round of "why does it say that". */}
      <div className="preview">
        <span className="preview-label">They will see</span>
        <p>
          <span className="fixed">Your Plex account name asked to stop your playback from this
          server: </span>
          <span className="ours">{message}</span>
          <span className="fixed"> {session.session_key}</span>
        </p>
        <small className="muted">
          Only the highlighted part is editable. Plex adds the rest and it can't be changed.
        </small>
      </div>

      {error && <p className="note bad-note">{error}</p>}

      <div className="row">
        <button className="btn danger" onClick={stop} disabled={busy || !plexPass.ok}>
          {busy ? "Stopping…" : `Stop ${session.friendly_name || session.username}'s stream`}
        </button>
        {!plexPass.ok && <span className="muted small">{plexPass.reason}</span>}
      </div>
    </div>
  );
}
