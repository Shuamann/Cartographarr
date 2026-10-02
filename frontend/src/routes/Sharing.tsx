import { useState } from "react";
import Loading from "../components/Loading";
import { when } from "../components/DataTable";
import { api, useApi } from "../lib/api";
import { useNav } from "../lib/nav";

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
function Shares() {
  const shares = useApi<Shares>("/sharing");
  const [editing, setEditing] = useState<string | null>(null);
  const [draft, setDraft] = useState<string[]>([]);
  const [removing, setRemoving] = useState<Share | null>(null);
  const [confirm, setConfirm] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  if (shares.error) return <p className="note bad-note">{shares.error}</p>;
  if (!shares.data)
    return (
      <div>
        <Loading
          label="Asking Plex who the server is shared with"
          slowHint="Plex answers this for everyone at once. It is usually quick, but plex.tv can take a while."
        />
      </div>
    );

  if (!shares.data.configured) {
    return (
      <div>
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
    <div>
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

/* Sharing has two views. Who has access comes from Plex and can change it.
 * Access review comes from Tautulli and history, so it works without a Plex
 * token: who still uses what they were given. */
export default function SharingRoute() {
  const [view, setView] = useState<"shares" | "review">(() => {
    try {
      return localStorage.getItem("sharing.view") === "review" ? "review" : "shares";
    } catch {
      return "shares";
    }
  });
  function choose(v: "shares" | "review") {
    setView(v);
    try {
      localStorage.setItem("sharing.view", v);
    } catch {
      /* private window */
    }
  }
  return (
    <div className="pad scroll">
      <div className="row-between">
        <h1>Sharing</h1>
        <div className="segmented">
          <button className={view === "shares" ? "seg on" : "seg"} onClick={() => choose("shares")}>
            Who has access
          </button>
          <button className={view === "review" ? "seg on" : "seg"} onClick={() => choose("review")}>
            Access review
          </button>
        </div>
      </div>
      {view === "shares" ? <Shares /> : <AccessReview />}
    </div>
  );
}

type Reviewed = {
  user_id: number;
  name: string;
  username: string | null;
  email: string | null;
  home: boolean;
  active_in_tautulli: boolean;
  libraries: string[] | null;
  allow_sync: boolean | null;
  plays: number;
  recent_plays: number;
  last_play: number | null;
  idle_days: number | null;
  devices: number;
  addresses: number;
  banned_devices: number;
  status: "active" | "inactive" | "never" | "removed";
};

const STATUS: Record<Reviewed["status"], { label: string; tone: string }> = {
  inactive: { label: "Not watching", tone: "pill warn" },
  never: { label: "Never watched", tone: "pill warn" },
  active: { label: "Active", tone: "pill ok" },
  removed: { label: "Removed from Tautulli", tone: "pill" },
};

function AccessReview() {
  const nav = useNav();
  const data = useApi<{ inactive_days: number; people: Reviewed[] }>("/access-review");
  const [filter, setFilter] = useState<"all" | "attention">("attention");
  if (data.error) return <p className="note bad-note">{data.error}</p>;
  if (!data.data) return <Loading label="Reviewing who uses their access" />;
  const { inactive_days, people } = data.data;
  const attention = people.filter((p) => p.status === "inactive" || p.status === "never");
  const shown = filter === "all" ? people : attention;
  return (
    <>
      <p className="muted small">
        Everyone Tautulli knows about, what they can see, and whether they still use it. Not watching means no plays in
        {" "}
        {inactive_days} days (change this in Settings, People and privacy). Library lists come from Tautulli, so this works without a
        Plex token; change access from Who has access, or a person&apos;s Access tab.
      </p>
      <div className="row chips">
        <button className={filter === "attention" ? "chip on" : "chip"} onClick={() => setFilter("attention")}>
          Needs a look {attention.length}
        </button>
        <button className={filter === "all" ? "chip on" : "chip"} onClick={() => setFilter("all")}>
          Everyone {people.length}
        </button>
      </div>
      {shown.length === 0 && <p className="muted">Everyone with access is using it.</p>}
      <div className="mini-list">
        {shown.map((p) => (
          <div key={p.user_id} className="mini">
            <div className="min0">
              {nav.openUser ? (
                <button className="linkish" onClick={() => nav.openUser?.(p.user_id)}>
                  <strong>{p.name}</strong>
                </button>
              ) : (
                <strong>{p.name}</strong>
              )}{" "}
              <span className={STATUS[p.status].tone}>{STATUS[p.status].label}</span>
              {p.home && <span className="pill">home</span>}
              {p.banned_devices > 0 && (
                <span className="pill banned">
                  {p.banned_devices} banned device{p.banned_devices === 1 ? "" : "s"}
                </span>
              )}
              <p className="muted small">
                {p.last_play ? `Last watched ${when(p.last_play)} (${p.idle_days} days ago)` : "Has never played anything"}
                {` · ${p.plays.toLocaleString()} plays, ${p.recent_plays} recently · ${p.devices} devices`}
              </p>
              <p className="muted small">
                {p.libraries === null
                  ? "Libraries not known yet (next user sync)"
                  : p.libraries.length === 0
                    ? "No libraries shared"
                    : p.libraries.join(", ")}
              </p>
            </div>
          </div>
        ))}
      </div>
    </>
  );
}
