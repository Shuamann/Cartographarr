import { useState } from "react";
import { useNav } from "../lib/nav";
import { api, useApi, type PlexUser, type UserDetail } from "../lib/api";
import DataTable, { type Column, duration, when } from "../components/DataTable";

type Show = "all" | "current" | "deleted";

export default function UsersRoute({ focusUserId }: { focusUserId?: number | null }) {
  const nav = useNav();
  const users = useApi<PlexUser[]>("/users");
  const [selected, setSelected] = useState<number | null>(focusUserId ?? null);
  const [show, setShow] = useState<Show>("all");
  const [restoring, setRestoring] = useState<number | null>(null);
  const [error, setError] = useState<string | null>(null);

  async function restore(u: PlexUser) {
    const name = u.friendly_name || u.username;
    if (!confirm(`Restore ${name} in Tautulli? They go back into Tautulli's user list. History Tautulli erased when they were deleted does not come back.`)) return;
    setRestoring(u.user_id);
    setError(null);
    try {
      await api.post(`/users/${u.user_id}/restore-in-tautulli`);
      users.reload();
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setRestoring(null);
    }
  }

  const all = users.data ?? [];
  const deleted = all.filter((u) => u.deleted_in_tautulli).length;
  const rows = all.filter((u) =>
    show === "all" ? true : show === "deleted" ? u.deleted_in_tautulli : !u.deleted_in_tautulli,
  );

  const columns: Column<PlexUser>[] = [
    {
      key: "name",
      label: "User",
      sort: (u) => (u.friendly_name || u.username || String(u.user_id)).toLowerCase(),
      render: (u) => (
        <>
          {u.friendly_name || u.username || <span className="muted">Unknown account {u.user_id}</span>}
          {u.is_home_user && <span className="pill">home</span>}
          {!u.is_active && !u.deleted_in_tautulli && <span className="pill warn">inactive</span>}
          {u.deleted_in_tautulli && (
            <span
              className="pill warn"
              title={
                u.username
                  ? "Deleted from Tautulli's user list, so Tautulli hides them from its lists and dropdowns. Their history here is kept, and the Plex account may still have access."
                  : "Tautulli has no record of this account any more. Its history here is kept."
              }
            >
              {u.username ? "deleted in Tautulli" : "unknown to Tautulli"}
            </span>
          )}
          {u.email && <div className="muted small">{u.email}</div>}
        </>
      ),
    },
    {
      key: "plays",
      label: "Plays",
      numeric: true,
      sort: (u) => u.plays ?? 0,
      render: (u) => (u.plays ?? 0).toLocaleString(),
    },
    {
      key: "last_seen",
      label: "Last seen",
      numeric: true,
      sort: (u) => u.last_seen ?? 0,
      render: (u) => when(u.last_seen),
    },
    ...(nav.isAdmin
      ? [
          {
            key: "restore",
            label: "",
            render: (u: PlexUser) =>
              u.deleted_in_tautulli && u.username ? (
                <button
                  className="tab"
                  disabled={restoring === u.user_id}
                  onClick={(e) => {
                    e.stopPropagation();
                    restore(u);
                  }}
                >
                  {restoring === u.user_id ? "Restoring\u2026" : "Restore in Tautulli"}
                </button>
              ) : null,
          } as Column<PlexUser>,
        ]
      : []),
  ];

  return (
    <div className="pad scroll">
      <div className="row-between">
        <h1>Users</h1>
        <div className="segmented">
          {(
            [
              ["all", `All ${all.length}`],
              ["current", `Current ${all.length - deleted}`],
              ["deleted", `Deleted in Tautulli ${deleted}`],
            ] as [Show, string][]
          ).map(([value, label]) => (
            <button key={value} className={show === value ? "seg on" : "seg"} onClick={() => setShow(value)}>
              {label}
            </button>
          ))}
        </div>
      </div>
      <p className="muted small">
        Everyone who has had access to the Plex server, including anyone Tautulli has since
        deleted, so their history stays reachable. Separate from the accounts that sign in to
        Cartographarr.
      </p>

      {users.error && <p className="note bad-note">{users.error}</p>}
      {error && <p className="note bad-note">{error}</p>}

      <DataTable
        rows={rows}
        columns={columns}
        rowKey={(u) => u.user_id}
        initialSort="last_seen"
        onRowClick={(u) => setSelected(u.user_id === selected ? null : u.user_id)}
        isSelected={(u) => u.user_id === selected}
      />

      {selected !== null && <UserPanel userId={selected} onClose={() => setSelected(null)} />}
    </div>
  );
}

function UserPanel({ userId, onClose }: { userId: number; onClose: () => void }) {
  const detail = useApi<UserDetail>(`/users/${userId}`);

  if (detail.error) return <p className="note bad-note">{detail.error}</p>;
  if (!detail.data) return <p className="muted">Loading…</p>;

  const d = detail.data;

  return (
    <section className="editor">
      <div className="row-between">
        <h2>{d.friendly_name || d.username}</h2>
        <button className="tab" onClick={onClose}>
          Close
        </button>
      </div>

      <dl className="stats">
        <Stat label="Plays" value={d.totals.plays.toLocaleString()} />
        <Stat label="Watched" value={duration(d.totals.seconds)} />
        <Stat label="Devices" value={String(d.totals.devices)} />
        <Stat label="Addresses" value={String(d.totals.ips)} />
      </dl>
      <p className="muted small">
        First play {when(d.totals.first_play)}, last {when(d.totals.last_play)}.
      </p>

      <div className="dash-cols">
        <div>
          <h3>Where from</h3>
          <div className="mini-list">
            {d.places.map((p, i) => (
              <div key={i} className="mini">
                <div>
                  {[p.city, p.region, p.country].filter(Boolean).join(", ") || "Unknown"}
                  {p.is_hosting && <span className="pill warn">VPN</span>}
                  <p className="muted small">{p.asn_org}</p>
                </div>
                <span className="muted">{p.plays.toLocaleString()}</span>
              </div>
            ))}
          </div>
        </div>

        <div>
          <h3>Most watched</h3>
          <div className="mini-list">
            {d.top_media.map((m) => (
              <div key={m.rating_key} className="mini">
                <span>{m.title}</span>
                <span className="muted">{m.plays.toLocaleString()}</span>
              </div>
            ))}
          </div>
        </div>
      </div>

      <h3>Devices</h3>
      <div className="mini-list">
        {d.devices.map((dev) => (
          <div key={dev.machine_id} className="mini">
            <div>
              {dev.player || "Unnamed"}
              {dev.is_new_unreviewed && <span className="pill warn">new</span>}
              <p className="muted small">
                {dev.platform} · <code>{dev.machine_id.slice(0, 18)}…</code>
              </p>
            </div>
            <span className="muted">{dev.play_count.toLocaleString()} plays</span>
          </div>
        ))}
      </div>
    </section>
  );
}

function Stat({ label, value }: { label: string; value: string }) {
  return (
    <div className="stat">
      <dt>{label}</dt>
      <dd>{value}</dd>
    </div>
  );
}
