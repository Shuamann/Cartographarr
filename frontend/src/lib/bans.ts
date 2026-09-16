import { useEffect, useMemo } from "react";
import { api, useApi } from "./api";

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
};

/* Every component that shows a Ban or Unban button reads the list from here,
 * and every change announces itself, so a ban made on the map shows up on the
 * People page without a reload. */
const CHANGED = "cartographarr:bans-changed";

export function useBans() {
  const bans = useApi<Ban[]>("/bans");
  useEffect(() => {
    const reload = () => bans.reload();
    window.addEventListener(CHANGED, reload);
    return () => window.removeEventListener(CHANGED, reload);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);
  const ids = useMemo(() => new Set((bans.data ?? []).map((b) => b.machine_id)), [bans.data]);
  return { list: bans.data ?? [], ids, loading: bans.loading, error: bans.error };
}

export async function ban(machineId: string, reason: string): Promise<void> {
  await api.post("/bans", { machine_id: machineId, reason });
  window.dispatchEvent(new Event(CHANGED));
}

export async function unban(machineId: string): Promise<void> {
  await api.del(`/bans/${encodeURIComponent(machineId)}`);
  window.dispatchEvent(new Event(CHANGED));
}
