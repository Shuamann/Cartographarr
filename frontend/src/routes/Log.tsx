import { useState } from "react";
import { useApi, type Enforcement } from "../lib/api";
import { StreamEntry, when } from "../components/EnforcementLog";

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
        Streams that were stopped, or would have been in dry run, and every change made through
        Cartographarr. Open an entry for the detail.
      </p>

      {rows.error && <p className="note bad-note">{rows.error}</p>}
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
                    <code className="small">{e.target}</code>
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
