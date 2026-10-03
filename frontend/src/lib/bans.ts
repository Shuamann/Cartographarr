import { useEffect, useMemo } from "react";
import { api, useApi } from "./api";
import { useNav } from "./nav";

export type Ban = {
  machine_id: string;
  label: string | null;
  user_id: number | null;
  user_name: string | null;
  reason: string | null;
  banned_by: string | null;
  banned_at: string | null;
  last_seen: number | null;
  attempts: number;
  last_attempt: string | null;
  expires_at: string | null;
};

/* Every component that shows a Ban or Unban button reads the list from here,
 * and every change announces itself, so a ban made on the map shows up on the
 * People page without a reload. */
const CHANGED = "cartographarr:bans-changed";

export function useBans() {
  // The ban list is admin data, and refused to viewers while viewer privacy
  // is on, so only admins ask for it.
  const { isAdmin } = useNav();
  const bans = useApi<Ban[]>(isAdmin ? "/bans" : null, [isAdmin]);
  useEffect(() => {
    const reload = () => bans.reload();
    window.addEventListener(CHANGED, reload);
    return () => window.removeEventListener(CHANGED, reload);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);
  const ids = useMemo(() => new Set((bans.data ?? []).map((b) => b.machine_id)), [bans.data]);
  return { list: bans.data ?? [], ids, loading: bans.loading, error: bans.error };
}

export async function ban(machineId: string, reason: string, hours?: number | null): Promise<void> {
  await api.post("/bans", { machine_id: machineId, reason, hours: hours || null });
  window.dispatchEvent(new Event(CHANGED));
}

/* A ban on the connection rather than the box.
 *
 * Which you want depends on what is coming back: a device ban follows one
 * machine and survives it moving house, an address ban catches the same
 * household however many identifiers it arrives under. They are separate
 * lists, and the Log says which one stopped a stream.
 */
export type AddressBan = {
  address: string;
  label: string | null;
  user_id: number | null;
  user_name: string | null;
  reason: string | null;
  banned_by: string | null;
  banned_at: string | null;
  attempts: number;
  last_attempt: string | null;
  expires_at: string | null;
};

export function useAddressBans() {
  const { isAdmin } = useNav();
  const bans = useApi<AddressBan[]>(isAdmin ? "/address-bans" : null, [isAdmin]);
  useEffect(() => {
    const reload = () => bans.reload();
    window.addEventListener(CHANGED, reload);
    return () => window.removeEventListener(CHANGED, reload);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);
  const addresses = useMemo(() => new Set((bans.data ?? []).map((b) => b.address)), [bans.data]);
  return { list: bans.data ?? [], addresses, loading: bans.loading, error: bans.error };
}

export async function banAddress(address: string, reason: string, hours?: number | null): Promise<void> {
  await api.post("/address-bans", { address, reason, hours: hours || null });
  window.dispatchEvent(new Event(CHANGED));
}

export async function unbanAddress(address: string): Promise<void> {
  await api.del(`/address-bans/${encodeURIComponent(address)}`);
  window.dispatchEvent(new Event(CHANGED));
}

/* How long a ban can last. Zero is permanent. */
export const BAN_LENGTHS = [
  { hours: 0, label: "Permanently" },
  { hours: 1, label: "1 hour" },
  { hours: 24, label: "1 day" },
  { hours: 24 * 7, label: "1 week" },
  { hours: 24 * 30, label: "30 days" },
];

/* When a timed ban ends, as a local date and time, or null if permanent.
 * Stored as UTC without a zone marker. */
export function banEnds(b: { expires_at: string | null } | undefined): string | null {
  if (!b?.expires_at) return null;
  const iso = /[zZ]|[+-]\d\d:\d\d$/.test(b.expires_at) ? b.expires_at : `${b.expires_at}Z`;
  return new Date(iso).toLocaleString();
}

export async function setBanReason(machineId: string, reason: string): Promise<void> {
  await api.patch(`/bans/${encodeURIComponent(machineId)}`, { reason });
  window.dispatchEvent(new Event(CHANGED));
}

export async function unban(machineId: string): Promise<void> {
  await api.del(`/bans/${encodeURIComponent(machineId)}`);
  window.dispatchEvent(new Event(CHANGED));
}
