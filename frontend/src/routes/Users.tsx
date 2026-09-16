import { useState } from "react";
import { useApi, type PlexUser, type UserDetail } from "../lib/api";
import DataTable, { type Column, duration, when } from "../components/DataTable";

export default function UsersRoute() {
  const users = useApi<PlexUser[]>("/users");
  const [selected, setSelected] = useState<number | null>(null);

  const columns: Column<PlexUser>[] = [
    {
      key: "name",
      label: "User",
      sort: (u) => (u.friendly_name || u.username || "").toLowerCase(),
      render: (u) => (
        <>
          {u.friendly_name || u.username}
          {u.is_home_user && <span className="pill">home</span>}
          {!u.is_active && <span className="pill warn">inactive</span>}
          {u.email && <div className="muted small">{u.email}</div>}
        </>
      ),
    },
    {
      key: "last_seen",
      label: "Last seen",
      numeric: true,
      sort: (u) => u.last_seen ?? 0,
      render: (u) => when(u.last_seen),
    },
  ];

  return (
    <div className="pad scroll">
      <h1>Users</h1>
      <p className="muted small">
        People with access to the Plex server, from Tautulli. Separate from the accounts that sign
        in to Cartographarr.
      </p>

      {users.error && <p className="note bad-note">{users.error}</p>}

      <DataTable
        rows={users.data ?? []}
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
