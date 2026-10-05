import { useState } from "react";
import { useApi, type Enforcement } from "../lib/api";
import { StreamEntry, when } from "../components/EnforcementLog";
import { useNav } from "../lib/nav";

type Change = {
  kind: "change";
  id: number;
  at: string | null;
  actor: string | null;
  action: string;
  target: string | null;
  summary: string | null;
  payload: string | null;
  result: string | null;
};

type Row = (Enforcement & { kind: "stream"; at: string | null }) | Change;

const KINDS = [
  { value: "all", label: "Everything" },
  { value: "streams", label: "Stream actions" },
  { value: "changes", label: "Changes" },
] as const;

/* Everything that happened, on one timeline.
 *
 * Stream actions (a rule or a person stopping playback) and changes (settings,
 * rules, devices, accounts, sharing, sign ins). Kept apart from Rules because
 * most of what lands here has nothing to do with a rule.
 */
type Options = { rules: string[]; people: string[]; outcomes: string[]; areas: string[] };

const BLANK_FILTERS = { start: "", end: "", who: "", rule: "", outcome: "", area: "", search: "" };

const AREA_LABEL: Record<string, string> = {
  settings: "Settings",
  sync: "Sync",
  device: "Devices",
  rule: "Rules",
  travel: "Sharing signals",
  user: "Users",
  account: "Accounts",
  auth: "Sign in",
  branding: "Branding",
  sharing: "Sharing",
  report: "Reports",
  library: "Library",
};

export default function LogRoute({ onOpenUser }: { onOpenUser?: (userId: number) => void }) {
  const [kind, setKind] = useState<(typeof KINDS)[number]["value"]>("all");
  const [filters, setFilters] = useState(BLANK_FILTERS);
  const options = useApi<Options>("/log/options");

  const query = new URLSearchParams({ kind, limit: "300" });
  for (const [key, value] of Object.entries(filters)) if (value) query.set(key, value);
  const rows = useApi<Row[]>(`/log?${query.toString()}`);
  const [open, setOpen] = useState<string | null>(null);

  const set = (key: keyof typeof BLANK_FILTERS) => (value: string) =>
    setFilters((f) => ({ ...f, [key]: value }));
  const narrowed = Object.values(filters).filter(Boolean).length;

  return (
    <div className="pad scroll">
      <div className="row-between">
        <h1>Log</h1>
        <div className="segmented">
          {KINDS.map((k) => (
            <button
              key={k.value}
              className={kind === k.value ? "seg on" : "seg"}
              onClick={() => setKind(k.value)}
            >
              {k.label}
            </button>
          ))}
        </div>
      </div>
      <p className="muted small">
        Streams that matched a rule or were stopped by hand, with what happened to each, and every change made through
        Cartographarr. Open an entry for the detail.
      </p>

      {/* A rule or an outcome is a question only a stream action can answer,
          and an area only a change can, so picking one narrows the timeline to
          that half rather than quietly ignoring the question. */}
      <div className="row wrap log-filters">
        <label className="log-filter">
          <span className="muted small">From</span>
          <input type="date" value={filters.start} onChange={(e) => set("start")(e.target.value)} />
        </label>
        <label className="log-filter">
          <span className="muted small">To</span>
          <input type="date" value={filters.end} onChange={(e) => set("end")(e.target.value)} />
        </label>
        <label className="log-filter">
          <span className="muted small">Person</span>
          <select value={filters.who} onChange={(e) => set("who")(e.target.value)}>
            <option value="">Anyone</option>
            {(options.data?.people ?? []).map((p) => (
              <option key={p} value={p}>
                {p}
              </option>
            ))}
          </select>
        </label>
        <label className="log-filter">
          <span className="muted small">Rule</span>
          <select value={filters.rule} onChange={(e) => set("rule")(e.target.value)}>
            <option value="">Any rule</option>
            {(options.data?.rules ?? []).map((r) => (
              <option key={r} value={r}>
                {r}
              </option>
            ))}
          </select>
        </label>
        <label className="log-filter">
          <span className="muted small">Outcome</span>
          <select value={filters.outcome} onChange={(e) => set("outcome")(e.target.value)}>
            <option value="">Any outcome</option>
            {(options.data?.outcomes ?? []).map((o) => (
              <option key={o} value={o}>
                {o}
              </option>
            ))}
          </select>
        </label>
        <label className="log-filter">
          <span className="muted small">Changed</span>
          <select value={filters.area} onChange={(e) => set("area")(e.target.value)}>
            <option value="">Anything</option>
            {(options.data?.areas ?? []).map((a) => (
              <option key={a} value={a}>
                {AREA_LABEL[a] ?? a}
              </option>
            ))}
          </select>
        </label>
        <label className="log-filter grow">
          <span className="muted small">Title</span>
          <input
            type="search"
            value={filters.search}
            placeholder="Search titles and changes"
            onChange={(e) => set("search")(e.target.value)}
          />
        </label>
        {narrowed > 0 && (
          <button className="ms-btn" onClick={() => setFilters(BLANK_FILTERS)}>
            Clear {narrowed}
          </button>
        )}
      </div>

      {rows.error && <p className="note bad-note" role="alert">{rows.error}</p>}
      {rows.data?.length === 0 && (
        <p className="muted">{narrowed > 0 ? "Nothing matches those filters." : "Nothing yet."}</p>
      )}

      <div className="log-list">
        {rows.data?.map((row) => {
          const key = `${row.kind}-${row.id}`;
          const toggle = () => setOpen(open === key ? null : key);
          return row.kind === "stream" ? (
            <StreamEntry
              key={key}
              entry={row}
              open={open === key}
              onToggle={toggle}
              onOpenUser={onOpenUser}
            />
          ) : (
            <ChangeEntry key={key} entry={row} open={open === key} onToggle={toggle} />
          );
        })}
      </div>
    </div>
  );
}

