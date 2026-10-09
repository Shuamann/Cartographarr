import MultiSelect from "../components/MultiSelect";
import { askConfirm, tell } from "../components/Ask";
import Loading from "../components/Loading";
import MediaPanel from "../components/MediaPanel";
import RecapView from "../components/Recap";
import TitleRow, { TitleRows, type TitleFact } from "../components/TitleRow";
import type { FilterState } from "../lib/filters";
import { useEffect, useMemo, useState, type ReactNode } from "react";
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
  type PartwayRow,
  type UserDetail,
} from "../lib/api";
import { useNav } from "../lib/nav";
import type { PeopleFilter } from "../lib/tabs";
import { coveredBy, useAddressBans, useBans } from "../lib/bans";
import SettingsLink, { SETTINGS_PAGES } from "../components/SettingsLink";

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

type Mode = "users" | "devices" | "addresses";

type AddressRow = {
  ip_address: string;
  plays: number;
  users: number;
  devices: number;
  last_seen: number | null;
  location: string | null;
  who: string | null;
  city: string | null;
  country: string | null;
  asn_org: string | null;
  is_hosting: boolean | null;
  banned: boolean;
};
type Sort = "last_seen" | "plays" | "name";

/* A tick that says this device belongs to this account.
 *
 * It quiets one thing: a pair of plays is not raised as one account in two
 * places when both ends are trusted devices of that account. A phone on
 * mobile data and a laptop carried to work are the same person every time,
 * and the signal has no way to know it without being told. Both ends, never
 * one: a trusted device playing alongside one nobody recognises is the case
 * most worth seeing.
 */
