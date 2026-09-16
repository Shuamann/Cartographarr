/* Thin fetch wrapper + a loading hook.
 *
 * Not a data-fetching library yet: the app has a handful of endpoints and no
 * polling. Revisit when the live-activity layer needs cache invalidation.
 */

import { useCallback, useEffect, useMemo, useRef, useState } from "react";

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
  patch: <T>(path: string, body: unknown) =>
    request<T>(path, { method: "PATCH", body: JSON.stringify(body) }),
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
    lat: number;
    lon: number;
    city: string | null;
    region: string | null;
    country: string | null;
    country_code: string | null;
    is_hosting: boolean;
    asn_org: string | null;
    accuracy_km: number | null;
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
  rating_key: number | null;
  section_id: number | null;
  transcode_decision: string | null;
  video_full_resolution: string | null;
  quality_profile: string | null;
  bandwidth: string | number | null;
  geo: {
    city: string | null;
    region: string | null;
    country: string | null;
    lat: number | null;
    lon: number | null;
    is_hosting: boolean;
    asn_org: string | null;
  } | null;
  title: string | null;
  parent_title: string | null;
  grandparent_title: string | null;
  year: string | number | null;
  summary: string | null;
  content_rating: string | null;
  view_offset: string | number | null;
  duration: string | number | null;
  container: string | null;
  stream_container: string | null;
  video_decision: string | null;
  audio_decision: string | null;
  subtitle_decision: string | null;
  video_codec: string | null;
  stream_video_codec: string | null;
  stream_video_full_resolution: string | null;
  audio_codec: string | null;
  stream_audio_codec: string | null;
  audio_channel_layout: string | null;
  stream_bitrate: string | number | null;
  secure: string | number | null;
  relayed: string | number | null;
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
  conditions?: CondGroup;
  actions?: RuleStep[];
  unmet?: string[];
};

export type CondLeaf = { type: "condition"; field: string; op: string; value: unknown };
export type CondGroup = { type: "group"; op: "and" | "or"; negate?: boolean; items: (CondLeaf | CondGroup)[] };
export type RuleStep = { name: string; params?: Record<string, unknown> };

export type RuleField = {
  key: string;
  label: string;
  group: string;
  type: "choice" | "text" | "number" | "bool" | "cidr" | "time" | "weekday";
  ops: { value: string; label: string }[];
  requires: string[];
  unmet: string[];
  hint: string | null;
  options: string | null;
  fixed: { value: string; label: string }[];
  unit: string | null;
};

export type RuleFields = {
  fields: RuleField[];
  options: Record<string, { value: string | number; label: string }[]>;
};

export type Enforcement = {
  id: number;
  rule_id: number | null;
  rule_name: string | null;
  action: string | null;
  source: "rule" | "manual" | null;
  actor: string | null;
  message: string | null;
  session_key: string | null;
  user_id: number | null;
  username: string | null;
  machine_id: string | null;
  player: string | null;
  platform: string | null;
  product: string | null;
  ip_address: string | null;
  full_title: string | null;
  media_type: string | null;
  rating_key: number | null;
  library_name: string | null;
  year: number | null;
  state: string | null;
  progress_percent: number | null;
  view_offset: number | null;
  duration: number | null;
  transcode_decision: string | null;
  video_resolution: string | null;
  quality_profile: string | null;
  bandwidth: number | null;
  location: string | null;
  city: string | null;
  region: string | null;
  country: string | null;
  is_hosting: boolean | null;
  asn_org: string | null;
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
    travel_flags: number;
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
  /** True when the numbers above describe a filtered slice rather than everything. */
  filtered: boolean;
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

export type PlexUser = {
  user_id: number;
  username: string | null;
  friendly_name: string | null;
  email: string | null;
  thumb: string | null;
  is_active: boolean;
  is_home_user: boolean;
  last_seen: number | null;
  deleted_in_tautulli?: boolean | null;
  plays?: number;
};

export type Device = {
  machine_id: string;
  user_id: number;
  player: string | null;
  platform: string | null;
  product: string | null;
  first_seen: number | null;
  last_seen: number | null;
  play_count: number;
  is_new_unreviewed: boolean;
};

export type UserDetail = PlexUser & {
  totals: {
    plays: number;
    seconds: number;
    devices: number;
    ips: number;
    first_play: number | null;
    last_play: number | null;
  };
  devices: Device[];
  places: {
    city: string | null;
    region: string | null;
    country: string | null;
    is_hosting: boolean;
    asn_org: string | null;
    plays: number;
  }[];
  top_media: { rating_key: number; title: string; plays: number }[];
};

export type HistoryRow = {
  row_id: number;
  user_id: number | null;
  machine_id: string | null;
  ip_address: string | null;
  started: number | null;
  media_type: string | null;
  rating_key: number | null;
  full_title: string | null;
  platform: string | null;
  player: string | null;
  transcode_decision: string | null;
  percent_complete: number | null;
};

export type HistoryPage = {
  total: number;
  page: number;
  size: number;
  items: HistoryRow[];
};

export type MediaDetail = {
  rating_key: number;
  title: string | null;
  full_title: string | null;
  year: number | null;
  media_type: string | null;
  summary: string | null;
  thumb: string | null;
  art: string | null;
  content_rating: string | null;
  duration: number | null;
  imdb_id: string | null;
  tmdb_id: string | null;
  tvdb_id: string | null;
  links: Record<string, string>;
  request: {
    requested_by: string | null;
    requested_at: string | null;
    status: number | null;
  } | null;
};

export type LocationDetail = {
  city: string | null;
  country: string | null;
  plays: number;
  users: { user_id: number | null; name: string; plays: number; last_play: number | null }[];
  devices: {
    machine_id: string;
    player: string | null;
    platform: string | null;
    user_id: number | null;
    plays: number;
    last_play: number | null;
  }[];
  addresses: {
    ip_address: string;
    asn_org: string | null;
    is_hosting: boolean;
    plays: number;
    last_play: number | null;
  }[];
};

/** user_id to display name, for tables that only store the id. */
export function useUserNames(): Map<number, string> {
  const users = useApi<PlexUser[]>("/users");
  return useMemo(
    () =>
      new Map(
        (users.data ?? []).map((u) => [u.user_id, u.friendly_name || u.username || String(u.user_id)]),
      ),
    [users.data],
  );
}

export type TravelFlag = {
  id: number;
  user_id: number;
  user_name: string;
  kind: "concurrent" | "travel";
  from_city: string | null;
  to_city: string | null;
  from_ip: string | null;
  to_ip: string | null;
  from_started: number | null;
  to_started: number | null;
  km: number | null;
  hours: number | null;
  kmh: number | null;
  hosting_involved: boolean;
  status: "new" | "reviewed" | "ignored";
};

export type IntegrationStatus = {
  name: string;
  label: string;
  configured: boolean;
  ok: boolean;
  detail: string;
  version: string | null;
};
