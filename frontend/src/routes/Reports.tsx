import Loading from "../components/Loading";
import { useMemo, useState } from "react";
import FilterBar from "../components/FilterBar";
import { api, useApi } from "../lib/api";
import { EMPTY, fromQuery, toQuery, type FilterState } from "../lib/filters";
import { useNav } from "../lib/nav";

/* Reports: pick what to count, how to group it, and the filters.
 *
 * One builder over every source (plays, buffering, rule matches), so a new
 * question is a few dropdowns rather than a new page. Presets and saved
 * reports are the same spec, and opening one just fills the builder in.
 */

type Measure = { key: string; label: string; unit: string; hint: string | null };
type Dimension = {
  key: string;
  label: string;
  group: string;
  kind: string | null;
  hint: string | null;
  unavailable: string | null;
};
type Source = { key: string; label: string; blurb: string; measures: Measure[]; dimensions: Dimension[] };
type Spec = {
  id?: string | number;
  name: string;
  source: string;
  measure: string;
  group: string;
  then: string | null;
  range: string;
  filters?: string | null;
};
type Catalog = { sources: Source[]; presets: Spec[] };
type Saved = Spec & { id: number; created_by: string | null; updated_at: string | null };

type Row = { key: string | number | boolean | null; label: string; value: number | null; cells?: Record<string, number> };
type Result = {
  source: string;
  measure: { key: string; label: string; unit: string; additive: boolean };
  group: { key: string; label: string; kind: string | null; time: boolean };
  then: { key: string; label: string; kind: string | null } | null;
  rows: Row[];
  columns: { key: string; label: string }[];
  total: number | null;
  truncated: boolean;
  ignored: string[];
  narrowed_to_you: boolean;
};

const RANGES: { value: string; label: string }[] = [
  { value: "7", label: "Last 7 days" },
  { value: "30", label: "Last 30 days" },
  { value: "90", label: "Last 90 days" },
  { value: "365", label: "Last year" },
  { value: "all", label: "All time" },
  { value: "custom", label: "Custom dates" },
];

const FILTER_NAMES: Record<string, string> = {
  section_id: "library",
  secure: "secure",
  relayed: "relayed",
  watched: "watched",
  country_code: "country",
  player: "player",
  search: "title search",
};

const BLANK: Spec = {
  name: "New report",
  source: "plays",
  measure: "plays",
  group: "user",
  then: null,
  range: "30",
};

