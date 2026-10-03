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

/* How wide to make an address ban.
 *
 * One address catches one connection, which is enough until the household's
 * address changes. A provider usually hands out addresses from a block, so
 * the /24 catches the same house after a reconnect, at the cost of catching
 * up to 255 neighbours with it. That trade is the viewer's to make, so it is
 * offered rather than guessed.
 *
 * IPv4 only. An IPv6 address is offered as itself, because working out which
 * part of one a provider treats as a customer is guesswork, and a wrong guess
 * here bans a stranger.
 */
export type Scope = { value: string; label: string; hint: string };

export function scopesFor(address: string): Scope[] {
  const exact = { value: address, label: "This address only", hint: "One connection" };
  const parts = address.trim().split(".");
  if (parts.length !== 4 || parts.some((p) => !/^\d{1,3}$/.test(p) || Number(p) > 255)) return [exact];
  return [
    exact,
    {
      value: `${parts[0]}.${parts[1]}.${parts[2]}.0/24`,
      label: `${parts[0]}.${parts[1]}.${parts[2]}.0/24`,
      hint: "This address and up to 255 neighbours, for an address that changes",
    },
    {
      value: `${parts[0]}.${parts[1]}.0.0/16`,
      label: `${parts[0]}.${parts[1]}.0.0/16`,
      hint: "65,536 addresses. Wide enough to catch people you did not mean",
    },
  ];
}

function asInt(address: string): number | null {
  const parts = address.trim().split(".");
  if (parts.length !== 4) return null;
  let total = 0;
  for (const part of parts) {
    if (!/^\d{1,3}$/.test(part) || Number(part) > 255) return null;
    total = (total << 8) | Number(part);
  }
  return total >>> 0;
}

/* Which ban, if any, already covers this address.
 *
 * The list holds exact addresses and ranges, so an address can be banned
 * without being on it. A page that only checked for an exact entry would
 * offer to ban something that is already stopped. IPv4 ranges only, matching
 * what scopesFor will write; an exact entry matches whatever it is.
 */
export function coveredBy(address: string, list: AddressBan[]): string | null {
  for (const ban of list) {
    if (ban.address === address) return ban.address;
    const [network, bits] = ban.address.split("/");
    if (!bits) continue;
    const here = asInt(address);
    const there = asInt(network);
    const width = Number(bits);
    if (here === null || there === null || !(width >= 0 && width <= 32)) continue;
    const mask = width === 0 ? 0 : (~0 << (32 - width)) >>> 0;
    if (((here & mask) >>> 0) === ((there & mask) >>> 0)) return ban.address;
  }
  return null;
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
