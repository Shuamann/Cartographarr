import { useEffect, useMemo, useState } from "react";
import { duration, when } from "../components/DataTable";
import { StreamEntry } from "../components/EnforcementLog";
import StreamDetail from "../components/StreamDetail";
import SignalDetail from "../components/SignalDetail";
import {
  api,
  useApi,
  type Activity,
  type AddressDetail,
  type Device,
  type DeviceDetail,
  type HistoryPage,
  type PersonEvent,
  type PlexUser,
  type Profile,
  type UserDetail,
} from "../lib/api";
import { useNav } from "../lib/nav";
import type { PeopleFilter } from "../lib/tabs";
import { useBans } from "../lib/bans";

/* Users and their devices, in one place.
 *
 * A device belongs to a person and people are usually found through a device
 * or the other way round, so both live in one list: each user opens out to
 * their devices, and selecting either shows its profile beside the list.
 */

export type Selection =
  | { kind: "user"; id: number }
  | { kind: "device"; id: string }
  | { kind: "address"; id: string };

type Mode = "users" | "devices";
type Sort = "last_seen" | "plays" | "name";

export default function PeopleRoute({
  initial,
  onInitialUsed,
  initialFilter,
  onInitialFilterUsed,
}: {
  initial?: Selection | null;
  onInitialUsed?: () => void;
  initialFilter?: PeopleFilter | null;
  onInitialFilterUsed?: () => void;
}) {
  const users = useApi<PlexUser[]>("/users");
  const devices = useApi<Device[]>("/devices");
  const live = useApi<Activity>("/activity");

  const [mode, setMode] = useState<Mode>(initial?.kind === "device" ? "devices" : "users");
  const [selected, setSelected] = useState<Selection | null>(initial ?? null);
  const [expanded, setExpanded] = useState<Set<number>>(
    () => new Set(initial?.kind === "user" ? [initial.id] : []),
  );
  const [search, setSearch] = useState("");
  const [sort, setSort] = useState<Sort>("last_seen");
  const [onlyNew, setOnlyNew] = useState(false);
  const [onlyDeleted, setOnlyDeleted] = useState(false);
  const [onlyLive, setOnlyLive] = useState(false);
  const [onlyBanned, setOnlyBanned] = useState(false);
  const bans = useBans();

  // Opened from a dashboard card with a filter in mind. New devices live on
  // devices, so that one also switches the list to devices.
  useEffect(() => {
    if (!initialFilter) return;
    setOnlyNew(initialFilter === "new");
    setOnlyBanned(initialFilter === "banned");
    setOnlyDeleted(initialFilter === "deleted");
    setOnlyLive(initialFilter === "live");
    if (initialFilter === "new" || initialFilter === "banned") setMode("devices");
    onInitialFilterUsed?.();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [initialFilter]);

  // Opened on someone from elsewhere (a History row, a stream card). Applied
  // then cleared, so coming back to People later does not jump to them again.
  // Also covers a link followed from inside People itself.
  useEffect(() => {
    if (!initial) return;
    setSelected(initial);
    if (initial.kind !== "address") setMode(initial.kind === "device" ? "devices" : "users");
    if (initial.kind === "user") setExpanded((prev) => new Set([...prev, initial.id]));
    onInitialUsed?.();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [initial]);

  const liveUsers = useMemo(
    () => new Set((live.data?.sessions ?? []).map((s) => Number(s.user_id))),
    [live.data],
  );
  const liveDevices = useMemo(
    () => new Set((live.data?.sessions ?? []).map((s) => s.machine_id).filter(Boolean) as string[]),
    [live.data],
  );

  const names = useMemo(
    () => new Map((users.data ?? []).map((u) => [u.user_id, u.friendly_name || u.username || `Account ${u.user_id}`])),
    [users.data],
  );
  const devicesByUser = useMemo(() => {
    const out = new Map<number, Device[]>();
    for (const d of devices.data ?? []) {
      const list = out.get(d.user_id) ?? [];
      list.push(d);
      out.set(d.user_id, list);
    }
    return out;
  }, [devices.data]);

  const q = search.trim().toLowerCase();

  const userRows = (users.data ?? [])
    .filter((u) => {
      const own = devicesByUser.get(u.user_id) ?? [];
      if (onlyDeleted && !u.deleted_in_tautulli) return false;
      if (onlyLive && !liveUsers.has(u.user_id)) return false;
      if (onlyNew && !own.some((d) => d.is_new_unreviewed)) return false;
      if (onlyBanned && !own.some((d) => bans.ids.has(d.machine_id))) return false;
      if (!q) return true;
      // A search for a device finds its owner too.
      const hay = [u.username, u.friendly_name, u.email, String(u.user_id), ...own.flatMap((d) => [d.player, d.platform, d.machine_id])];
      return hay.some((h) => h && h.toLowerCase().includes(q));
    })
    .sort((a, b) =>
      sort === "plays"
        ? (b.plays ?? 0) - (a.plays ?? 0)
        : sort === "name"
          ? (names.get(a.user_id) ?? "").localeCompare(names.get(b.user_id) ?? "")
          : (b.last_seen ?? 0) - (a.last_seen ?? 0),
    );

  const deviceRows = (devices.data ?? [])
    .filter((d) => {
      if (onlyNew && !d.is_new_unreviewed) return false;
      if (onlyBanned && !bans.ids.has(d.machine_id)) return false;
      if (onlyLive && !liveDevices.has(d.machine_id)) return false;
      if (onlyDeleted && !(users.data ?? []).find((u) => u.user_id === d.user_id)?.deleted_in_tautulli) return false;
      if (!q) return true;
      const hay = [d.player, d.platform, d.product, d.machine_id, names.get(d.user_id)];
      return hay.some((h) => h && h.toLowerCase().includes(q));
    })
    .sort((a, b) =>
      sort === "plays"
        ? b.play_count - a.play_count
        : sort === "name"
          ? (a.player ?? "").localeCompare(b.player ?? "")
          : (b.last_seen ?? 0) - (a.last_seen ?? 0),
    );

  const newCount = (devices.data ?? []).filter((d) => d.is_new_unreviewed).length;
  const deletedCount = (users.data ?? []).filter((u) => u.deleted_in_tautulli).length;

  function toggle(userId: number) {
    const next = new Set(expanded);
    if (next.has(userId)) next.delete(userId);
    else next.add(userId);
    setExpanded(next);
  }

  function reload() {
    users.reload();
    devices.reload();
  }

  return (
    <div className="people">
      <aside className="people-list">
        <div className="people-tools">
          <input
            className="search"
            type="search"
            placeholder="Search people, devices, ids"
            value={search}
            onChange={(e) => setSearch(e.target.value)}
          />
          <div className="row-between">
            <div className="segmented">
              <button className={mode === "users" ? "seg on" : "seg"} onClick={() => setMode("users")}>
                Users {users.data?.length ?? ""}
              </button>
              <button className={mode === "devices" ? "seg on" : "seg"} onClick={() => setMode("devices")}>
                Devices {devices.data?.length ?? ""}
              </button>
            </div>
            <select value={sort} onChange={(e) => setSort(e.target.value as Sort)} aria-label="Sort">
              <option value="last_seen">Last seen</option>
              <option value="plays">Plays</option>
              <option value="name">Name</option>
            </select>
          </div>
          <div className="row chips">
            <button className={onlyLive ? "chip on" : "chip"} onClick={() => setOnlyLive(!onlyLive)}>
              Streaming now {liveUsers.size || ""}
            </button>
            <button className={onlyNew ? "chip on" : "chip"} onClick={() => setOnlyNew(!onlyNew)}>
              New devices {newCount || ""}
            </button>
            <button className={onlyBanned ? "chip on banned" : "chip banned"} onClick={() => setOnlyBanned(!onlyBanned)}>
              Banned {bans.ids.size || ""}
            </button>
            <button className={onlyDeleted ? "chip on" : "chip"} onClick={() => setOnlyDeleted(!onlyDeleted)}>
              Deleted in Tautulli {deletedCount || ""}
            </button>
          </div>
        </div>

        {(users.error || devices.error) && <p className="note bad-note">{users.error || devices.error}</p>}

        <div className="people-rows">
          {mode === "users" &&
            userRows.map((u) => {
              const own = (devicesByUser.get(u.user_id) ?? []).slice().sort((a, b) => (b.last_seen ?? 0) - (a.last_seen ?? 0));
              const open = expanded.has(u.user_id);
              const isSel = selected?.kind === "user" && selected.id === u.user_id;
              const newOwn = own.filter((d) => d.is_new_unreviewed).length;
              const bannedOwn = own.filter((d) => bans.ids.has(d.machine_id)).length;
              return (
                <div key={u.user_id} className="person">
                  <div className={isSel ? "person-row on" : "person-row"}>
                    <button
                      className="person-caret"
                      aria-label={open ? "Hide devices" : "Show devices"}
                      onClick={() => toggle(u.user_id)}
                      disabled={own.length === 0}
                    >
                      {own.length ? (open ? "▾" : "▸") : ""}
                    </button>
                    <button className="person-main" onClick={() => setSelected({ kind: "user", id: u.user_id })}>
                      <span className="person-name clip">
                        {liveUsers.has(u.user_id) && <span className="live-dot" title="Streaming now" />}
                        {names.get(u.user_id)}
                      </span>
                      <span className="person-meta muted small">
                        {(u.plays ?? 0).toLocaleString()} plays · {ago(u.last_seen)}
                      </span>
                      <span className="person-pills">
                        {bannedOwn > 0 && <span className="pill banned">{bannedOwn} banned</span>}
                        {newOwn > 0 && <span className="pill warn">{newOwn} new</span>}
                        {u.deleted_in_tautulli && <span className="pill warn">deleted</span>}
                        {u.is_home_user && <span className="pill">home</span>}
                      </span>
                    </button>
                  </div>
                  {open &&
                    own.map((d) => {
                      const devSel = selected?.kind === "device" && selected.id === d.machine_id;
                      return (
                        <button
                          key={`${d.machine_id}-${d.user_id}`}
                          className={devSel ? "device-row on" : "device-row"}
                          onClick={() => setSelected({ kind: "device", id: d.machine_id })}
                        >
                          <span className="clip">
                            {liveDevices.has(d.machine_id) && <span className="live-dot" title="Streaming now" />}
                            {d.player || "Unnamed"} <span className="muted small">{d.platform}</span>
                          </span>
                          <span className="muted small">
                            {d.play_count.toLocaleString()} · {ago(d.last_seen)}
                          </span>
                          {bans.ids.has(d.machine_id) && <span className="pill banned">banned</span>}
                          {d.is_new_unreviewed && <span className="pill warn">new</span>}
                        </button>
                      );
                    })}
                </div>
              );
            })}

          {mode === "devices" &&
            deviceRows.map((d) => {
              const devSel = selected?.kind === "device" && selected.id === d.machine_id;
              return (
                <button
                  key={`${d.machine_id}-${d.user_id}`}
                  className={devSel ? "device-row flat on" : "device-row flat"}
                  onClick={() => setSelected({ kind: "device", id: d.machine_id })}
                >
                  <span className="clip">
                    {liveDevices.has(d.machine_id) && <span className="live-dot" title="Streaming now" />}
                    {d.player || "Unnamed"} <span className="muted small">{d.platform}</span>
                    <span className="muted small person-owner">{names.get(d.user_id) ?? d.user_id}</span>
                  </span>
                  <span className="muted small">
                    {d.play_count.toLocaleString()} · {ago(d.last_seen)}
                  </span>
                  {bans.ids.has(d.machine_id) && <span className="pill banned">banned</span>}
                  {d.is_new_unreviewed && <span className="pill warn">new</span>}
                </button>
              );
            })}

          {mode === "users" && users.data && userRows.length === 0 && <p className="muted pad-s">Nobody matches.</p>}
          {mode === "devices" && devices.data && deviceRows.length === 0 && <p className="muted pad-s">No device matches.</p>}
        </div>
      </aside>

      <section className="people-pane">
        {!selected && (
          <div className="people-empty muted">
            <p>Choose a user or a device to see everything about them.</p>
          </div>
        )}
        {selected?.kind === "user" && (
          <UserProfile
            key={`u-${selected.id}`}
            userId={selected.id}
            live={live.data}
            onSelectDevice={(id) => setSelected({ kind: "device", id })}
            onChanged={reload}
          />
        )}
        {selected?.kind === "address" && (
          <AddressProfile
            key={`a-${selected.id}`}
            ip={selected.id}
            onSelectUser={(id) => {
              setSelected({ kind: "user", id });
              setExpanded(new Set([...expanded, id]));
            }}
            onSelectDevice={(id) => setSelected({ kind: "device", id })}
          />
        )}
        {selected?.kind === "device" && (
          <DeviceProfile
            key={`d-${selected.id}`}
            machineId={selected.id}
            live={live.data}
            onSelectUser={(id) => {
              setSelected({ kind: "user", id });
              setExpanded(new Set([...expanded, id]));
            }}
            onChanged={reload}
          />
        )}
      </section>
    </div>
  );
}

// ---- user ----------------------------------------------------------------------

type Tab = "overview" | "users" | "history" | "places" | "devices" | "activity" | "access";

function UserProfile({
  userId,
  live,
  onSelectDevice,
  onChanged,
}: {
  userId: number;
  live?: Activity;
  onSelectDevice: (machineId: string) => void;
  onChanged: () => void;
}) {
  const nav = useNav();
  const detail = useApi<UserDetail>(`/users/${userId}`);
  const [tab, setTab] = useState<Tab>("overview");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  if (detail.error) return <p className="note bad-note pad">{detail.error}</p>;
  if (!detail.data) return <p className="muted pad">Loading…</p>;
  const u = detail.data;
  const name = u.friendly_name || u.username || `Account ${u.user_id}`;
  const streaming = (live?.sessions ?? []).filter((s) => Number(s.user_id) === userId);

  async function restore() {
    if (!confirm(`Restore ${name} in Tautulli? History Tautulli erased when they were deleted does not come back.`)) return;
    setBusy(true);
    setError(null);
    try {
      await api.post(`/users/${userId}/restore-in-tautulli`);
      detail.reload();
      onChanged();
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setBusy(false);
    }
  }

  const tabs: [Tab, string][] = [
    ["overview", "Overview"],
    ["history", "History"],
    ["places", `Places ${u.places.length}`],
    ["devices", `Devices ${u.devices.length}`],
    ["activity", "Activity"],
    ...(nav.isAdmin ? ([["access", "Access"]] as [Tab, string][]) : []),
  ];

  return (
    <div className="profile">
      <header className="profile-head">
        <div className="min0">
          <h1 className="clip">
            {streaming.length > 0 && <span className="live-dot" title="Streaming now" />}
            {name}
          </h1>
          <p className="muted small">
            {[u.username && u.username !== name ? u.username : null, u.email, `id ${u.user_id}`].filter(Boolean).join(" · ")}
          </p>
          <div className="row person-pills">
            {u.is_home_user && <span className="pill">home user</span>}
            {!u.is_active && !u.deleted_in_tautulli && <span className="pill warn">inactive</span>}
            {u.deleted_in_tautulli && (
              <span className="pill warn">{u.username ? "deleted in Tautulli" : "unknown to Tautulli"}</span>
            )}
          </div>
        </div>
        <div className="row wrap profile-actions">
          {nav.filterTo && (
            <>
              <button className="btn" onClick={() => nav.filterTo?.("Map", { user_id: [userId] })}>
                Map
              </button>
              <button className="btn" onClick={() => nav.filterTo?.("History", { user_id: [userId] })}>
                History
              </button>
            </>
          )}
          {nav.isAdmin && u.deleted_in_tautulli && u.username && (
            <button className="btn" onClick={restore} disabled={busy}>
              {busy ? "Restoring…" : "Restore in Tautulli"}
            </button>
          )}
        </div>
      </header>
      {error && <p className="note bad-note">{error}</p>}

      <nav className="profile-tabs segmented">
        {tabs.map(([value, label]) => (
          <button key={value} className={tab === value ? "seg on" : "seg"} onClick={() => setTab(value)}>
            {label}
          </button>
        ))}
      </nav>

      <div className="profile-body">
        {tab === "overview" && (
          <>
            {streaming.map((s) => (
              <StreamDetail key={s.session_key} session={s} compact />
            ))}
            <Overview profile={u} extra={[["Devices", String(u.devices.length)]]} />
          </>
        )}
        {tab === "history" && <RecentPlays query={`user_id=${userId}`} onOpenAll={() => nav.filterTo?.("History", { user_id: [userId] })} showDevice />}
        {tab === "places" && <Places profile={u} onMap={() => nav.filterTo?.("Map", { user_id: [userId] })} />}
        {tab === "devices" && (
          <div className="mini-list">
            {u.devices.length === 0 && <p className="muted">No devices recorded.</p>}
            {u.devices.map((d) => (
              <button key={d.machine_id} className="mini mini-button" onClick={() => onSelectDevice(d.machine_id)}>
                <div className="min0">
                  <strong>{d.player || "Unnamed"}</strong>
                  {d.is_new_unreviewed && <span className="pill warn">new</span>}
                  {(live?.sessions ?? []).some((s) => s.machine_id === d.machine_id) && <span className="pill ok">streaming</span>}
                  <p className="muted small">
                    {[d.platform, d.product].filter(Boolean).join(" · ")} · first {when(d.first_seen)} · last {ago(d.last_seen)}
                  </p>
                </div>
                <span className="muted">{d.play_count.toLocaleString()} plays</span>
              </button>
            ))}
          </div>
        )}
        {tab === "activity" && <ActivityList query={`user_id=${userId}`} />}
        {tab === "access" && <Access username={u.username} />}
      </div>
    </div>
  );
}

// ---- device --------------------------------------------------------------------

function DeviceProfile({
  machineId,
  live,
  onSelectUser,
  onChanged,
}: {
  machineId: string;
  live?: Activity;
  onSelectUser: (userId: number) => void;
  onChanged: () => void;
}) {
  const nav = useNav();
  const bans = useBans();
  const detail = useApi<DeviceDetail>(`/devices/${encodeURIComponent(machineId)}`);
  const [tab, setTab] = useState<Tab>("overview");
  const [copied, setCopied] = useState(false);

  if (detail.error) return <p className="note bad-note pad">{detail.error}</p>;
  if (!detail.data) return <p className="muted pad">Loading…</p>;
  const d = detail.data;
  const label = d.player || machineId.slice(0, 12);
  const streaming = (live?.sessions ?? []).filter((s) => s.machine_id === machineId);

  async function review() {
    await api.post(`/devices/${encodeURIComponent(machineId)}/review`).catch(() => {});
    detail.reload();
    onChanged();
  }

  async function copy() {
    await navigator.clipboard?.writeText(machineId).catch(() => {});
    setCopied(true);
    setTimeout(() => setCopied(false), 1500);
  }

  const tabs: [Tab, string][] = [
    ["overview", "Overview"],
    ["users", `Users ${d.owners.length}`],
    ["history", "History"],
    ["places", `Places ${d.places.length}`],
    ["activity", "Activity"],
  ];

  return (
    <div className="profile">
      <header className="profile-head">
        <div className="min0">
          <h1 className="clip">
            {streaming.length > 0 && <span className="live-dot" title="Streaming now" />}
            {label}
          </h1>
          <p className="muted small">{[d.platform, d.product].filter(Boolean).join(" · ")}</p>
          <div className="row person-pills">
            {bans.ids.has(machineId) && (
              <span className="pill banned" title={banInfo(bans.list.find((b) => b.machine_id === machineId))}>
                banned
              </span>
            )}
            {d.is_new_unreviewed && <span className="pill warn">new, not reviewed</span>}
            {d.owners.length > 1 && <span className="pill warn">used by {d.owners.length} accounts</span>}
            <button className="idbtn" title="Copy the device id" onClick={copy}>
              <code className="small">{machineId}</code>
              <span className="muted small">{copied ? "copied" : "copy"}</span>
            </button>
          </div>
        </div>
        <div className="row wrap profile-actions">
          {nav.filterTo && (
            <>
              <button className="btn" onClick={() => nav.filterTo?.("Map", { machine_id: [machineId], machineLabel: label })}>
                Map
              </button>
              <button className="btn" onClick={() => nav.filterTo?.("History", { machine_id: [machineId], machineLabel: label })}>
                History
              </button>
            </>
          )}
          {nav.isAdmin && d.is_new_unreviewed && (
            <button className="btn" onClick={review}>
              Mark reviewed
            </button>
          )}
          {nav.blockDevice && !bans.ids.has(machineId) && (
            <button className="btn danger" onClick={() => nav.blockDevice?.(machineId, label)}>
              Ban device
            </button>
          )}
          {nav.unbanDevice && bans.ids.has(machineId) && (
            <button className="btn" onClick={() => nav.unbanDevice?.(machineId, label)}>
              Unban device
            </button>
          )}
        </div>
      </header>

      <nav className="profile-tabs segmented">
        {tabs.map(([value, text]) => (
          <button key={value} className={tab === value ? "seg on" : "seg"} onClick={() => setTab(value)}>
            {text}
          </button>
        ))}
      </nav>

      <div className="profile-body">
        {tab === "overview" && (
          <>
            {streaming.map((s) => (
              <StreamDetail key={s.session_key} session={s} compact />
            ))}
            <section className="profile-section">
              <h3>{d.owners.length > 1 ? "Accounts on this device" : "Account"}</h3>
              <div className="mini-list">
                {d.owners.map((o) => (
                  <button key={o.user_id} className="mini mini-button" onClick={() => onSelectUser(o.user_id)}>
                    <span>{o.name}</span>
                    <span className="muted small">
                      {o.play_count.toLocaleString()} plays · first {when(o.first_seen)} · last {ago(o.last_seen)}
                    </span>
                  </button>
                ))}
              </div>
            </section>
            <Overview profile={d} extra={[["First seen", when(d.first_seen)]]} />
          </>
        )}
        {tab === "users" && (
          <>
            <p className="muted small">
              Every account that has signed in to or used this device, most recent first.
              {d.owners.length > 1 && " More than one account on a single device can be a household, or a shared login."}
            </p>
            <div className="device-users">
              {d.owners.map((o) => {
                const streaming = (live?.sessions ?? []).some(
                  (x) => x.machine_id === machineId && Number(x.user_id) === o.user_id,
                );
                return (
                  <section key={o.user_id} className="device-user">
                    <div className="row-between">
                      <button className="linkish device-user-name" onClick={() => onSelectUser(o.user_id)}>
                        {streaming && <span className="live-dot" title="Streaming on this device now" />}
                        {o.name}
                      </button>
                      <span className="row person-pills">
                        {o.deleted_in_tautulli && <span className="pill warn">deleted in Tautulli</span>}
                        {streaming && <span className="pill ok">streaming now</span>}
                      </span>
                    </div>
                    <dl className="spec">
                      <dt>Plays</dt>
                      <dd>
                        {o.play_count.toLocaleString()} · {duration(o.seconds)} watched
                      </dd>
                      <dt>First used</dt>
                      <dd>{when(o.first_seen)}</dd>
                      <dt>Last used</dt>
                      <dd>
                        {when(o.last_seen)} <span className="muted small">({ago(o.last_seen)})</span>
                      </dd>
                      <dt>Last watched</dt>
                      <dd>{o.last_watched?.title ?? "Unknown"}</dd>
                      <dt>From</dt>
                      <dd>
                        {o.places.length === 0
                          ? "No located plays"
                          : o.places.map((x, i) => (
                              <span key={i} className="pill">
                                {[x.city, x.region].filter(Boolean).join(", ") || x.country || "Unknown"} {x.plays}
                                {x.is_hosting ? " VPN" : ""}
                              </span>
                            ))}
                      </dd>
                      <dt>Addresses</dt>
                      <dd>{o.addresses}</dd>
                    </dl>
                  </section>
                );
              })}
            </div>
          </>
        )}
        {tab === "history" && (
          <RecentPlays
            query={`machine_id=${encodeURIComponent(machineId)}`}
            onOpenAll={() => nav.filterTo?.("History", { machine_id: [machineId], machineLabel: label })}
            showUser
          />
        )}
        {tab === "places" && <Places profile={d} onMap={() => nav.filterTo?.("Map", { machine_id: [machineId], machineLabel: label })} />}
        {tab === "activity" && <ActivityList query={`machine_id=${encodeURIComponent(machineId)}`} />}
      </div>
    </div>
  );
}

// ---- address -------------------------------------------------------------------

function AddressProfile({
  ip,
  onSelectUser,
  onSelectDevice,
}: {
  ip: string;
  onSelectUser: (userId: number) => void;
  onSelectDevice: (machineId: string) => void;
}) {
  const nav = useNav();
  const detail = useApi<AddressDetail>(`/addresses/${encodeURIComponent(ip)}`);
  const [tab, setTab] = useState<"overview" | "history">("overview");

  if (detail.error) return <p className="note bad-note pad">{detail.error}</p>;
  if (!detail.data) return <p className="muted pad">Loading…</p>;
  const a = detail.data;
  const where = a.place ? [a.place.city, a.place.region, a.place.country].filter(Boolean).join(", ") : "";

  return (
    <div className="profile">
      <header className="profile-head">
        <div className="min0">
          <h1 className="clip">
            <code>{ip}</code>
          </h1>
          <p className="muted small">
            {[where || null, a.place?.asn_org, a.place?.asn ? `AS${a.place.asn}` : null].filter(Boolean).join(" · ") ||
              "No location for this address"}
          </p>
          <div className="row person-pills">
            {a.place?.is_hosting && <span className="pill vpn">VPN or hosting</span>}
            {a.place?.is_private && <span className="pill">local network</span>}
            {a.place?.accuracy_km ? <span className="pill">±{a.place.accuracy_km} km</span> : null}
            {a.accounts.length > 1 && <span className="pill warn">used by {a.accounts.length} accounts</span>}
          </div>
        </div>
        <div className="row wrap profile-actions">
          {nav.filterTo && (
            <>
              <button className="btn" onClick={() => nav.filterTo?.("Map", { ip_address: [ip] })}>
                Map
              </button>
              <button className="btn" onClick={() => nav.filterTo?.("History", { ip_address: [ip] })}>
                History
              </button>
            </>
          )}
        </div>
      </header>

      <nav className="profile-tabs segmented">
        <button className={tab === "overview" ? "seg on" : "seg"} onClick={() => setTab("overview")}>
          Overview
        </button>
        <button className={tab === "history" ? "seg on" : "seg"} onClick={() => setTab("history")}>
          History
        </button>
      </nav>

      <div className="profile-body">
        {tab === "overview" && (
          <>
            <dl className="stats">
              <Stat label="Plays" value={a.totals.plays.toLocaleString()} />
              <Stat label="Watched" value={duration(a.totals.seconds)} />
              <Stat label="Accounts" value={String(a.accounts.length)} />
              <Stat label="Devices" value={String(a.devices.length)} />
            </dl>
            <p className="muted small">
              First play {when(a.totals.first_play)}, last {when(a.totals.last_play)}.
            </p>
            <div className="dash-cols">
              <section className="profile-section">
                <h3>Accounts</h3>
                <div className="mini-list">
                  {a.accounts.map((u) => (
                    <button key={u.user_id} className="mini mini-button" onClick={() => onSelectUser(u.user_id)}>
                      <div className="min0">
                        <span>{u.name}</span>
                        <p className="muted small">
                          {duration(u.seconds)} · first {when(u.first_play)} · last {ago(u.last_play)}
                        </p>
                      </div>
                      <span className="muted">{u.plays.toLocaleString()}</span>
                    </button>
                  ))}
                </div>
              </section>
              <section className="profile-section">
                <h3>Devices</h3>
                <div className="mini-list">
                  {a.devices.length === 0 && <p className="muted">No devices recorded.</p>}
                  {a.devices.map((d) => (
                    <button key={d.machine_id} className="mini mini-button" onClick={() => onSelectDevice(d.machine_id)}>
                      <div className="min0">
                        <span>{d.player || "Unnamed"}</span>
                        <p className="muted small">
                          {[d.platform, d.user_name].filter(Boolean).join(" · ")} · last {ago(d.last_play)}
                        </p>
                      </div>
                      <span className="muted">{d.plays.toLocaleString()}</span>
                    </button>
                  ))}
                </div>
              </section>
            </div>
            <section className="profile-section">
              <h3>Most watched from here</h3>
              <div className="mini-list">
                {a.top_media.map((m) => (
                  <div key={m.rating_key} className="mini">
                    <span className="clip">{m.title ?? "Unknown"}</span>
                    <span className="muted">{m.plays.toLocaleString()}</span>
                  </div>
                ))}
              </div>
            </section>
          </>
        )}
        {tab === "history" && (
          <RecentPlays
            query={`ip_address=${encodeURIComponent(ip)}`}
            onOpenAll={() => nav.filterTo?.("History", { ip_address: [ip] })}
            showUser
            showDevice
          />
        )}
      </div>
    </div>
  );
}

// ---- shared sections -----------------------------------------------------------

function Overview({ profile: p, extra = [] }: { profile: Profile; extra?: [string, string][] }) {
  const vpn = p.addresses.filter((a) => a.is_hosting).length;
  return (
    <>
      <dl className="stats">
        <Stat label="Plays" value={p.totals.plays.toLocaleString()} />
        <Stat label="Watched" value={duration(p.totals.seconds)} />
        <Stat label="Addresses" value={String(p.totals.ips)} />
        <Stat label="Places" value={String(p.places.length)} />
        {extra.map(([label, value]) => (
          <Stat key={label} label={label} value={value} />
        ))}
      </dl>
      <p className="muted small">
        First play {when(p.totals.first_play)}, last {when(p.totals.last_play)}.
        {vpn > 0 && <span className="pill vpn">{vpn} VPN or hosting address{vpn === 1 ? "" : "es"}</span>}
      </p>

      <div className="dash-cols">
        <section className="profile-section">
          <h3>Most watched</h3>
          <div className="mini-list">
            {p.top_media.length === 0 && <p className="muted">Nothing yet.</p>}
            {p.top_media.map((m) => (
              <div key={m.rating_key} className="mini">
                <div className="min0">
                  <span className="clip">{m.title ?? "Unknown"}</span>
                  <p className="muted small">
                    {m.media_type} · {duration(m.seconds)} · last {ago(m.last_play)}
                  </p>
                </div>
                <span className="muted">{m.plays.toLocaleString()}</span>
              </div>
            ))}
          </div>
        </section>
        <section className="profile-section">
          <h3>Where from</h3>
          <PlaceList places={p.places.slice(0, 6)} />
        </section>
      </div>
    </>
  );
}

function Places({ profile: p, onMap }: { profile: Profile; onMap: () => void }) {
  const nav = useNav();
  return (
    <>
      <div className="row-between">
        <h3>Places</h3>
        <button className="btn" onClick={onMap}>
          Show on map
        </button>
      </div>
      <PlaceList places={p.places} />

      <h3 className="profile-subhead">Addresses</h3>
      <div className="mini-list">
        {p.addresses.map((a) => (
          <div key={a.ip_address} className="mini">
            <div className="min0">
              {nav.openAddress ? (
                <button className="linkish" onClick={() => nav.openAddress?.(a.ip_address)}>
                  <code>{a.ip_address}</code>
                </button>
              ) : (
                <code>{a.ip_address}</code>
              )}
              {a.location && <span className="pill">{a.location.toUpperCase()}</span>}
              {a.is_hosting && <span className="pill vpn">VPN</span>}
              <p className="muted small">
                {[a.asn_org, a.city].filter(Boolean).join(" · ") || "Unknown network"} · first {when(a.first_play)} · last {ago(a.last_play)}
              </p>
            </div>
            <span className="muted">{a.plays.toLocaleString()}</span>
          </div>
        ))}
      </div>
    </>
  );
}

function PlaceList({ places }: { places: Profile["places"] }) {
  if (places.length === 0) return <p className="muted">No located plays.</p>;
  return (
    <div className="mini-list">
      {places.map((x, i) => (
        <div key={i} className="mini">
          <div className="min0">
            <span className="clip">{[x.city, x.region, x.country].filter(Boolean).join(", ") || "Unknown"}</span>
            {x.is_hosting && <span className="pill vpn">VPN</span>}
            <p className="muted small">last {ago(x.last_play)}</p>
          </div>
          <span className="muted">{x.plays.toLocaleString()}</span>
        </div>
      ))}
    </div>
  );
}

function RecentPlays({
  query,
  onOpenAll,
  showUser,
  showDevice,
}: {
  query: string;
  onOpenAll: () => void;
  showUser?: boolean;
  showDevice?: boolean;
}) {
  const nav = useNav();
  const page = useApi<HistoryPage>(`/history?${query}&size=40`);
  const users = useApi<PlexUser[]>(showUser ? "/users" : null);
  const names = new Map((users.data ?? []).map((u) => [u.user_id, u.friendly_name || u.username]));

  if (page.error) return <p className="note bad-note">{page.error}</p>;
  if (!page.data) return <p className="muted">Loading…</p>;

  return (
    <>
      <div className="row-between">
        <h3>Latest {page.data.items.length} of {page.data.total.toLocaleString()} plays</h3>
        <button className="btn" onClick={onOpenAll}>
          Open in History
        </button>
      </div>
      <div className="mini-list">
        {page.data.items.map((h) => (
          <div key={h.row_id} className="mini">
            <div className="min0">
              <span className="clip">{h.full_title}</span>
              <p className="muted small">
                {when(h.started)}
                {showUser && h.user_id != null && (
                  <>
                    {" · "}
                    {nav.openUser ? (
                      <button className="linkish" onClick={() => nav.openUser?.(h.user_id as number)}>
                        {names.get(h.user_id) ?? h.user_id}
                      </button>
                    ) : (
                      names.get(h.user_id) ?? h.user_id
                    )}
                  </>
                )}
                {showDevice && h.player && (
                  <>
                    {" · "}
                    {nav.openDevice && h.machine_id ? (
                      <button className="linkish" onClick={() => nav.openDevice?.(h.machine_id as string)}>
                        {h.player}
                      </button>
                    ) : (
                      h.player
                    )}
                  </>
                )}
                {h.transcode_decision ? ` · ${h.transcode_decision}` : ""}
              </p>
            </div>
            <span className="muted small">{h.percent_complete != null ? `${h.percent_complete}%` : ""}</span>
          </div>
        ))}
      </div>
    </>
  );
}

function ActivityList({ query }: { query: string }) {
  const nav = useNav();
  const events = useApi<PersonEvent[]>(`/people/activity?${query}`);
  const [open, setOpen] = useState<string | null>(null);

  if (events.error) return <p className="note bad-note">{events.error}</p>;
  if (!events.data) return <p className="muted">Loading…</p>;

  return (
    <>
      <p className="muted small">
        Sharing signals{nav.isAdmin ? ", streams rules or people stopped, and changes made about them" : ""}, newest first.
      </p>
      {events.data.length === 0 && <p className="muted">Nothing has happened here.</p>}
      <div className="log-list">
        {events.data.map((e) => {
          const key = `${e.kind}-${e.id}`;
          if (e.kind === "stream") {
            return (
              <StreamEntry
                key={key}
                entry={e}
                open={open === key}
                onToggle={() => setOpen(open === key ? null : key)}
                onOpenUser={nav.openUser}
              />
            );
          }
          if (e.kind === "signal") {
            return (
              <article key={key} className={open === key ? "log-entry open" : "log-entry"}>
                <button className="log-summary signal-summary" onClick={() => setOpen(open === key ? null : key)} aria-expanded={open === key}>
                  <span className="log-when muted small">{when(e.at_epoch)}</span>
                  <span className="log-what clip">
                    <strong>{e.signal_kind === "concurrent" ? "Two places at once" : "Impossible travel"}</strong>
                    <span className="muted small clip">
                      {[e.from_city, e.to_city].filter(Boolean).join(" to ")}
                      {e.km != null ? ` \u00b7 ${Math.round(e.km).toLocaleString()} km` : ""}
                      {e.kmh != null && e.signal_kind === "travel" ? ` \u00b7 ${Math.round(e.kmh).toLocaleString()} km/h` : ""}
                    </span>
                  </span>
                  <span className="log-result">
                    <span className={e.status === "new" ? "pill warn" : "pill"}>{e.status}</span>
                  </span>
                  <span className="log-caret" aria-hidden="true">
                    {open === key ? "\u25b4" : "\u25be"}
                  </span>
                </button>
                {open === key && (
                  <div className="log-detail">
                    <div className="min0">
                      <SignalDetail id={e.id} onChanged={events.reload} />
                    </div>
                  </div>
                )}
              </article>
            );
          }
          return (
            <div key={key} className="mini event">
              <div className="min0">
                <strong>{e.summary ?? e.action}</strong>
                <p className="muted small">
                  {e.actor ?? "Unknown"} · {when(e.at_epoch)}
                </p>
              </div>
              <span className={e.result && e.result !== "ok" && e.result !== "removed" ? "pill bad" : "pill"}>change</span>
            </div>
          );
        })}
      </div>
    </>
  );
}

type Share = { username: string; sections: string[]; home: boolean };

function Access({ username }: { username: string | null }) {
  const shares = useApi<{ configured: boolean; users: Share[]; sections: string[] }>("/sharing");

  if (shares.error) return <p className="note bad-note">{shares.error}</p>;
  if (!shares.data) return <p className="muted">Asking Plex…</p>;
  if (!shares.data.configured) {
    return <p className="note warn-note">Add a Plex token in Settings to see which libraries are shared.</p>;
  }
  const share = shares.data.users.find((s) => s.username === username);
  if (!share) {
    return (
      <p className="note warn-note">
        Plex is not sharing this server with {username ?? "this account"}. They may have been removed, or they
        use a Plex Home or guest account.
      </p>
    );
  }
  return (
    <>
      <h3>Shared libraries</h3>
      <div className="row wrap chips">
        {shares.data.sections.map((section) => (
          <span key={section} className={share.sections.includes(section) ? "chip on" : "chip"}>
            {section}
          </span>
        ))}
      </div>
      <p className="muted small">Change libraries or stop sharing on the Sharing tab.</p>
    </>
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

function banInfo(b: { banned_by: string | null; banned_at: string | null; reason: string | null; attempts: number } | undefined): string {
  if (!b) return "Banned";
  const at = b.banned_at ? new Date(b.banned_at.endsWith("Z") ? b.banned_at : `${b.banned_at}Z`).toLocaleString() : "";
  return [`Banned ${at}`.trim(), b.banned_by ? `by ${b.banned_by}` : "", b.reason ? `: ${b.reason}` : "", `, ${b.attempts} attempt${b.attempts === 1 ? "" : "s"} since`]
    .join("")
    .trim();
}

/* "3 hours ago", which scans faster in a list than a full timestamp. */
function ago(epoch: number | null | undefined): string {
  if (!epoch) return "never";
  const seconds = Date.now() / 1000 - epoch;
  if (seconds < 60) return "just now";
  const steps: [number, string][] = [
    [60, "minute"],
    [3600, "hour"],
    [86400, "day"],
    [2592000, "month"],
    [31536000, "year"],
  ];
  let unit = steps[0];
  for (const step of steps) if (seconds >= step[0]) unit = step;
  const n = Math.floor(seconds / unit[0]);
  return `${n} ${unit[1]}${n === 1 ? "" : "s"} ago`;
}