function TrustTick({
  trusted,
  onChange,
  label,
}: {
  trusted: boolean;
  onChange: (next: boolean) => void;
  label: string;
}) {
  return (
    <button
      className={trusted ? "btn trust on" : "btn trust"}
      aria-pressed={trusted}
      title={
        trusted
          ? `${label} is trusted. Plays from here are not raised against another trusted device of the same account.`
          : `Trust ${label}, so plays from here are not raised against another trusted device of the same account.`
      }
      onClick={() => onChange(!trusted)}
    >
      <span aria-hidden="true">{"\u2713"}</span>
      {trusted ? "Trusted" : "Trust"}
    </button>
  );
}

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
  /* A person, a device and an address are three ways of asking the same
     question, so the useful question is usually a combination of them. Each
     list is narrowed by the other two; the one you are looking at is not
     offered as a filter on itself. */
  const [pickUser, setPickUser] = useState<string[]>([]);
  const [pickDevice, setPickDevice] = useState<string[]>([]);
  const [pickAddress, setPickAddress] = useState<string[]>([]);
  const picked = pickUser.length + pickDevice.length + pickAddress.length;

  const params = (...pairs: [string, string[]][]) => {
    const q = new URLSearchParams();
    for (const [key, values] of pairs) for (const v of values) q.append(key, v);
    const text = q.toString();
    return text ? `&${text}` : "";
  };

  /* The full lists stay as they are: every name lookup on this page reads
     them, and narrowing the options by the filter would make a choice
     impossible to undo from the list it had just emptied. What is displayed
     is its own query. */
  const allAddresses = useApi<AddressRow[]>("/addresses?limit=500");
  const shownUsers = useApi<PlexUser[]>(
    mode === "users" && (pickDevice.length || pickAddress.length)
      ? `/users?${params(["machine_id", pickDevice], ["ip_address", pickAddress]).slice(1)}`
      : null,
    [mode, pickDevice.join(), pickAddress.join()],
  );
  const shownDevices = useApi<Device[]>(
    mode === "devices" && (pickUser.length || pickAddress.length)
      ? `/devices?${params(["only_user_id", pickUser], ["ip_address", pickAddress]).slice(1)}`
      : null,
    [mode, pickUser.join(), pickAddress.join()],
  );
  const addresses = useApi<AddressRow[]>(
    mode === "addresses"
      ? `/addresses?limit=500${params(["user_id", pickUser], ["machine_id", pickDevice])}`
      : null,
    [mode, pickUser.join(), pickDevice.join()],
  );
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

  const nav = useNav();
  const suggestions = useApi<{ machine_id: string }[]>(nav.isAdmin ? "/devices/trust-suggestions" : null);
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

  const userRows = (shownUsers.data ?? users.data ?? [])
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

  const addressRows = (addresses.data ?? [])
    .filter((a) => {
      if (onlyBanned && !a.banned) return false;
      if (!q) return true;
      return [a.ip_address, a.who, a.city, a.country, a.asn_org].some((h) => h && h.toLowerCase().includes(q));
    })
    .sort((a, b) =>
      sort === "plays"
        ? b.plays - a.plays
        : sort === "name"
          ? a.ip_address.localeCompare(b.ip_address)
          : (b.last_seen ?? 0) - (a.last_seen ?? 0),
    );

  const deviceRows = (shownDevices.data ?? devices.data ?? [])
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
      <h1 className="spoken">Endpoints</h1>
      <aside className="people-list">
        <div className="people-tools">
          <input
            className="search"
            type="search"
            placeholder="Search people, devices, ids"
            value={search}
            onChange={(e) => setSearch(e.target.value)}
          />
          {/* The list you are looking at is not offered as a filter on
              itself: picking it would be the list. */}
          <div className="row wrap endpoint-filters">
            {mode !== "users" && (
              <MultiSelect
                label="Person"
                selected={pickUser}
                onChange={(next) => setPickUser(next.map(String))}
                options={(users.data ?? []).map((u) => ({
                  value: String(u.user_id),
                  label: u.friendly_name || u.username || `User ${u.user_id}`,
                }))}
              />
            )}
            {mode !== "devices" && (
              <MultiSelect
                label="Device"
                selected={pickDevice}
                onChange={(next) => setPickDevice(next.map(String))}
                options={(devices.data ?? []).map((d) => ({
                  value: d.machine_id,
                  label: `${d.player || "Unnamed"}${d.platform ? ` (${d.platform})` : ""}`,
                }))}
              />
            )}
            {mode !== "addresses" && (
              <MultiSelect
                label="Address"
                selected={pickAddress}
                onChange={(next) => setPickAddress(next.map(String))}
                options={(allAddresses.data ?? []).map((a) => ({
                  value: a.ip_address,
                  label: `${a.ip_address}${a.city ? ` (${a.city})` : ""}`,
                }))}
              />
            )}
            {picked > 0 && (
              <button
                className="chip"
                onClick={() => {
                  setPickUser([]);
                  setPickDevice([]);
                  setPickAddress([]);
                }}
              >
                Clear {picked}
              </button>
            )}
          </div>

          <div className="row-between">
            <div className="segmented">
              <button className={mode === "users" ? "seg on" : "seg"} onClick={() => setMode("users")}>
                Users {users.data?.length ?? ""}
              </button>
              <button className={mode === "devices" ? "seg on" : "seg"} onClick={() => setMode("devices")}>
                Devices {devices.data?.length ?? ""}
              </button>
              <button className={mode === "addresses" ? "seg on" : "seg"} onClick={() => setMode("addresses")}>
                Addresses {addresses.data?.length ?? ""}
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
            {/* A count that has read the same number for years says nothing.
                Clearing it is what makes the next one mean something, and
                there was no way to do it except one device at a time. */}
            {nav.isAdmin && newCount > 1 && (
              <button
                className="chip"
                title="Clear the new flag on all of them, so the next new device stands out"
                onClick={async () => {
                  if (!(await askConfirm({
                    title: `Mark all ${newCount} devices as reviewed?`,
                    body: "They stay in the list, but the next new one stands out.",
                    confirm: "Mark them reviewed",
                  }))) return;
                  try {
                    await api.post("/devices/review-all", {});
                    devices.reload();
                  } catch (err) {
                    void tell("That did not work", (err as Error).message);
                  }
                }}
              >
                Mark all reviewed
              </button>
            )}
            {/* The flag is set by hand and the tick is the final word, but the
                data already says which devices are not in question: a long
                history on one account and none on any other. Offering those
                is the difference between a feature somebody uses and one
                nobody has the afternoon for. */}
            {nav.isAdmin && (suggestions.data?.length ?? 0) > 0 && (
              <button
                className="chip"
                title="Trust the devices with a settled history on one account and no history on any other"
                onClick={async () => {
                  const n = suggestions.data?.length ?? 0;
                  if (!(await askConfirm({
                    title: `Trust ${n} device${n === 1 ? "" : "s"}?`,
                    body:
                      "Each has a long history on one account and none on any other. Trusting them stops a pair of"
                      + " their plays being raised as one account in two places. Any of them can be untrusted again.",
                    confirm: "Trust them",
                  }))) return;
                  try {
                    await api.post("/devices/trust-suggested", {});
                    devices.reload();
                    suggestions.reload();
                  } catch (err) {
                    void tell("That did not work", (err as Error).message);
                  }
                }}
              >
                Trust {suggestions.data?.length} settled
              </button>
            )}
          </div>
        </div>

        {(users.error || devices.error) && <p className="note bad-note" role="alert">{users.error || devices.error}</p>}

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

          {mode === "addresses" &&
            addressRows.map((a) => {
              const here = selected?.kind === "address" && selected.id === a.ip_address;
              return (
                <button
                  key={a.ip_address}
                  className={here ? "device-row flat address-row on" : "device-row flat address-row"}
                  onClick={() => setSelected({ kind: "address", id: a.ip_address })}
                >
                  <span className="clip">
                    {a.ip_address}
                    <span className="muted small person-owner">
                      {[a.who, a.city].filter(Boolean).join(" · ") || a.country || "Unknown"}
                    </span>
                  </span>
                  <span className="muted small">
                    {a.plays.toLocaleString()} · {ago(a.last_seen)}
                  </span>
                  {a.is_hosting && <span className="pill vpn">VPN</span>}
                  {a.banned && <span className="pill banned">banned</span>}
                </button>
              );
            })}

          {mode === "users" && users.data && userRows.length === 0 && <p className="muted pad-s">Nobody matches.</p>}
          {mode === "devices" && devices.data && deviceRows.length === 0 && <p className="muted pad-s">No device matches.</p>}
          {mode === "addresses" && addresses.data && addressRows.length === 0 && (
            <p className="muted pad-s">No address matches.</p>
          )}
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

