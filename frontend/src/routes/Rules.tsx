import { useState } from "react";
import { api, useApi, type ActionSpec, type Enforcement, type Rule } from "../lib/api";

type Draft = Partial<Rule> & { name: string };

const MATCHERS: { key: keyof Rule; label: string; placeholder?: string; hint?: string }[] = [
  { key: "match_machine_id", label: "Device ID", placeholder: "machine_id", hint: "Survives player renames, so it is the reliable way to target one device" },
  { key: "match_user_id", label: "User ID", placeholder: "123" },
  { key: "match_player", label: "Player name", placeholder: "Living Room TV", hint: "The viewer can change this" },
  { key: "match_platform", label: "Platform", placeholder: "Roku" },
  { key: "match_product", label: "Product", placeholder: "Plex for Roku" },
  { key: "match_ip_cidr", label: "IP or range", placeholder: "203.0.113.5 or 203.0.113.0/24" },
  { key: "match_transcode_decision", label: "Playback", placeholder: "transcode" },
  { key: "match_video_resolution", label: "Resolution", placeholder: "4k" },
  { key: "match_location", label: "Location", placeholder: "wan" },
  { key: "match_concurrent_streams_gt", label: "More streams than", placeholder: "2" },
  { key: "match_paused_minutes_gt", label: "Paused over (min)", placeholder: "30" },
];

export default function RulesRoute() {
  const rules = useApi<Rule[]>("/rules");
  const actions = useApi<ActionSpec[]>("/actions");
  const logEntries = useApi<Enforcement[]>("/enforcement-log?limit=50");
  const [draft, setDraft] = useState<Draft | null>(null);
  const [error, setError] = useState<string | null>(null);

  const dryRun = logEntries.data?.some((e) => e.dry_run) ?? true;

  async function save() {
    if (!draft) return;
    setError(null);
    try {
      const body = Object.fromEntries(
        Object.entries(draft).filter(([, v]) => v !== "" && v !== undefined),
      );
      if (draft.id) await api.put(`/rules/${draft.id}`, body);
      else await api.post("/rules", body);
      setDraft(null);
      rules.reload();
    } catch (err) {
      setError((err as Error).message);
    }
  }

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
      <div className="row-between">
        <h1>Rules</h1>
        <button className="btn primary" onClick={() => setDraft({ name: "", action: "terminate" })}>
          New rule
        </button>
      </div>

      <p className="muted">
        Plex can't ban a shared user's device, so rules work by watching live playback and acting
        on a match. Conditions are combined with AND; the first matching rule wins.
      </p>

      {dryRun && (
        <p className="note warn-note">
          Dry run is on, so rules only record what they would have done. Turn off
          <code> ENFORCE_DRY_RUN </code> once the log looks right.
        </p>
      )}

      {rules.data?.length === 0 && <p className="muted">No rules yet.</p>}

      <div className="rule-list">
        {rules.data?.map((r) => (
          <div key={r.id} className={r.enabled ? "rule" : "rule off"}>
            <div>
              <h2>{r.name}</h2>
              <p className="muted small">
                {MATCHERS.filter((m) => r[m.key] !== null && r[m.key] !== "")
                  .map((m) => `${m.label}: ${r[m.key]}`)
                  .join("  ·  ") || "no conditions"}
              </p>
              <p className="muted small">
                <span className="pill">{r.action}</span>
                {r.message && <> “{r.message}”</>}
              </p>
            </div>
            <div className="row">
              <button className="tab" onClick={() => toggle(r)}>
                {r.enabled ? "Disable" : "Enable"}
              </button>
              <button className="tab" onClick={() => setDraft(r)}>Edit</button>
              <button className="tab danger-text" onClick={() => remove(r)}>Delete</button>
            </div>
          </div>
        ))}
      </div>

      {draft && (
        <div className="editor">
          <h2>{draft.id ? "Edit rule" : "New rule"}</h2>

          <label>
            Name
            <input
              value={draft.name}
              autoFocus
              onChange={(e) => setDraft({ ...draft, name: e.target.value })}
            />
          </label>

          <h3>Conditions</h3>
          <p className="muted small">Leave blank to ignore. At least one is required.</p>
          <div className="grid2">
            {MATCHERS.map((m) => (
              <label key={m.key}>
                {m.label}
                <input
                  placeholder={m.placeholder}
                  value={(draft[m.key] as string | number | null) ?? ""}
                  onChange={(e) => setDraft({ ...draft, [m.key]: e.target.value })}
                />
                {m.hint && <small>{m.hint}</small>}
              </label>
            ))}
          </div>

          <h3>Action</h3>
          <div className="row wrap">
            {actions.data?.map((a) => (
              <button
                key={a.name}
                className={draft.action === a.name ? "ms-btn on" : "ms-btn"}
                disabled={a.unmet.length > 0}
                title={a.unmet.length ? `Needs ${a.unmet.join(", ")}` : a.description}
                onClick={() => setDraft({ ...draft, action: a.name })}
              >
                {a.label}
              </button>
            ))}
          </div>
          {actions.data
            ?.filter((a) => a.name === draft.action)
            .map((a) => (
              <p key={a.name} className="muted small">
                {a.description}
                {a.unmet.length > 0 && `, unavailable: ${a.unmet.join(", ")}`}
              </p>
            ))}

          {draft.action === "terminate" && (
            <label>
              Message shown to the viewer
              <textarea
                rows={2}
                value={draft.message ?? ""}
                placeholder="This device is not permitted to stream."
                onChange={(e) => setDraft({ ...draft, message: e.target.value })}
              />
            </label>
          )}

          {error && <p className="note bad-note">{error}</p>}

          <div className="row">
            <button className="btn primary" onClick={save} disabled={!draft.name.trim()}>
              Save
            </button>
            <button className="btn" onClick={() => setDraft(null)}>Cancel</button>
          </div>
        </div>
      )}

      <h2 className="section-head">Enforcement log</h2>
      {logEntries.data?.length === 0 && <p className="muted">Nothing yet.</p>}
      <table className="table">
        <tbody>
          {logEntries.data?.map((e, i) => (
            <tr key={i}>
              <td className="muted small">
                {e.acted_at ? new Date(e.acted_at).toLocaleString() : ""}
              </td>
              <td>{e.rule_name}</td>
              <td>{e.username}</td>
              <td className="muted">{e.player}</td>
              <td className="muted">{e.full_title}</td>
              <td>
                <span className={e.dry_run ? "pill" : "pill warn"}>
                  {e.dry_run ? "dry run" : "acted"}
                </span>{" "}
                {e.result}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
