import { useEffect, useMemo, useState } from "react";
import MultiSelect from "../components/MultiSelect";
import { useBans } from "../lib/bans";
import { useNav } from "../lib/nav";
import {
  api,
  useApi,
  type ActionSpec,
  type CondGroup,
  type CondLeaf,
  type Rule,
  type RuleField,
  type RuleFields,
  type RuleStep,
  type Setting,
} from "../lib/api";

type Draft = {
  id?: number;
  name: string;
  enabled: boolean;
  conditions: CondGroup;
  actions: RuleStep[];
};

type Preview = {
  error?: string;
  unmet: string[];
  sessions: { session_key: string; full_title: string; user: string; player: string; platform: string; matched: boolean }[];
};

const MAX_DEPTH = 3;

/* What a requirement means to someone setting a rule up, and where to fix it. */
const NEEDS: Record<string, string> = {
  geoip: "a MaxMind key in Settings",
  "integration:seerr": "Seerr in Settings",
  "integration:apprise": "Apprise URLs in Settings",
  "integration:webhook": "a webhook URL in Settings",
  plex_pass: "Plex Pass",
};

function needs(unmet: string[]): string {
  return unmet.map((u) => NEEDS[u] ?? u).join(" and ");
}

const emptyGroup = (op: "and" | "or" = "and"): CondGroup => ({ type: "group", op, negate: false, items: [] });

function blankValue(field: RuleField): unknown {
  switch (field.type) {
    case "choice":
    case "weekday":
      return [];
    case "bool":
      return true;
    case "time":
      return ["22:00", "06:00"];
    default:
      return "";
  }
}

/* A rule from before condition trees, or a prefill from the device list,
 * arrives with the old flat fields. The server already converts saved rules;
 * this covers the prefill, which was never saved. */
function toDraft(rule: Partial<Rule> & { name: string }): Draft {
  let conditions = rule.conditions;
  if (!conditions) {
    conditions = emptyGroup();
    if (rule.match_machine_id) {
      conditions.items.push({ type: "condition", field: "device", op: "any", value: [rule.match_machine_id] });
    }
  }
  return {
    id: rule.id,
    name: rule.name,
    enabled: rule.enabled ?? true,
    conditions,
    actions: rule.actions?.length ? rule.actions : [{ name: rule.action ?? "terminate", params: {} }],
  };
}