type Tab = "overview" | "recap" | "users" | "history" | "places" | "devices" | "activity" | "access";

/* What somebody started and did not finish.
 *
 * An episode is listed under its show, because the answer to "what am I
 * partway through" is the name of the show, not the name of an episode. Drawn
 * as every other title is, and said even when there is nothing: a section
 * that vanishes when it is empty reads as a feature that is not there.
 */
function Partway({ rows }: { rows: PartwayRow[] }) {
  const [open, setOpen] = useState<number | null>(null);
  return (
    <section className="profile-section">
      <h3>Partway through</h3>
      {rows.length === 0 ? (
        <p className="muted">Nothing started and left unfinished in the last six months.</p>
      ) : (
        <TitleRows>
          {rows.map((r) => (
            <div key={r.rating_key}>
              <TitleRow
                ratingKey={r.rating_key}
                item={{
                  media_type: r.media_type,
                  full_title: r.what,
                  title: r.episode_title ?? r.title,
                  grandparent_title: r.show_rating_key ? r.title : null,
                  parent_media_index: r.season,
                  media_index: r.episode,
                  year: r.year,
                }}
                facts={[
                  {
                    label: "Progress",
                    value: (
                      <span className="row partway-at">
                        <span className="progress" title={`${r.percent}% in`}>
                          <span className="progress-fill" style={{ width: `${r.percent}%` }} />
                        </span>
                        <span>{r.percent}%</span>
                      </span>
                    ),
                  },
                  { label: "Last", value: ago(r.last_play) },
                ]}
                open={open === r.rating_key}
                onToggle={() => setOpen(open === r.rating_key ? null : r.rating_key)}
              />
              {open === r.rating_key && (
                <div className="top-media-detail">
                  <MediaPanel ratingKey={r.rating_key} />
                </div>
              )}
            </div>
          ))}
        </TitleRows>
      )}
    </section>
  );
}

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
  const bans = useBans();
  const detail = useApi<UserDetail>(`/users/${userId}`);
  const [tab, setTab] = useState<Tab>("overview");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  if (detail.error) return <p className="note bad-note pad" role="alert">{detail.error}</p>;
  if (!detail.data) return <div className="pad"><Loading /></div>;
  const u = detail.data;
  const name = u.friendly_name || u.username || `Account ${u.user_id}`;
  const streaming = (live?.sessions ?? []).filter((s) => Number(s.user_id) === userId);

  async function restore() {
    if (!(await askConfirm({
      title: `Restore ${name} in Tautulli?`,
      body: "History Tautulli erased when they were deleted does not come back.",
      confirm: "Restore",
    }))) return;
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
    ["recap", "Recap"],
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
      {error && <p className="note bad-note" role="alert">{error}</p>}

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
            <Overview profile={u} extra={[["Devices", String(u.devices.length)]]} scope={{ user_id: [userId] }}>
              <Partway rows={u.partway ?? []} />
            </Overview>
            <PlaybackSection path={`/users/${userId}/playback`} who="this person" />
          </>
        )}
        {tab === "history" && <RecentPlays query={`user_id=${userId}`} onOpenAll={() => nav.filterTo?.("History", { user_id: [userId] })} showDevice />}
        {tab === "places" && <Places profile={u} scope={{ user_id: [userId] }} onMap={() => nav.filterTo?.("Map", { user_id: [userId] })} />}
        {tab === "devices" && (
          <div className="mini-list">
            {u.devices.length === 0 && <p className="muted">No devices recorded.</p>}
            {u.devices.map((d) => (
              <button key={d.machine_id} className="mini mini-button" onClick={() => onSelectDevice(d.machine_id)}>
                <div className="min0">
                  <strong>{d.player || "Unnamed"}</strong>
                  {d.is_new_unreviewed && <span className="pill warn">new</span>}
                  {bans.ids.has(d.machine_id) && <span className="pill banned">banned</span>}
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
        {tab === "recap" && <RecapView userId={userId} />}
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

  if (detail.error) return <p className="note bad-note pad" role="alert">{detail.error}</p>;
  if (!detail.data) return <div className="pad"><Loading /></div>;
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
            {d.trusted && (
              <span className="pill ok" title={d.trusted_by ? `Trusted by ${d.trusted_by}` : "Trusted"}>
                trusted
              </span>
            )}
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
          {nav.isAdmin && (
            <TrustTick
              trusted={Boolean(d.trusted)}
              label={label}
              onChange={async (next) => {
                await api
                  .post(`/devices/${encodeURIComponent(machineId)}/trust?trusted=${next}`)
                  .catch(() => {});
                detail.reload();
                onChanged();
              }}
            />
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
            <Overview profile={d} extra={[["First", when(d.first_seen)]]} scope={{ machine_id: [machineId], machineLabel: label }} />
            <PlaybackSection path={`/devices/${encodeURIComponent(machineId)}/playback`} who="this device" />
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
        {tab === "places" && (
          <Places
            profile={d}
            scope={{ machine_id: [machineId], machineLabel: label }}
            onMap={() => nav.filterTo?.("Map", { machine_id: [machineId], machineLabel: label })}
          />
        )}
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
  const addressBans = useAddressBans();
  const covering = coveredBy(ip, addressBans.list);
  const [tab, setTab] = useState<"overview" | "history">("overview");

  if (detail.error) return <p className="note bad-note pad" role="alert">{detail.error}</p>;
  if (!detail.data) return <div className="pad"><Loading /></div>;
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
            {covering && (
              <span className="pill banned">
                {covering === ip ? "banned" : `covered by ${covering}`}
              </span>
            )}
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
          {/* Banned as itself or as the block around it, asked in the dialog.
              A ban made on the exact address does not hide a wider one that
              already covers it, so both buttons can be true at once. */}
          {nav.blockAddress && !covering && (
            <button className="btn danger" onClick={() => nav.blockAddress?.(ip, ip)}>
              Ban address
            </button>
          )}
          {/* Unbans whatever is actually stopping it, which may be the range
              rather than this address. */}
          {nav.unbanAddress && covering && (
            <button className="btn" onClick={() => nav.unbanAddress?.(covering)}>
              {covering === ip ? "Unban address" : `Unban ${covering}`}
            </button>
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
            <dl className="spec profile-facts">
              <Stat label="Plays" value={a.totals.plays.toLocaleString()} sub={sessionsSub(a.totals)} />
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
              <TopMedia items={a.top_media} scope={{ ip_address: [ip] }} />
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

function Overview({
  profile: p,
  extra = [],
  scope,
  children,
}: {
  profile: Profile;
  extra?: [string, string][];
  /* The filters that mean "this user" or "this device", for links out. */
  scope: Partial<FilterState>;
  /* Above the lists: what is happening now reads before what happened most. */
  children?: ReactNode;
}) {
  const vpn = p.addresses.filter((a) => a.is_hosting).length;
  return (
    <>
      <dl className="spec profile-facts">
        <Stat label="Plays" value={p.totals.plays.toLocaleString()} sub={sessionsSub(p.totals)} />
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

      {children}

      <div className="dash-cols">
        <section className="profile-section">
          <h3>Most watched</h3>
          <TopMedia items={p.top_media} scope={scope} />
        </section>
        <section className="profile-section">
          <h3>Where from</h3>
          <PlaceList places={p.places.slice(0, 6)} scope={scope} />
        </section>
      </div>
    </>
  );
}

function Places({ profile: p, onMap, scope }: { profile: Profile; onMap: () => void; scope: Partial<FilterState> }) {
  const nav = useNav();
  return (
    <>
      <div className="row-between">
        <h3>Places</h3>
        <button className="btn" onClick={onMap}>
          Show on map
        </button>
      </div>
      <PlaceList places={p.places} scope={scope} />

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

/* Each place opens the map there, narrowed to whoever this profile is. */
function PlaceList({ places, scope }: { places: Profile["places"]; scope?: Partial<FilterState> }) {
  const nav = useNav();
  if (places.length === 0) return <p className="muted">No located plays.</p>;
  return (
    <div className="mini-list">
      {places.map((x, i) => {
        const name = [x.city, x.region, x.country].filter(Boolean).join(", ") || "Unknown";
        const body = (
          <>
            <div className="min0">
              <span className="clip">{name}</span>
              {x.is_hosting && <span className="pill vpn">VPN</span>}
              <p className="muted small">last {ago(x.last_play)}</p>
            </div>
            <span className="muted">{x.plays.toLocaleString()}</span>
          </>
        );
        return nav.showPlace && x.lat != null && x.lon != null ? (
          <button
            key={i}
            className="mini mini-button"
            title={`Show ${name} on the map`}
            onClick={() => nav.showPlace?.({ lat: x.lat as number, lon: x.lon as number }, scope)}
          >
            {body}
          </button>
        ) : (
          <div key={i} className="mini">
            {body}
          </div>
        );
      })}
    </div>
  );
}

type Playback = {
  days: number;
  plays: number;
  transcoded: number;
  streams_recorded: number;
  hardware: number;
  transcode_causes: { cause: string; label: string; streams: number }[];
  stalls: number;
  stall_minutes: number;
  stall_causes: { cause: string; label: string; stalls: number }[];
  stalled_titles: { rating_key: number; title: string | null; stalls: number }[];
};

/* How streams play here: transcodes and why, stalls and what is likely to
 * blame. "Is it their device?" answered on the profile itself. */
function PlaybackSection({ path, who }: { path: string; who: string }) {
  const nav = useNav();
  const data = useApi<Playback>(`${path}?days=90`);
  if (data.error) return null;
  if (!data.data) return <Loading compact label="Reading how streams play" />;
  const p = data.data;
  if (!p.plays && !p.streams_recorded && !p.stalls) return null;
  const share = p.plays ? Math.round((p.transcoded / p.plays) * 100) : 0;
  const count = (cause: string) => p.stall_causes.find((c) => c.cause === cause)?.stalls ?? 0;
  const elsewhere = count("server") + count("upload") + count("file");
  // "One stream that kept stalling" is counted with the viewer's side: a
  // sitting that rebuffers again and again is their line at that moment, or a
  // file too big for it, rather than anything the server did.
  const theirs = count("viewer") + count("stream");
  const verdict =
    p.stalls === 0
      ? `No stalls recorded for ${who} in the last ${p.days} days.`
      : theirs / p.stalls >= 0.5
        ? count("stream") > count("viewer")
          ? `Most stalls were single streams that kept stalling: usually ${who}'s connection at the time, or a file ` +
            "too big to send them."
          : `Most stalls look like ${who}'s device or connection: stalls across many titles while nobody else stalls.`
        : elsewhere / p.stalls >= 0.5
          ? `Most stalls are not down to ${who}: they came from the ${
              count("file") >= count("server") + count("upload") ? "files being watched" : "server or its upload"
            }.`
          : `${p.stalls} stall${p.stalls === 1 ? "" : "s"} so far, with no pattern yet.`;
  return (
    <section className="profile-section playback">
      <h3>How it plays, last {p.days} days</h3>
      <p className="small">{verdict}</p>
      <dl className="spec profile-facts">
        <Stat label="Transcoded" value={`${share}% of plays, ${p.transcoded} of ${p.plays}`} />
        <Stat label="Stalls" value={p.stalls ? `${p.stalls}, ${p.stall_minutes} min` : "None"} />
      </dl>
      <div className="dash-cols">
        <div>
          <h4>Why streams transcoded</h4>
          {p.transcode_causes.length === 0 ? (
            <p className="muted small">
              {p.streams_recorded ? "Every recorded stream played directly." : "No streams recorded live yet."}
            </p>
          ) : (
            <div className="mini-list">
              {p.transcode_causes.map((c) => (
                <div key={c.cause} className="mini">
                  <span>{c.label}</span>
                  <span className="muted">{c.streams}</span>
                </div>
              ))}
            </div>
          )}
        </div>
        <div>
          <h4>Likely cause of stalls</h4>
          {p.stall_causes.length === 0 ? (
            <p className="muted small">No stalls.</p>
          ) : (
            <div className="mini-list">
              {p.stall_causes.map((c) => (
                <div key={c.cause} className="mini">
                  <span>{c.label}</span>
                  <span className="muted">{c.stalls}</span>
                </div>
              ))}
            </div>
          )}
          {p.stalled_titles.length > 0 && (
            <p className="muted small">
              Stalled most on{" "}
              {p.stalled_titles.map((t, i) => (
                <span key={t.rating_key}>
                  {i > 0 ? ", " : ""}
                  {nav.filterTo ? (
                    <button
                      className="linkish"
                      onClick={() => nav.filterTo?.("History", { rating_key: t.rating_key, ratingKeyLabel: t.title ?? "" })}
                    >
                      {t.title ?? `item ${t.rating_key}`}
                    </button>
                  ) : (
                    t.title
                  )}{" "}
                  ({t.stalls})
                </span>
              ))}
            </p>
          )}
        </div>
      </div>
    </section>
  );
}

/* Titles, each opening in place to the title's own card: poster, summary,
 * links out, and a jump to these plays in History. */
function TopMedia({ items, scope }: { items: Profile["top_media"]; scope?: Partial<FilterState> }) {
  const nav = useNav();
  const [open, setOpen] = useState<number | null>(null);
  if (items.length === 0) return <p className="muted">Nothing yet.</p>;
  return (
    <TitleRows>
      {items.map((m) => (
        <div key={m.rating_key}>
          <TitleRow
            ratingKey={m.rating_key}
            item={{ title: m.title, full_title: m.title, media_type: m.media_type, year: m.year }}
            facts={[
              { label: "Plays", value: m.plays.toLocaleString() },
              { label: "Watched", value: duration(m.seconds) },
              { label: "Last", value: ago(m.last_play) },
            ]}
            open={open === m.rating_key}
            onToggle={() => setOpen(open === m.rating_key ? null : m.rating_key)}
          />
          {open === m.rating_key && (
            <div className="top-media-detail">
              <MediaPanel
                ratingKey={m.rating_key}
                filterLabel="These plays in History"
                onFilterToTitle={
                  nav.filterTo
                    ? (ratingKey, title) => nav.filterTo?.("History", { ...(scope ?? {}), rating_key: ratingKey, ratingKeyLabel: title })
                    : undefined
                }
              />
            </div>
          )}
        </div>
      ))}
    </TitleRows>
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
  const [open, setOpen] = useState<number | null>(null);

  if (page.error) return <p className="note bad-note" role="alert">{page.error}</p>;
  if (!page.data) return <Loading compact />;

  // A link inside a row goes where it names and does not open the row too.
  const stop = (e: React.MouseEvent) => e.stopPropagation();

  return (
    <>
      <div className="row-between">
        <h3>Latest {page.data.items.length} of {page.data.total.toLocaleString()} plays</h3>
        <button className="btn" onClick={onOpenAll}>
          Open in History
        </button>
      </div>
      <TitleRows>
        {page.data.items.map((h) => {
          const facts: TitleFact[] = [{ label: "When", value: when(h.started) }];
          if (showUser && h.user_id != null)
            facts.push({
              label: "Who",
              value: nav.openUser ? (
                <button className="linkish" onClick={(e) => { stop(e); nav.openUser?.(h.user_id as number); }}>
                  {names.get(h.user_id) ?? h.user_id}
                </button>
              ) : (
                names.get(h.user_id) ?? h.user_id
              ),
            });
          if (showDevice && h.player)
            facts.push({
              label: "Device",
              value:
                nav.openDevice && h.machine_id ? (
                  <button className="linkish" onClick={(e) => { stop(e); nav.openDevice?.(h.machine_id as string); }}>
                    {h.player}
                  </button>
                ) : (
                  h.player
                ),
            });
          if (h.transcode_decision) facts.push({ label: "Playback", value: h.transcode_decision });
          if (h.percent_complete != null) facts.push({ label: "Watched", value: `${h.percent_complete}%` });
          return (
            <div key={h.row_id}>
              <TitleRow
                ratingKey={h.rating_key}
                item={h}
                facts={facts}
                open={open === h.row_id}
                onToggle={h.rating_key ? () => setOpen(open === h.row_id ? null : h.row_id) : undefined}
              />
              {open === h.row_id && h.rating_key && (
                <div className="top-media-detail">
                  <MediaPanel ratingKey={h.rating_key} />
                </div>
              )}
            </div>
          );
        })}
      </TitleRows>
    </>
  );
}

function ActivityList({ query }: { query: string }) {
  const nav = useNav();
  const events = useApi<PersonEvent[]>(`/people/activity?${query}`);
  const [open, setOpen] = useState<string | null>(null);

  if (events.error) return <p className="note bad-note" role="alert">{events.error}</p>;
  if (!events.data) return <Loading compact />;

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

/* Which libraries Plex shares with this person, changeable here, with the
 * same guard rails as the Sharing tab: libraries are saved and read back
 * from Plex, and stopping sharing needs the username typed back, since it
 * cannot be undone from here. */
function Access({ username }: { username: string | null }) {
  const shares = useApi<{ configured: boolean; users: Share[]; sections: string[] }>("/sharing");
  const [draft, setDraft] = useState<string[] | null>(null);
  const [removing, setRemoving] = useState(false);
  const [confirmName, setConfirmName] = useState("");
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState<string | null>(null);

  if (shares.error) return <p className="note bad-note" role="alert">{shares.error}</p>;
  if (!shares.data) return <p className="muted">Asking Plex…</p>;
  if (!shares.data.configured) {
    return (
      <p className="note warn-note">
        <SettingsLink page={SETTINGS_PAGES.plex}>Add a Plex token in Settings</SettingsLink> to see and change which
        libraries are shared.
      </p>
    );
  }
  const share = shares.data.users.find((x) => x.username === username);
  if (!share || !username) {
    return (
      <p className="note warn-note">
        Plex is not sharing this server with {username ?? "this account"}. They may have been removed, or they
        use a Plex Home or guest account.
      </p>
    );
  }

  const selected = draft ?? share.sections;
  const changed = draft !== null && [...draft].sort().join("|") !== [...share.sections].sort().join("|");

  async function save() {
    setBusy(true);
    setMessage(null);
    try {
      await api.put(`/sharing/${encodeURIComponent(username as string)}/sections`, { sections: selected });
      setDraft(null);
      shares.reload();
      setMessage("Saved. This is what Plex now reports.");
    } catch (err) {
      setMessage((err as Error).message);
    } finally {
      setBusy(false);
    }
  }

  async function unshare() {
    setBusy(true);
    setMessage(null);
    try {
      const r = await fetch(`/api/sharing/${encodeURIComponent(username as string)}`, {
        method: "DELETE",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ confirm: confirmName }),
      });
      if (!r.ok) throw new Error((await r.json().catch(() => ({}))).detail ?? r.statusText);
      setRemoving(false);
      shares.reload();
    } catch (err) {
      setMessage((err as Error).message);
    } finally {
      setBusy(false);
    }
  }

  return (
    <>
      <h3>Shared libraries</h3>
      <p className="muted small">Click a library to share it or take it away, then save.</p>
      <div className="row wrap chips">
        {shares.data.sections.map((section) => (
          <button
            key={section}
            className={selected.includes(section) ? "chip on" : "chip"}
            disabled={busy}
            onClick={() =>
              setDraft(selected.includes(section) ? selected.filter((x) => x !== section) : [...selected, section])
            }
          >
            {section}
          </button>
        ))}
      </div>
      {selected.length === 0 && (
        <p className="muted small">Nothing selected keeps the share with no libraries in it, which is not the same as stopping sharing.</p>
      )}
      <div className="row access-actions">
        <button className="btn primary" onClick={save} disabled={!changed || busy}>
          {busy && !removing ? "Saving…" : "Save libraries"}
        </button>
        {changed && (
          <button className="btn" onClick={() => setDraft(null)} disabled={busy}>
            Undo changes
          </button>
        )}
        <button className="btn danger" onClick={() => setRemoving(!removing)} disabled={busy}>
          {removing ? "Cancel" : "Stop sharing"}
        </button>
      </div>
      {message && <p className="note">{message}</p>}

      {removing && (
        <div className="editor danger-editor">
          <h3>Stop sharing with {username}?</h3>
          <p className="note warn-note">
            This cannot be undone from here. Getting them back means sending a fresh invitation that they have to
            accept. Their history stays in Cartographarr either way.
          </p>
          <label>
            Type <strong>{username}</strong> to confirm
            <input value={confirmName} onChange={(e) => setConfirmName(e.target.value)} autoFocus />
          </label>
          <div className="row">
            <button className="btn danger" onClick={unshare} disabled={busy || confirmName.trim() !== username}>
              {busy ? "Removing…" : "Stop sharing"}
            </button>
          </div>
        </div>
      )}
    </>
  );
}

function sessionsSub(t: { plays: number; sessions: number }): string | undefined {
  return t.sessions && t.sessions !== t.plays ? `${t.sessions.toLocaleString()} sessions` : undefined;
}

/* A fact, as label and value on one line. These were boxes, five of them
   across the top of a person with one number in each, which made the
   summary the largest thing on the page and the slowest to read. */
function Stat({ label, value, sub }: { label: string; value: string; sub?: string }) {
  return (
    <div className="spec-pair">
      <dt>{label}</dt>
      <dd>
        {/* One piece of text: the cell is a flex row, and its gap would
            otherwise open a space before the comma. */}
        <span>
          {value}
          {sub && <span className="muted">, {sub}</span>}
        </span>
      </dd>
    </div>
  );
}

function banInfo(
  b: { banned_by: string | null; banned_at: string | null; reason: string | null; attempts: number; expires_at?: string | null } | undefined,
): string {
  if (!b) return "Banned";
  const at = b.banned_at ? new Date(b.banned_at.endsWith("Z") ? b.banned_at : `${b.banned_at}Z`).toLocaleString() : "";
  const until = b.expires_at ? new Date(b.expires_at.endsWith("Z") ? b.expires_at : `${b.expires_at}Z`).toLocaleString() : null;
  return [`Banned ${at}`.trim(), b.banned_by ? ` by ${b.banned_by}` : "", until ? `, until ${until}` : "", b.reason ? `: ${b.reason}` : "", `, ${b.attempts} attempt${b.attempts === 1 ? "" : "s"} since`]
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