const AREA: Record<string, string> = {
  settings: "Settings",
  sync: "Sync",
  device: "Devices",
  rule: "Rules",
  travel: "Sharing signals",
  user: "Users",
  account: "Accounts",
  auth: "Sign in",
  branding: "Branding",
  sharing: "Sharing",
};

function ChangeEntry({
  entry: e,
  open,
  onToggle,
}: {
  entry: Change;
  open: boolean;
  onToggle: () => void;
}) {
  const area = AREA[e.action.split(".")[0]] ?? e.action;
  const failed = e.result && e.result !== "ok" && e.result !== "removed";

  let detail: Record<string, unknown> | null = null;
  try {
    detail = e.payload ? JSON.parse(e.payload) : null;
  } catch {
    detail = null;
  }

  return (
    <article className={open ? "log-entry open" : "log-entry"}>
      <button className="log-summary" onClick={onToggle} aria-expanded={open}>
        <span className="log-when muted small">{when(e.at)}</span>
        <span className="log-what clip">
          <strong className="clip">{e.summary ?? e.action}</strong>
          <span className="muted small">{area}</span>
        </span>
        <span className="log-by muted small clip">{e.actor ?? "Unknown"}</span>
        <span className="log-result">
          <span className={failed ? "pill bad" : "pill"}>{failed ? "failed" : "change"}</span>
        </span>
        <span className="log-caret" aria-hidden="true">
          {open ? "▴" : "▾"}
        </span>
      </button>

      {open && (
        <div className="log-detail">
          <div className="min0">
            <dl className="kv">
              <div>
                <dt>What</dt>
                <dd>{e.summary ?? e.action}</dd>
              </div>
              <div>
                <dt>Who</dt>
                <dd>{e.actor ?? "Unknown"}</dd>
              </div>
              <div>
                <dt>When</dt>
                <dd>{when(e.at, true)}</dd>
              </div>
              <div>
                <dt>Area</dt>
                <dd>{area}</dd>
              </div>
              {e.target && (
                <div>
                  <dt>Target</dt>
                  <dd>
                    <TargetLink action={e.action} target={e.target} />
                  </dd>
                </div>
              )}
              <div>
                <dt>Result</dt>
                <dd>{e.result ?? "ok"}</dd>
              </div>
            </dl>

            {detail && <DetailTable detail={detail} />}
          </div>
        </div>
      )}
    </article>
  );
}

/* What a change was about, as a link to it where there is somewhere to go.
 * Rules, sharing, settings and branding have no record page, so they open
 * their tab. */
function TargetLink({ action, target }: { action: string; target: string }) {
  const nav = useNav();
  const area = action.split(".")[0];
  const text = <code className="small">{target}</code>;
  let go: (() => void) | undefined;
  if (area === "device") go = () => nav.openDevice?.(target);
  else if (area === "user" && /^\d+$/.test(target)) go = () => nav.openUser?.(Number(target));
  else if (area === "rule") go = () => nav.goTo?.("Rules");
  else if (area === "sharing") go = () => nav.goTo?.("Sharing");
  else if (area === "travel") go = () => nav.goTo?.("Dashboard");
  else if (area === "settings" || area === "branding" || area === "account") go = () => nav.goTo?.("Settings");
  if (!go) return text;
  return (
    <button className="linkish" onClick={go}>
      {text}
    </button>
  );
}

/* Before and after where the change recorded both, otherwise the raw detail.
 * Secrets were never stored, so a changed key only says that it changed. */
function DetailTable({ detail }: { detail: Record<string, unknown> }) {
  const rows = Object.entries(detail);
  const isDiff = rows.every(
    ([, v]) => v && typeof v === "object" && ("before" in v || "after" in v || "changed" in v),
  );

  if (!isDiff) {
    return <pre className="log-json small">{JSON.stringify(detail, null, 2)}</pre>;
  }

  return (
    <table className="table log-diff">
      <thead>
        <tr>
          <th>Field</th>
          <th>Before</th>
          <th>After</th>
        </tr>
      </thead>
      <tbody>
        {rows.map(([field, v]) => {
          const change = v as { before?: unknown; after?: unknown; changed?: boolean };
          return (
            <tr key={field}>
              <td>
                <code className="small">{field}</code>
              </td>
              {change.changed ? (
                <td colSpan={2} className="muted">
                  Changed (hidden, it is a secret)
                </td>
              ) : (
                <>
                  <td className="muted">{show(change.before)}</td>
                  <td>{show(change.after)}</td>
                </>
              )}
            </tr>
          );
        })}
      </tbody>
    </table>
  );
}

function show(value: unknown): string {
  if (value === null || value === undefined || value === "") return "(empty)";
  if (typeof value === "object") return JSON.stringify(value);
  return String(value);
}
