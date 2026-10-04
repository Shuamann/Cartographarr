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
export default function LogRoute({ onOpenUser }: { onOpenUser?: (userId: number) => void }) {
  const [kind, setKind] = useState<(typeof KINDS)[number]["value"]>("all");
  const rows = useApi<Row[]>(`/log?kind=${kind}&limit=300`);
  const [open, setOpen] = useState<string | null>(null);

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

      {rows.error && <p className="note bad-note" role="alert">{rows.error}</p>}
      {rows.data?.length === 0 && <p className="muted">Nothing yet.</p>}

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