export default function RulesRoute({
  prefill,
  onPrefillUsed,
}: {
  prefill?: Partial<Rule> & { name: string };
  onPrefillUsed?: () => void;
}) {
  const rules = useApi<Rule[]>("/rules");
  const actions = useApi<ActionSpec[]>("/actions");
  const catalogue = useApi<RuleFields>("/rules/fields");
  const settings = useApi<Setting[]>("/settings");
  const [draft, setDraft] = useState<Draft | null>(prefill ? toDraft(prefill) : null);

  // A Ban or Block button hands over a draft to open once. Left in place it
  // reopened the same draft every time Rules was visited, even after saving.
  useEffect(() => {
    if (prefill) onPrefillUsed?.();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const setting = (key: string) => settings.data?.find((s) => s.key === key)?.value;
  const enforcing = setting("enforce_enabled") !== false;
  const dryRun = setting("enforce_dry_run") !== false;

  async function remove(rule: Rule) {
    if (!confirm(`Delete "${rule.name}"?`)) return;
    await api.del(`/rules/${rule.id}`);
    rules.reload();
  }

  async function toggle(rule: Rule) {
    await api.put(`/rules/${rule.id}`, { enabled: !rule.enabled });
    rules.reload();
  }

  return (
    <div className="pad scroll">
      <div className="settings">
        <div className="row-between">
          <h1>Rules</h1>
          <button
            className="btn primary"
            onClick={() =>
              setDraft({
                name: "",
                enabled: true,
                conditions: emptyGroup(),
                actions: [{ name: "log_only", params: {} }],
              })
            }
          >
            New rule
          </button>
        </div>

        <p className="muted">
          Plex cannot ban one device belonging to someone you share with, so rules watch live
          playback and act on a match. Rules are checked in order and the first match wins. What
          they did is in the Log tab.
        </p>

        {!enforcing && (
          <p className="note warn-note">Rules are switched off in Settings, so none of these run.</p>
        )}
        {enforcing && dryRun && (
          <p className="note warn-note">
            Dry run is on, so rules only record what they would have done. Turn it off in Settings
            once the log looks right.
          </p>
        )}

        {draft && catalogue.data && actions.data && (
          <Editor
            draft={draft}
            onChange={setDraft}
            catalogue={catalogue.data}
            actions={actions.data}
            onDone={() => {
              setDraft(null);
              rules.reload();
            }}
          />
        )}

        <BanListCard />

        {rules.data?.length === 0 && !draft && <p className="muted">No rules yet.</p>}

        <div className="rule-list">
          {rules.data?.map((r) => (
            <div key={r.id} className={r.enabled ? "rule" : "rule off"}>
              <div className="min0">
                <div className="row">
                  <h2>{r.name}</h2>
                  {!r.enabled && <span className="pill">off</span>}
                  {r.unmet && r.unmet.length > 0 && (
                    <span className="pill warn" title={`Needs ${needs(r.unmet)}`}>
                      paused: needs {needs(r.unmet)}
                    </span>
                  )}
                </div>
                <p className="rule-when small">
                  <span className="muted">When </span>
                  {catalogue.data && r.conditions
                    ? describe(r.conditions, catalogue.data, true)
                    : "..."}
                </p>
                <p className="small">
                  <span className="muted">Then </span>
                  {(r.actions ?? []).map((step, i) => (
                    <span key={i} className="pill">
                      {actions.data?.find((a) => a.name === step.name)?.label ?? step.name}
                    </span>
                  ))}
                </p>
              </div>
              <div className="row">
                <button className="tab" onClick={() => toggle(r)}>
                  {r.enabled ? "Disable" : "Enable"}
                </button>
                <button className="tab" onClick={() => setDraft(toDraft(r))}>
                  Edit
                </button>
                <button className="tab danger-text" onClick={() => remove(r)}>
                  Delete
                </button>
              </div>
            </div>
          ))}
        </div>
      </div>
    </div>
  );
}

/* The ban list shown as the rule it is. It always runs first, and it is
 * managed from People, the map and stream cards rather than edited here. */
function BanListCard() {
  const bans = useBans();
  const nav = useNav();
  const [open, setOpen] = useState(false);

  return (
    <div className="rule system-rule">
      <div className="min0">
        <div className="row">
          <h2>Banned devices</h2>
          <span className="pill">built in, runs first</span>
          <span className={bans.list.length ? "pill banned" : "pill"}>{bans.list.length} banned</span>
        </div>
        <p className="small">
          <span className="muted">When </span>the device is on the ban list
          <span className="muted"> then </span>stop the stream, with the ban message from Settings.
        </p>
        <p className="muted small">Ban or unban a device from People, a stream card, or the map.</p>
        {open && (
          <div className="mini-list">
            {bans.list.length === 0 && <p className="muted">Nothing is banned.</p>}
            {bans.list.map((b) => (
              <div key={b.machine_id} className="mini">
                <div className="min0">
                  <button className="linkish" onClick={() => nav.openDevice?.(b.machine_id)}>
                    {b.label ?? b.machine_id}
                  </button>
                  <p className="muted small">
                    {[b.user_name, b.reason, b.banned_by ? `by ${b.banned_by}` : null].filter(Boolean).join(" \u00b7 ")}
                    {` \u00b7 ${b.attempts} attempt${b.attempts === 1 ? "" : "s"} since`}
                  </p>
                </div>
                {nav.unbanDevice && (
                  <button className="tab" onClick={() => nav.unbanDevice?.(b.machine_id, b.label ?? b.machine_id)}>
                    Unban
                  </button>
                )}
              </div>
            ))}
          </div>
        )}
      </div>
      <div className="row">
        <button className="tab" onClick={() => setOpen(!open)}>
          {open ? "Hide list" : "Show list"}
        </button>
      </div>
    </div>
  );
}

// ---- editor -----------------------------------------------------------------

function Editor({
  draft,
  onChange,
  catalogue,
  actions,
  onDone,
}: {
  draft: Draft;
  onChange: (next: Draft) => void;
  catalogue: RuleFields;
  actions: ActionSpec[];
  onDone: () => void;
}) {
  const [error, setError] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);
  const [preview, setPreview] = useState<Preview | null>(null);
  const [previewing, setPreviewing] = useState(false);

  async function save() {
    setSaving(true);
    setError(null);
    try {
      const body = {
        name: draft.name,
        enabled: draft.enabled,
        conditions: draft.conditions,
        actions: draft.actions,
      };
      if (draft.id) await api.put(`/rules/${draft.id}`, body);
      else await api.post("/rules", body);
      onDone();
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setSaving(false);
    }
  }

  async function runPreview() {
    setPreviewing(true);
    setError(null);
    try {
      setPreview(await api.post<Preview>("/rules/preview", { conditions: draft.conditions }));
    } catch (err) {
      setError((err as Error).message);
      setPreview(null);
    } finally {
      setPreviewing(false);
    }
  }

  return (
    <section className="area rule-editor">
      <header>
        <h2>{draft.id ? "Edit rule" : "New rule"}</h2>
        <p className="muted small">
          Build the conditions from the dropdowns. A group is true when all, or any, of what is
          inside it is true, and groups can sit inside groups.
        </p>
      </header>

      <div className="area-body">
        <section className="card-section">
          <div className="grid2">
            <label>
              Name
              <input
                value={draft.name}
                autoFocus
                placeholder="No remote 4K transcodes"
                onChange={(e) => onChange({ ...draft, name: e.target.value })}
              />
            </label>
            <label>
              Status
              <select
                value={String(draft.enabled)}
                onChange={(e) => onChange({ ...draft, enabled: e.target.value === "true" })}
              >
                <option value="true">On</option>
                <option value="false">Off</option>
              </select>
            </label>
          </div>
        </section>

        <section className="card-section">
          <h3>When</h3>
          <GroupEditor
            group={draft.conditions}
            depth={0}
            catalogue={catalogue}
            onChange={(conditions) => onChange({ ...draft, conditions })}
          />
          <p className="muted small rule-sentence">
            <span className="muted">Reads as: </span>
            {describe(draft.conditions, catalogue, true)}
          </p>
        </section>

        <section className="card-section">
          <h3>Then</h3>
          <ActionsEditor
            steps={draft.actions}
            specs={actions}
            onChange={(steps) => onChange({ ...draft, actions: steps })}
          />
        </section>

        <section className="card-section">
          <div className="row-between">
            <h3>Try it</h3>
            <button className="btn" onClick={runPreview} disabled={previewing}>
              {previewing ? "Checking…" : "Check against live streams"}
            </button>
          </div>
          <p className="muted small">
            Shows which of the streams playing right now this would catch. Nothing is stopped or
            logged.
          </p>
          {preview?.error && <p className="note bad-note">{preview.error}</p>}
          {preview && preview.unmet.length > 0 && (
            <p className="note warn-note">This rule cannot run until you add {needs(preview.unmet)}.</p>
          )}
          {preview && !preview.error && preview.sessions.length === 0 && (
            <p className="muted small">Nothing is playing right now.</p>
          )}
          {preview && preview.sessions.length > 0 && (
            <div className="mini-list">
              {preview.sessions.map((s) => (
                <div key={s.session_key} className="mini">
                  <div className="min0">
                    <strong className="clip">{s.full_title}</strong>
                    <p className="muted small">
                      {s.user} · {s.player} ({s.platform})
                    </p>
                  </div>
                  <span className={s.matched ? "pill warn" : "pill"}>
                    {s.matched ? "would match" : "no match"}
                  </span>
                </div>
              ))}
            </div>
          )}
        </section>

        {error && <p className="note bad-note">{error}</p>}

        <div className="row rule-editor-actions">
          <button className="btn primary" onClick={save} disabled={saving || !draft.name.trim()}>
            {saving ? "Saving…" : "Save rule"}
          </button>
          <button className="btn" onClick={onDone}>
            Cancel
          </button>
        </div>
      </div>
    </section>
  );
}

function GroupEditor({
  group,
  depth,
  catalogue,
  onChange,
  onRemove,
}: {
  group: CondGroup;
  depth: number;
  catalogue: RuleFields;
  onChange: (next: CondGroup) => void;
  onRemove?: () => void;
}) {
  const firstUsable = catalogue.fields.find((f) => f.unmet.length === 0) ?? catalogue.fields[0];

  function setItem(index: number, next: CondLeaf | CondGroup) {
    onChange({ ...group, items: group.items.map((item, i) => (i === index ? next : item)) });
  }
  function removeItem(index: number) {
    onChange({ ...group, items: group.items.filter((_, i) => i !== index) });
  }
  function addCondition() {
    onChange({
      ...group,
      items: [
        ...group.items,
        { type: "condition", field: firstUsable.key, op: firstUsable.ops[0].value, value: blankValue(firstUsable) },
      ],
    });
  }
  function addGroup() {
    // A new group defaults to the opposite of its parent, since a group of
    // the same kind inside another adds nothing.
    onChange({ ...group, items: [...group.items, emptyGroup(group.op === "and" ? "or" : "and")] });
  }

  const joiner = group.op === "and" ? "AND" : "OR";

  return (
    <div className={`cond-group depth-${depth % 2}`}>
      <div className="cond-group-head">
        <select
          value={`${group.negate ? "not-" : ""}${group.op}`}
          onChange={(e) => {
            const v = e.target.value;
            onChange({ ...group, negate: v.startsWith("not-"), op: v.endsWith("and") ? "and" : "or" });
          }}
        >
          <option value="and">All of these are true</option>
          <option value="or">Any of these is true</option>
          <option value="not-and">Not all of these are true</option>
          <option value="not-or">None of these is true</option>
        </select>
        {onRemove && (
          <button className="tab danger-text" onClick={onRemove}>
            Remove group
          </button>
        )}
      </div>

      {group.items.length === 0 && (
        <p className="muted small cond-empty">
          {depth === 0 ? "Add a condition to start. An empty rule matches nothing." : "Empty groups are ignored."}
        </p>
      )}

      {group.items.map((item, i) => (
        <div key={i} className="cond-item">
          {i > 0 && <span className={`cond-joiner ${group.op}`}>{joiner}</span>}
          {item.type === "group" ? (
            <GroupEditor
              group={item}
              depth={depth + 1}
              catalogue={catalogue}
              onChange={(next) => setItem(i, next)}
              onRemove={() => removeItem(i)}
            />
          ) : (
            <ConditionRow
              leaf={item}
              catalogue={catalogue}
              onChange={(next) => setItem(i, next)}
              onRemove={() => removeItem(i)}
            />
          )}
        </div>
      ))}

      <div className="row cond-add">
        <button className="tab" onClick={addCondition}>
          + Condition
        </button>
        <button
          className="tab"
          onClick={addGroup}
          disabled={depth + 1 >= MAX_DEPTH}
          title={depth + 1 >= MAX_DEPTH ? "Groups can only nest so deep" : "A group of conditions with its own all or any"}
        >
          + Group
        </button>
      </div>
    </div>
  );
}

function ConditionRow({
  leaf,
  catalogue,
  onChange,
  onRemove,
}: {
  leaf: CondLeaf;
  catalogue: RuleFields;
  onChange: (next: CondLeaf) => void;
  onRemove: () => void;
}) {
  const field = catalogue.fields.find((f) => f.key === leaf.field);
  const groups = useMemo(() => {
    const out: Record<string, RuleField[]> = {};
    for (const f of catalogue.fields) (out[f.group] ??= []).push(f);
    return out;
  }, [catalogue]);

  return (
    <div className={field && field.unmet.length ? "cond-row blocked" : "cond-row"}>
      <select
        value={leaf.field}
        onChange={(e) => {
          const next = catalogue.fields.find((f) => f.key === e.target.value);
          if (next) onChange({ type: "condition", field: next.key, op: next.ops[0].value, value: blankValue(next) });
        }}
      >
        {Object.entries(groups).map(([name, list]) => (
          <optgroup key={name} label={name}>
            {list.map((f) => (
              // Greyed out, not hidden, so it is clear the option exists and
              // what it takes to use it.
              <option key={f.key} value={f.key} disabled={f.unmet.length > 0 && f.key !== leaf.field}>
                {f.label}
                {f.unmet.length > 0 ? ` (needs ${needs(f.unmet)})` : ""}
              </option>
            ))}
          </optgroup>
        ))}
      </select>

      {field && (
        <select value={leaf.op} onChange={(e) => onChange({ ...leaf, op: e.target.value })}>
          {field.ops.map((o) => (
            <option key={o.value} value={o.value}>
              {o.label}
            </option>
          ))}
        </select>
      )}

      {field && <ValueEditor field={field} catalogue={catalogue} value={leaf.value} onChange={(value) => onChange({ ...leaf, value })} />}

      <button className="icon-btn" onClick={onRemove} aria-label="Remove condition" title="Remove">
        &times;
      </button>

      {field?.unmet.length ? (
        <small className="cond-hint warn-text">This rule will not run until you add {needs(field.unmet)}.</small>
      ) : field?.hint ? (
        <small className="cond-hint muted">{field.hint}</small>
      ) : null}
    </div>
  );
}

function optionsFor(field: RuleField, catalogue: RuleFields) {
  if (field.fixed.length) return field.fixed;
  return field.options ? catalogue.options[field.options] ?? [] : [];
}

function ValueEditor({
  field,
  catalogue,
  value,
  onChange,
}: {
  field: RuleField;
  catalogue: RuleFields;
  value: unknown;
  onChange: (value: unknown) => void;
}) {
  switch (field.type) {
    case "choice": {
      const options = optionsFor(field, catalogue);
      const selected = Array.isArray(value) ? (value as (string | number)[]) : [];
      const labels = selected.map((v) => options.find((o) => String(o.value) === String(v))?.label ?? String(v));
      return (
        <MultiSelect
          label={labels.length ? truncate(labels.join(", "), 38) : "Choose…"}
          options={options}
          selected={selected.map((v) => options.find((o) => String(o.value) === String(v))?.value ?? v)}
          onChange={onChange}
        />
      );
    }
    case "weekday": {
      const days = Array.isArray(value) ? (value as string[]).map(String) : [];
      return (
        <div className="row chips">
          {field.fixed.map((d) => (
            <button
              key={d.value}
              className={days.includes(d.value) ? "chip on" : "chip"}
              onClick={() =>
                onChange(days.includes(d.value) ? days.filter((x) => x !== d.value) : [...days, d.value])
              }
            >
              {d.label}
            </button>
          ))}
        </div>
      );
    }
    case "bool":
      return (
        <select value={String(value)} onChange={(e) => onChange(e.target.value === "true")}>
          <option value="true">Yes</option>
          <option value="false">No</option>
        </select>
      );
    case "number":
      return (
        <span className="row">
          <input
            type="number"
            className="cond-number"
            value={value === null || value === undefined ? "" : String(value)}
            onChange={(e) => onChange(e.target.value === "" ? "" : Number(e.target.value))}
          />
          {field.unit && <span className="muted small">{field.unit}</span>}
        </span>
      );
    case "time": {
      const [start, end] = Array.isArray(value) ? (value as string[]) : ["", ""];
      return (
        <span className="row">
          <input type="time" value={start} onChange={(e) => onChange([e.target.value, end])} />
          <span className="muted small">and</span>
          <input type="time" value={end} onChange={(e) => onChange([start, e.target.value])} />
        </span>
      );
    }
    default:
      return (
        <input
          value={String(value ?? "")}
          placeholder={field.type === "cidr" ? "203.0.113.0/24, 198.51.100.7" : ""}
          onChange={(e) => onChange(e.target.value)}
        />
      );
  }
}

function ActionsEditor({
  steps,
  specs,
  onChange,
}: {
  steps: RuleStep[];
  specs: ActionSpec[];
  onChange: (steps: RuleStep[]) => void;
}) {
  const unused = specs.filter((s) => !steps.some((step) => step.name === s.name));

  return (
    <div className="action-list">
      {steps.map((step, i) => {
        const spec = specs.find((s) => s.name === step.name);
        return (
          <div key={i} className={spec?.unmet.length ? "action-row blocked" : "action-row"}>
            <div className="row-between">
              <select
                value={step.name}
                onChange={(e) =>
                  onChange(steps.map((s, j) => (j === i ? { name: e.target.value, params: {} } : s)))
                }
              >
                {specs.map((s) => (
                  <option
                    key={s.name}
                    value={s.name}
                    disabled={(s.unmet.length > 0 || steps.some((x, j) => j !== i && x.name === s.name)) && s.name !== step.name}
                  >
                    {s.label}
                    {s.unmet.length ? ` (needs ${needs(s.unmet)})` : ""}
                  </option>
                ))}
              </select>
              {steps.length > 1 && (
                <button className="icon-btn" onClick={() => onChange(steps.filter((_, j) => j !== i))} aria-label="Remove action">
                  &times;
                </button>
              )}
            </div>
            {spec && <p className="muted small">{spec.description}</p>}
            {spec?.unmet.length ? (
              <p className="warn-text small">Will be refused until you add {needs(spec.unmet)}.</p>
            ) : null}
            {spec &&
              Object.entries(spec.param_schema).map(([key, schema]) => (
                <label key={key}>
                  {schema.label}
                  <textarea
                    rows={2}
                    value={String(step.params?.[key] ?? "")}
                    placeholder={schema.default ?? ""}
                    onChange={(e) =>
                      onChange(
                        steps.map((s, j) => (j === i ? { ...s, params: { ...s.params, [key]: e.target.value } } : s)),
                      )
                    }
                  />
                </label>
              ))}
          </div>
        );
      })}
      {unused.length > 0 && (
        <button
          className="tab"
          onClick={() => {
            const next = unused.find((s) => s.unmet.length === 0) ?? unused[0];
            onChange([...steps, { name: next.name, params: {} }]);
          }}
        >
          + Another action
        </button>
      )}
    </div>
  );
}

// ---- reading a rule back as a sentence ---------------------------------------------

function describe(group: CondGroup, catalogue: RuleFields, top = false): string {
  const parts = group.items
    .map((item) => (item.type === "group" ? describe(item, catalogue) : leafText(item, catalogue)))
    .filter(Boolean);
  if (!parts.length) return top ? "no conditions yet" : "";
  const joined = parts.join(group.op === "and" ? " AND " : " OR ");
  const wrapped = top && !group.negate ? joined : `(${joined})`;
  return group.negate ? `NOT ${wrapped}` : wrapped;
}

function leafText(leaf: CondLeaf, catalogue: RuleFields): string {
  const field = catalogue.fields.find((f) => f.key === leaf.field);
  if (!field) return leaf.field;
  const op = field.ops.find((o) => o.value === leaf.op)?.label ?? leaf.op;
  const options = optionsFor(field, catalogue);
  let value: string;
  if (Array.isArray(leaf.value)) {
    const list = leaf.value.map((v) => options.find((o) => String(o.value) === String(v))?.label ?? String(v));
    value = field.type === "time" ? list.join(" and ") : list.join(", ") || "?";
  } else if (typeof leaf.value === "boolean") {
    value = leaf.value ? "yes" : "no";
  } else {
    value = `${leaf.value ?? "?"}${field.unit ? ` ${field.unit}` : ""}`;
  }
  return `${field.label} ${op} ${value}`;
}

function truncate(text: string, length: number): string {
  return text.length > length ? `${text.slice(0, length - 1)}…` : text;
}
