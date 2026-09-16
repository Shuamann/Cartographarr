import { useState } from "react";
import { api, useApi, type AppUser, type Device, type PlexUser } from "../lib/api";
import DataTable, { type Column, when } from "../components/DataTable";

/* The device inventory.
 *
 * This replaces hunting for a machine_id by hand, which is what writing a block
 * rule used to mean. Copy it, or go straight to a pre-filled rule.
 */
export default function DevicesRoute({ me, onBlock }: { me: AppUser | null; onBlock: (d: Device) => void }) {
  const devices = useApi<Device[]>("/devices");
  const users = useApi<PlexUser[]>("/users");
  const [newOnly, setNewOnly] = useState(false);
  const [search, setSearch] = useState("");
  const [copied, setCopied] = useState<string | null>(null);

  const isAdmin = me?.role === "admin";
  const names = new Map((users.data ?? []).map((u) => [u.user_id, u.friendly_name || u.username]));

  const rows = (devices.data ?? []).filter((d) => {
    if (newOnly && !d.is_new_unreviewed) return false;
    if (!search.trim()) return true;
    const hay = `${d.player} ${d.platform} ${d.product} ${d.machine_id} ${names.get(d.user_id) ?? ""}`;
    return hay.toLowerCase().includes(search.trim().toLowerCase());
  });

  async function review(device: Device) {
    await api.post(`/devices/${encodeURIComponent(device.machine_id)}/review`).catch(() => {});
    devices.reload();
  }

  async function copy(machineId: string) {
    await navigator.clipboard?.writeText(machineId).catch(() => {});
    setCopied(machineId);
    setTimeout(() => setCopied(null), 1500);
  }

  const unreviewed = (devices.data ?? []).filter((d) => d.is_new_unreviewed).length;

  const columns: Column<Device>[] = [
    {
      key: "player",
      label: "Device",
      sort: (d) => (d.player ?? "").toLowerCase(),
      render: (d) => (
        <>
          {d.player || "Unnamed"}
          {d.is_new_unreviewed && <span className="pill warn">new</span>}
          <div className="muted small">
            {d.platform}
            {d.product ? ` · ${d.product}` : ""}
          </div>
        </>
      ),
    },
    {
      key: "user",
      label: "User",
      sort: (d) => (names.get(d.user_id) ?? "").toLowerCase(),
      render: (d) => names.get(d.user_id) ?? d.user_id,
    },
    {
      key: "machine_id",
      label: "Device ID",
      render: (d) => (
        <button className="idbtn" title="Copy" onClick={(e) => { e.stopPropagation(); copy(d.machine_id); }}>
          <code>{d.machine_id.slice(0, 18)}…</code>
          <span className="muted small">{copied === d.machine_id ? "copied" : "copy"}</span>
        </button>
      ),
    },
    { key: "play_count", label: "Plays", numeric: true, sort: (d) => d.play_count, render: (d) => d.play_count.toLocaleString() },
    { key: "first_seen", label: "First seen", numeric: true, sort: (d) => d.first_seen ?? 0, render: (d) => when(d.first_seen) },
    { key: "last_seen", label: "Last seen", numeric: true, sort: (d) => d.last_seen ?? 0, render: (d) => when(d.last_seen) },
    {
      key: "actions",
      label: "",
      render: (d) =>
        isAdmin ? (
          <div className="row">
            {d.is_new_unreviewed && (
              <button className="tab" onClick={(e) => { e.stopPropagation(); review(d); }}>
                Reviewed
              </button>
            )}
            <button className="tab danger-text" onClick={(e) => { e.stopPropagation(); onBlock(d); }}>
              Block
            </button>
          </div>
        ) : null,
    },
  ];

  return (
    <div className="pad scroll">
      <div className="row-between">
        <h1>Devices</h1>
        <div className="row">
          <input
            className="search"
            type="search"
            placeholder="Search devices…"
            value={search}
            onChange={(e) => setSearch(e.target.value)}
          />
          <button className={newOnly ? "ms-btn on" : "ms-btn"} onClick={() => setNewOnly(!newOnly)}>
            New only{unreviewed > 0 && <span className="ms-count">{unreviewed}</span>}
          </button>
        </div>
      </div>

      <p className="muted small">
        Rules match on the device ID, which survives a rename. The player name does not, so anyone
        can defeat a name-based rule by renaming their client.
      </p>

      {devices.error && <p className="note bad-note">{devices.error}</p>}

      <DataTable
        rows={rows}
        columns={columns}
        rowKey={(d) => `${d.machine_id}-${d.user_id}`}
        initialSort="last_seen"
        empty={newOnly ? "No unreviewed devices." : "No devices yet."}
      />
    </div>
  );
}
