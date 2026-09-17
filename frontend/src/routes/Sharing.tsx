import { useState } from "react";
import Loading from "../components/Loading";
import { api, useApi } from "../lib/api";

type Share = {
  id: number;
  username: string;
  email: string | null;
  thumb: string | null;
  home: boolean;
  sections: string[];
};

type Shares = { configured: boolean; users: Share[]; sections: string[] };

/* Who the server is shared with.
 *
 * The only screen that changes anything outside this app, and the only one
 * whose changes cannot be undone from here. Unsharing needs a fresh invitation
 * that the other person accepts, so it asks for the username to be typed back
 * rather than settling for a yes.
 */
export default function SharingRoute() {
  const shares = useApi<Shares>("/sharing");
  const [editing, setEditing] = useState<string | null>(null);
  const [draft, setDraft] = useState<string[]>([]);
  const [removing, setRemoving] = useState<Share | null>(null);
  const [confirm, setConfirm] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  if (shares.error) return <div className="pad"><p className="note bad-note">{shares.error}</p></div>;
  if (!shares.data)
    return (
      <div className="pad">
        <h1>Sharing</h1>
        <Loading
          label="Asking Plex who the server is shared with"
          slowHint="Plex answers this for everyone at once. It is usually quick, but plex.tv can take a while."
        />
      </div>
    );

  if (!shares.data.configured) {
    return (
      <div className="pad">
        <h1>Sharing</h1>
        <p className="note warn-note">
          Add a Plex token in Settings to manage sharing. Everything else in Cartographarr goes
          through Tautulli, but changing who can see what has to talk to Plex directly.
        </p>
      </div>
    );
  }

  async function save(username: string) {
    setBusy(true);
    setError(null);
    try {
      await api.put(`/sharing/${encodeURIComponent(username)}/sections`, { sections: draft });
      setEditing(null);
      shares.reload();
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setBusy(false);
    }
  }

  async function remove() {
    if (!removing) return;
    setBusy(true);
    setError(null);
    try {
      await fetch(`/api/sharing/${encodeURIComponent(removing.username)}`, {
        method: "DELETE",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ confirm }),
      }).then(async (r) => {
        if (!r.ok) throw new Error((await r.json().catch(() => ({}))).detail ?? r.statusText);
      });
      setRemoving(null);
      setConfirm("");
      shares.reload();
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="pad scroll">
      <h1>Sharing</h1>
      <p className="muted small">
        Plex cannot block one device belonging to someone you share with, which is what the Rules
        page is for. What Plex can do is change which libraries a person sees, or stop sharing
        with them altogether.
      </p>

      {error && <p className="note bad-note">{error}</p>}

      <div className="mini-list">
        {shares.data.users.map((user) => (
          <div key={user.id ?? user.username} className={editing === user.username || removing?.username === user.username ? "share-row open" : "share-row"}>
            <div className="mini">
              <div className="min0">
                <strong>{user.username}</strong>
                {user.home && <span className="pill">home</span>}
                <p className="muted small">{user.email}</p>
                <p className="muted small">
                  {user.sections.length === 0 ? "No libraries shared" : user.sections.join(", ")}
                </p>
              </div>
              <div className="row">
                <button
                  className={editing === user.username ? "tab active" : "tab"}
                  aria-expanded={editing === user.username}
                  onClick={() => {
                    if (editing === user.username) return setEditing(null);
                    setEditing(user.username);
                    setRemoving(null);
                    setDraft(user.sections);
                    setError(null);
                  }}
                >
                  Libraries
                </button>
                <button
                  className="tab danger-text"
                  aria-expanded={removing?.username === user.username}
                  onClick={() => {
                    if (removing?.username === user.username) return setRemoving(null);
                    setRemoving(user);
                    setEditing(null);
                    setConfirm("");
                    setError(null);
                  }}
                >
                  Unshare
                </button>
              </div>
            </div>

            {editing === user.username && (
              <div className="share-panel">
                <h2>What {user.username} can see</h2>
                <div className="share-sections">
                  {shares.data!.sections.map((section) => (
                    <label key={section} className="check">
                      <input
                        type="checkbox"
                        checked={draft.includes(section)}
                        onChange={(e) =>
                          setDraft(e.target.checked ? [...draft, section] : draft.filter((x) => x !== section))
                        }
                      />
                      {section}
                    </label>
                  ))}
                </div>
                <p className="muted small">
                  Unticking everything leaves the share in place with nothing in it, which is different from unsharing.
                </p>
                <div className="row">
                  <button className="btn primary" onClick={() => save(user.username)} disabled={busy}>
                    {busy ? "Saving\u2026" : "Save"}
                  </button>
                  <button className="btn" onClick={() => setEditing(null)}>
                    Cancel
                  </button>
                </div>
              </div>
            )}

            {removing?.username === user.username && (
              <div className="share-panel danger-editor">
                <h2>Stop sharing with {user.username}?</h2>
                <p className="note warn-note">
                  This cannot be undone from here. Getting them back means sending a fresh invitation that they have to
                  accept. Their watch history stays in Cartographarr either way.
                </p>
                <label>
                  Type <strong>{user.username}</strong> to confirm
                  <input value={confirm} onChange={(e) => setConfirm(e.target.value)} autoFocus />
                </label>
                <div className="row">
                  <button className="btn danger" onClick={remove} disabled={busy || confirm.trim() !== user.username}>
                    {busy ? "Removing\u2026" : "Stop sharing"}
                  </button>
                  <button className="btn" onClick={() => setRemoving(null)}>
                    Cancel
                  </button>
                </div>
              </div>
            )}
          </div>
        ))}
      </div>
    </div>
  );
}