function daysAgo(days: number): string {
  const d = new Date();
  d.setDate(d.getDate() - days);
  const pad = (n: number) => String(n).padStart(2, "0");
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}`;
}

/* The filter state a spec opens with: its saved filters, plus its range. */
function filtersFor(spec: Spec): FilterState {
  const base = spec.filters ? fromQuery(spec.filters) : { ...EMPTY };
  if (spec.range === "custom") return base;
  return { ...base, start: spec.range === "all" ? "" : daysAgo(Number(spec.range)), end: "" };
}

/* Filters to store with a saved report. Dates only for a custom range; a
 * relative range is worked out again whenever the report is opened. */
function filtersToSave(filters: FilterState, range: string): string | null {
  const kept = range === "custom" ? filters : { ...filters, start: "", end: "" };
  const q = toQuery(kept);
  return q ? q.slice(1) : null;
}

export default function Reports() {
  const nav = useNav();
  const catalog = useApi<Catalog>("/reports/catalog");
  const saved = useApi<Saved[]>("/reports/saved");

  const [spec, setSpec] = useState<Spec>(BLANK);
  const [filters, setFilters] = useState<FilterState>(() => filtersFor(BLANK));
  const [openId, setOpenId] = useState<string | number | null>(null);
  const [status, setStatus] = useState<string | null>(null);

  const sources = catalog.data?.sources ?? [];
  const source = sources.find((s) => s.key === spec.source) ?? sources[0];

  function open(next: Spec) {
    setSpec({ ...next, then: next.then ?? null });
    setFilters(filtersFor(next));
    setOpenId(next.id ?? null);
    setStatus(null);
  }

  // Changing the source keeps whatever still applies and resets the rest.
  function setSource(key: string) {
    const s = sources.find((x) => x.key === key);
    if (!s) return;
    const has = (d: string | null) => d !== null && s.dimensions.some((x) => x.key === d);
    setSpec({
      ...spec,
      source: key,
      measure: s.measures.some((m) => m.key === spec.measure) ? spec.measure : s.measures[0].key,
      group: has(spec.group) ? spec.group : s.dimensions[0].key,
      then: has(spec.then) ? spec.then : null,
    });
  }

  function setRange(range: string) {
    setSpec({ ...spec, range });
    if (range !== "custom") {
      setFilters({ ...filters, start: range === "all" ? "" : daysAgo(Number(range)), end: "" });
    }
  }

  function onFilters(next: FilterState) {
    // Picking dates by hand makes the range custom, so the two never disagree.
    if (next.start !== filters.start || next.end !== filters.end) setSpec((s) => ({ ...s, range: "custom" }));
    setFilters(next);
  }

  const query = useMemo(() => {
    if (!source) return null;
    const p = new URLSearchParams(toQuery(filters).slice(1));
    p.set("source", spec.source);
    p.set("measure", spec.measure);
    p.set("group", spec.group);
    if (spec.then) p.set("then", spec.then);
    p.set("limit", "50");
    return `/reports/run?${p.toString()}`;
  }, [source, spec.source, spec.measure, spec.group, spec.then, filters]);

  const result = useApi<Result>(query);

  const savedRow = typeof openId === "number" ? saved.data?.find((r) => r.id === openId) : undefined;

  async function save(asNew: boolean) {
    const name = prompt("Name this report", asNew || !savedRow ? (spec.name === BLANK.name ? "" : spec.name) : savedRow.name);
    if (!name?.trim()) return;
    const body = { ...spec, name: name.trim(), filters: filtersToSave(filters, spec.range) };
    try {
      const row =
        !asNew && savedRow
          ? await api.put<Saved>(`/reports/saved/${savedRow.id}`, body)
          : await api.post<Saved>("/reports/saved", body);
      saved.reload();
      setSpec({ ...spec, name: row.name });
      setOpenId(row.id);
      setStatus(`Saved as "${row.name}".`);
    } catch (e) {
      setStatus((e as Error).message);
    }
  }

  async function remove() {
    if (!savedRow || !confirm(`Delete the saved report "${savedRow.name}"?`)) return;
    await api.del(`/reports/saved/${savedRow.id}`);
    saved.reload();
    open(BLANK);
  }

  if (catalog.error) return <p className="note bad-note pad">{catalog.error}</p>;
  if (!source) return <div className="pad"><Loading /></div>;

  return (
    <div className="settings-layout">
      <nav className="settings-nav" aria-label="Reports">
        <h1>Reports</h1>
        <div className="settings-nav-group">
          <button
            className={openId === null ? "settings-nav-item on" : "settings-nav-item"}
            onClick={() => open(BLANK)}
          >
            <span>New report</span>
          </button>
        </div>
        {(saved.data?.length ?? 0) > 0 && (
          <div className="settings-nav-group">
            <span className="settings-nav-label">Saved</span>
            {saved.data!.map((r) => (
              <button
                key={r.id}
                className={openId === r.id ? "settings-nav-item on" : "settings-nav-item"}
                onClick={() => open(r)}
              >
                <span>{r.name}</span>
              </button>
            ))}
          </div>
        )}
        <div className="settings-nav-group">
          <span className="settings-nav-label">Starting points</span>
          {catalog.data!.presets.map((p) => (
            <button
              key={p.id}
              className={openId === p.id ? "settings-nav-item on" : "settings-nav-item"}
              onClick={() => open(p)}
            >
              <span>{p.name}</span>
            </button>
          ))}
        </div>
      </nav>

      <div className="settings-page">
        <header className="settings-page-head row-between">
          <div>
            <h2>{spec.name}</h2>
            <p className="muted">{source.blurb}</p>
          </div>
          <div className="report-actions">
            <button className="btn" onClick={() => result.data && downloadCsv(spec.name, result.data)} disabled={!result.data?.rows.length}>
              Download CSV
            </button>
            {nav.isAdmin && savedRow && (
              <>
                <button className="btn danger" onClick={remove}>
                  Delete
                </button>
                <button className="btn" onClick={() => save(true)}>
                  Save as new
                </button>
              </>
            )}
            {nav.isAdmin && (
              <button className="btn primary" onClick={() => save(false)}>
                {savedRow ? "Save changes" : "Save report"}
              </button>
            )}
          </div>
        </header>
        {status && <p className="note">{status}</p>}

        <section className="report-builder">
          <label>
            <span>Report on</span>
            <select value={spec.source} onChange={(e) => setSource(e.target.value)}>
              {sources.map((s) => (
                <option key={s.key} value={s.key}>
                  {s.label}
                </option>
              ))}
            </select>
          </label>
          <label>
            <span>Measure</span>
            <select value={spec.measure} onChange={(e) => setSpec({ ...spec, measure: e.target.value })}>
              {source.measures.map((m) => (
                <option key={m.key} value={m.key} title={m.hint ?? undefined}>
                  {m.label}
                </option>
              ))}
            </select>
          </label>
          <label>
            <span>Group by</span>
            <DimensionSelect
              dimensions={source.dimensions}
              value={spec.group}
              exclude={spec.then}
              onChange={(v) => setSpec({ ...spec, group: v ?? spec.group })}
            />
          </label>
          <label>
            <span>Split by</span>
            <DimensionSelect
              dimensions={source.dimensions}
              value={spec.then}
              exclude={spec.group}
              optional
              onChange={(v) => setSpec({ ...spec, then: v })}
            />
          </label>
          <label>
            <span>Time</span>
            <select value={spec.range} onChange={(e) => setRange(e.target.value)}>
              {RANGES.map((r) => (
                <option key={r.value} value={r.value}>
                  {r.label}
                </option>
              ))}
            </select>
          </label>
        </section>

        <FilterBar value={filters} onChange={onFilters} />

        {result.error && <p className="note bad-note">{result.error}</p>}
        {result.data && <ResultView result={result.data} loading={result.loading} />}
      </div>
    </div>
  );
}

function DimensionSelect({
  dimensions,
  value,
  exclude,
  optional,
  onChange,
}: {
  dimensions: Dimension[];
  value: string | null;
  exclude: string | null;
  optional?: boolean;
  onChange: (value: string | null) => void;
}) {
  const groups = [...new Set(dimensions.map((d) => d.group))];
  return (
    <select value={value ?? ""} onChange={(e) => onChange(e.target.value || null)}>
      {optional && <option value="">Nothing</option>}
      {groups.map((g) => (
        <optgroup key={g} label={g}>
          {dimensions
            .filter((d) => d.group === g)
            .map((d) => (
              <option
                key={d.key}
                value={d.key}
                disabled={d.key === exclude || Boolean(d.unavailable)}
                title={d.unavailable ?? d.hint ?? undefined}
              >
                {d.label}
                {d.unavailable ? ` (${d.unavailable.toLowerCase()})` : ""}
              </option>
            ))}
        </optgroup>
      ))}
    </select>
  );
}

export function formatValue(value: number | null | undefined, unit: string): string {
  if (value === null || value === undefined) return "";
  const n = (digits: number) => value.toLocaleString(undefined, { maximumFractionDigits: digits });
  switch (unit) {
    case "hours":
      return `${n(1)} h`;
    case "minutes":
      return `${n(1)} min`;
    case "seconds":
      return `${n(0)} s`;
    case "percent":
      return `${n(0)}%`;
    case "kbps":
      return `${n(0)} kbps`;
    case "mbps":
      return `${n(1)} Mbps`;
    default:
      return n(2);
  }
}

function ResultView({ result, loading }: { result: Result; loading: boolean }) {
  const { measure, group, then, rows, columns } = result;
  const stacked = Boolean(then) && measure.additive && columns.length > 0;
  const ignored = result.ignored.map((f) => FILTER_NAMES[f] ?? f.replace(/_/g, " "));

  return (
    <div className={loading ? "report-result loading" : "report-result"}>
      <p className="report-summary">
        <strong>{formatValue(result.total, measure.unit) || "0"}</strong>{" "}
        <span className="muted">
          {measure.label.toLowerCase()} in total
          {result.truncated ? `, showing the top ${rows.length} by ${group.label.toLowerCase()}` : ""}
        </span>
      </p>
      {ignored.length > 0 && (
        <p className="note">This source has no {ignored.join(", ")} to filter on, so those filters were not applied.</p>
      )}
      {result.narrowed_to_you && <p className="note">This report only covers your own plays.</p>}

      {rows.length === 0 ? (
        <p className="muted">
          Nothing matches.
          {["buffering", "streams", "server"].includes(result.source) &&
            " This is recorded from live activity from when this version was installed, so it starts empty."}
        </p>
      ) : (
        <>
          {stacked && <Legend columns={columns} />}
          {group.time ? (
            <ColumnChart result={result} stacked={stacked} />
          ) : (
            <BarList result={result} stacked={stacked} />
          )}
          <ReportTable result={result} />
        </>
      )}
    </div>
  );
}

function Legend({ columns }: { columns: Result["columns"] }) {
  return (
    <div className="report-legend">
      {columns.map((c, i) => (
        <span key={c.key}>
          <i style={{ background: seriesColor(i) }} />
          {c.label}
        </span>
      ))}
    </div>
  );
}

function seriesColor(i: number): string {
  return `var(--chart-${(i % 8) + 1})`;
}

function RowLabel({ row, kind }: { row: Row; kind: string | null }) {
  const nav = useNav();
  const key = row.key;
  const link = (() => {
    if (key === null || key === undefined || key === "") return null;
    if (kind === "user" && nav.openUser) return () => nav.openUser!(Number(key));
    if (kind === "device" && nav.openDevice) return () => nav.openDevice!(String(key));
    if (kind === "address" && nav.openAddress) return () => nav.openAddress!(String(key));
    if (kind === "media" && nav.filterTo)
      return () => nav.filterTo!("History", { rating_key: Number(key), ratingKeyLabel: row.label });
    return null;
  })();
  return link ? (
    <button className="linkish" onClick={link} title={row.label}>
      {row.label}
    </button>
  ) : (
    <span title={row.label}>{row.label}</span>
  );
}

function BarList({ result, stacked }: { result: Result; stacked: boolean }) {
  const max = Math.max(...result.rows.map((r) => r.value ?? 0), 0) || 1;
  return (
    <div className="report-bars">
      {result.rows.map((row) => (
        <div className="report-bar-row" key={String(row.key)}>
          <div className="report-bar-label">
            <RowLabel row={row} kind={result.group.kind} />
          </div>
          <div className="report-bar-track">
            {stacked ? (
              result.columns.map((c, i) => {
                const v = row.cells?.[String(c.key)] ?? 0;
                return v ? (
                  <span
                    key={c.key}
                    className="report-bar-fill"
                    style={{ width: `${(v / max) * 100}%`, background: seriesColor(i) }}
                    title={`${c.label}: ${formatValue(v, result.measure.unit)}`}
                  />
                ) : null;
              })
            ) : (
              <span className="report-bar-fill" style={{ width: `${((row.value ?? 0) / max) * 100}%` }} />
            )}
          </div>
          <div className="report-bar-value">{formatValue(row.value, result.measure.unit)}</div>
        </div>
      ))}
    </div>
  );
}

/* Time along the bottom. Inline SVG, like the dashboard sparkline. */
function ColumnChart({ result, stacked }: { result: Result; stacked: boolean }) {
  const rows = result.rows;
  const max = Math.max(...rows.map((r) => r.value ?? 0), 0) || 1;
  const width = 800;
  const height = 220;
  const gap = rows.length > 60 ? 1 : 3;
  const w = width / rows.length;
  const every = Math.ceil(rows.length / 12);
  return (
    <svg className="report-columns" viewBox={`0 0 ${width} ${height + 22}`} role="img" aria-label={result.measure.label}>
      {rows.map((row, i) => {
        const x = i * w + gap / 2;
        const bw = Math.max(w - gap, 1);
        const title = `${row.label}: ${formatValue(row.value, result.measure.unit)}`;
        let y = height;
        return (
          <g key={String(row.key)}>
            <title>{title}</title>
            {stacked ? (
              result.columns.map((c, ci) => {
                const v = row.cells?.[String(c.key)] ?? 0;
                const h = (v / max) * height;
                y -= h;
                return v ? <rect key={c.key} x={x} y={y} width={bw} height={h} fill={seriesColor(ci)} /> : null;
              })
            ) : (
              <rect
                x={x}
                y={height - ((row.value ?? 0) / max) * height}
                width={bw}
                height={((row.value ?? 0) / max) * height}
                className="report-column"
              />
            )}
            {i % every === 0 && (
              <text x={x + bw / 2} y={height + 16} textAnchor="middle" className="report-axis">
                {row.label}
              </text>
            )}
          </g>
        );
      })}
    </svg>
  );
}

function ReportTable({ result }: { result: Result }) {
  const { group, measure, columns, rows, then } = result;
  return (
    <div className="report-table-wrap">
      <table className="table locations report-table">
        <thead>
          <tr>
            <th>{group.label}</th>
            {then && columns.map((c) => <th key={c.key} className="num">{c.label}</th>)}
            <th className="num">{then ? "All" : measure.label}</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((row) => (
            <tr key={String(row.key)}>
              <td>
                <RowLabel row={row} kind={group.kind} />
              </td>
              {then &&
                columns.map((c) => (
                  <td key={c.key} className="num">
                    {formatValue(row.cells?.[String(c.key)], measure.unit)}
                  </td>
                ))}
              <td className="num">
                <strong>{formatValue(row.value, measure.unit)}</strong>
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function downloadCsv(name: string, result: Result) {
  const { group, measure, columns, rows, then } = result;
  const esc = (v: unknown) => {
    const s = v === null || v === undefined ? "" : String(v);
    return /[",\n]/.test(s) ? `"${s.replace(/"/g, '""')}"` : s;
  };
  const header = [group.label, ...(then ? columns.map((c) => `${then.label}: ${c.label}`) : []), `${measure.label} (${measure.unit})`];
  const lines = [header.map(esc).join(",")];
  for (const row of rows) {
    lines.push(
      [row.label, ...(then ? columns.map((c) => row.cells?.[String(c.key)] ?? "") : []), row.value ?? ""].map(esc).join(","),
    );
  }
  const blob = new Blob([lines.join("\n")], { type: "text/csv" });
  const a = document.createElement("a");
  a.href = URL.createObjectURL(blob);
  a.download = `${name.replace(/[^\w -]+/g, "").trim() || "report"}.csv`;
  a.click();
  setTimeout(() => URL.revokeObjectURL(a.href), 1000);
}
