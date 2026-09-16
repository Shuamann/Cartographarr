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
  del: <T>(path: string) => request<T>(path, { method: "DELETE" }),
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

export type Capabilities = {
  plex_pass: { active: boolean | null; reason: string | null };
  server: { name: string | null; version: string | null; machine_identifier: string | null };
  probed_at: number;
  stale: boolean;
  integrations: Record<string, string>;
};

export type ActionSpec = {
  name: string;
  label: string;
  description: string;
  requires: string[];
  unmet: string[];
  param_schema: Record<string, { type: string; label: string; default?: string }>;
};

export type LiveSession = {
  session_key: string;
  user_id: number | null;
  username: string | null;
  friendly_name: string | null;
  machine_id: string | null;
  player: string | null;
  platform: string | null;
  product: string | null;
  ip_address: string | null;
  location: string | null;
  state: string | null;
  progress_percent: string | number | null;
  media_type: string | null;
  full_title: string | null;
  library_name: string | null;
  transcode_decision: string | null;
  video_full_resolution: string | null;
  quality_profile: string | null;
  bandwidth: string | number | null;
  geo: {
    city: string | null;
    region: string | null;
    country: string | null;
    is_hosting: boolean;
    asn_org: string | null;
  } | null;
};

export type Activity = {
  stream_count: number | null;
  transcode_count: number | null;
  total_bandwidth: number | null;
  sessions: LiveSession[];
  error?: string;
};

export type Rule = {
  id: number;
  name: string;
  enabled: boolean;
  action: string;
  message: string | null;
  match_user_id: number | null;
  match_machine_id: string | null;
  match_player: string | null;
  match_platform: string | null;
  match_product: string | null;
  match_ip_cidr: string | null;
  match_transcode_decision: string | null;
  match_video_resolution: string | null;
  match_location: string | null;
  match_is_hosting: boolean | null;
  match_concurrent_streams_gt: number | null;
  match_paused_minutes_gt: number | null;
};

export type Enforcement = {
  rule_name: string | null;
  action: string | null;
  username: string | null;
  player: string | null;
  full_title: string | null;
  dry_run: boolean;
  result: string | null;
  acted_at: string | null;
};

export type Dashboard = {
  capabilities: Capabilities;
  settings: { enforce_enabled: boolean; enforce_dry_run: boolean };
  totals: {
    plays: number;
    users: number;
    devices: number;
    media_items: number;
    ip_locations: number;
    hosting_ips: number;
    new_devices: number;
  };
  live: {
    stream_count: number;
    transcode_count: number;
    total_bandwidth: number | null;
    sessions: LiveSession[];
    error?: string;
  };
  plays_by_day: { day: string; plays: number }[];
  top_users: { user_id: number; name: string; plays: number }[];
  recent_enforcement: Enforcement[];
  integrations: Record<string, unknown>;
};

export type AppUser = {
  id: number;
  username: string;
  email: string | null;
  role: "admin" | "viewer";
  auth_source: string;
  is_active: boolean;
  last_login: string | null;
};

export type AuthState = {
  needs_claim: boolean;
  authenticated: boolean;
  user: AppUser | null;
  proxy_enabled: boolean;
};
