/* Thin fetch wrapper + a loading hook.
 *
 * Not a data-fetching library yet: the app has a handful of endpoints and no
 * polling. Revisit when the live-activity layer needs cache invalidation.
 */

import { useCallback, useEffect, useRef, useState } from "react";

export class ApiError extends Error {
  constructor(
    message: string,
    readonly status: number,
  ) {
    super(message);
  }
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(`/api${path}`, {
    ...init,
    headers: { "Content-Type": "application/json", ...init?.headers },
  });

  if (!res.ok) {
    // FastAPI puts the useful message in `detail`; fall back to the status.
    let message = res.statusText;
    try {
      const body = await res.json();
      if (typeof body?.detail === "string") message = body.detail;
    } catch {
      /* non-JSON error body */
    }
    throw new ApiError(message, res.status);
  }
  return res.json() as Promise<T>;
}

export const api = {
  get: <T>(path: string) => request<T>(path),
  post: <T>(path: string, body?: unknown) =>
    request<T>(path, { method: "POST", body: JSON.stringify(body ?? {}) }),
  put: <T>(path: string, body: unknown) =>
    request<T>(path, { method: "PUT", body: JSON.stringify(body) }),
};

type Query<T> = { data: T | undefined; error: string | null; loading: boolean; reload: () => void };

export function useApi<T>(path: string | null, deps: unknown[] = []): Query<T> {
  const [data, setData] = useState<T>();
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(path !== null);
  const [nonce, setNonce] = useState(0);
  // A slow response from a stale path must not overwrite a newer one.
  const latest = useRef(0);

  useEffect(() => {
    if (path === null) {
      setLoading(false);
      return;
    }
    const ticket = ++latest.current;
    setLoading(true);
    api
      .get<T>(path)
      .then((result) => {
        if (ticket !== latest.current) return;
        setData(result);
        setError(null);
      })
      .catch((err: Error) => {
        if (ticket !== latest.current) return;
        setError(err.message);
      })
      .finally(() => {
        if (ticket === latest.current) setLoading(false);
      });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [path, nonce, ...deps]);

  const reload = useCallback(() => setNonce((n) => n + 1), []);
  return { data, error, loading, reload };
}

/* ---- shapes the API returns ------------------------------------------- */

export type SetupStatus = {
  configured: boolean;
  missing: string[];
  locked: string[];
  geoip_ready: boolean;
  history_rows: number;
};

export type TautulliTest = {
  ok: boolean;
  remote: { tried: boolean; ok?: boolean; server_name?: string; version?: string; error?: string };
  local: { tried: boolean; ok?: boolean; server_name?: string; version?: string; error?: string };
};

export type Setting = {
  key: string;
  value: unknown;
  source: "environment" | "ui";
  editable: boolean;
};

export type SyncStatus = {
  running: boolean;
  history_rows: number;
  ip_locations: number;
  media_items: number;
  state: Record<string, string>;
};

export type MapPoint = {
  type: "Feature";
  geometry: { type: "Point"; coordinates: [number, number] };
  properties: {
    city: string | null;
    region: string | null;
    country: string | null;
    country_code: string | null;
    is_hosting: boolean;
    asn_org: string | null;
    plays: number;
    users: number;
    devices: number;
    ips: number;
    last_play: number | null;
  };
};

export type MapPoints = { type: "FeatureCollection"; features: MapPoint[] };
