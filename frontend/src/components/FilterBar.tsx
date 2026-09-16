import { useEffect, useState } from "react";
import { useApi } from "../lib/api";
import { activeCount, EMPTY, type FilterState } from "../lib/filters";
import MultiSelect, { type Option } from "./MultiSelect";

type Library = { section_id: number; name: string | null };
type User = { user_id: number; friendly_name: string | null; username: string | null };
type Options = {
  media_type: string[];
  platform: string[];
  product: string[];
  transcode_decision: string[];
  location: string[];
  country_code: string[];
};
type Title = { rating_key: number; title: string; year: number | null };

type Props = { value: FilterState; onChange: (next: FilterState) => void };

export default function FilterBar({ value, onChange }: Props) {
  const options = useApi<Options>("/filter-options");
  const users = useApi<User[]>("/users");
  const libraries = useApi<Library[]>("/libraries");

  const set = <K extends keyof FilterState>(key: K, v: FilterState[K]) =>
    onChange({ ...value, [key]: v });

  const list = (values: string[]): Option[] => values.map((v) => ({ value: v, label: v }));
  const active = activeCount(value);

  return (
    <div className="filters">
      <input
        type="date"
        aria-label="From"
        value={value.start}
        max={value.end || undefined}
        onChange={(e) => set("start", e.target.value)}
      />
      <span className="muted">to</span>
      <input
        type="date"
        aria-label="To"
        value={value.end}
        min={value.start || undefined}
        onChange={(e) => set("end", e.target.value)}
      />
      {(value.start || value.end) && (
        <button
          className="icon-btn"
          title="Clear the dates"
          aria-label="Clear the dates"
          onClick={() => onChange({ ...value, start: "", end: "" })}
        >
          ✕
        </button>
      )}

      <MultiSelect
        label="User"
        options={(users.data ?? []).map((u) => ({
          value: u.user_id,
          label: u.friendly_name || u.username || String(u.user_id),
        }))}
        selected={value.user_id}
        onChange={(v) => set("user_id", v as number[])}
      />

      {/* Set from a device profile rather than picked here, since two hundred
          device ids make a poor dropdown. Shown so it can be seen and cleared. */}
      {value.machine_id.length > 0 && (
        <button
          className="ms-btn on"
          title="Clear the device filter"
          onClick={() => onChange({ ...value, machine_id: [], machineLabel: null })}
        >
          Device: {value.machineLabel ?? value.machine_id.length} ✕
        </button>
      )}

      <MultiSelect
        label="Library"
        options={(libraries.data ?? []).map((l) => ({
          value: l.section_id,
          label: l.name ?? `Section ${l.section_id}`,
        }))}
        selected={value.section_id}
        onChange={(v) => set("section_id", v as number[])}
      />

      <MultiSelect
        label="Type"
        options={list(options.data?.media_type ?? [])}
        selected={value.media_type}
        onChange={(v) => set("media_type", v as string[])}
      />

      <MultiSelect
        label="Platform"
        options={list(options.data?.platform ?? [])}
        selected={value.platform}
        onChange={(v) => set("platform", v as string[])}
      />

      <MultiSelect
        label="Playback"
        options={list(options.data?.transcode_decision ?? [])}
        selected={value.transcode_decision}
        onChange={(v) => set("transcode_decision", v as string[])}
      />

      <button
        className={value.is_hosting ? "ms-btn on" : "ms-btn"}
        title="Only streams coming from a hosting or VPN provider"
        onClick={() => set("is_hosting", value.is_hosting ? null : true)}
      >
        VPN only
      </button>

      <TitlePicker value={value} onChange={onChange} />

      <SearchBox value={value.search} onChange={(v) => set("search", v)} />

      <button
        className="ms-btn clear-all"
        onClick={() => onChange(EMPTY)}
        disabled={active === 0}
        title={active === 0 ? "No filters set" : "Clear every filter"}
      >
        Reset{active > 0 && <span className="ms-count">{active}</span>}
      </button>
    </div>
  );
}

/* Typing shouldn't fire a request per keystroke. */
function SearchBox({ value, onChange }: { value: string; onChange: (v: string) => void }) {
  const [draft, setDraft] = useState(value);

  // Keep in step when the parent resets filters.
  useEffect(() => setDraft(value), [value]);

  useEffect(() => {
    if (draft === value) return;
    const timer = setTimeout(() => onChange(draft), 300);
    return () => clearTimeout(timer);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [draft]);

  return (
    <input
      className="search"
      type="search"
      placeholder="Search titles…"
      value={draft}
      onChange={(e) => setDraft(e.target.value)}
    />
  );
}

/* Pick one title and the map repaints to only its plays, including every
 * episode when a show is chosen, which the backend handles. */
function TitlePicker({ value, onChange }: Props) {
  const [query, setQuery] = useState("");
  const [debounced, setDebounced] = useState("");
  const [open, setOpen] = useState(false);

  useEffect(() => {
    const timer = setTimeout(() => setDebounced(query), 300);
    return () => clearTimeout(timer);
  }, [query]);

  const results = useApi<Title[]>(
    debounced.trim().length >= 2 ? `/media/search?q=${encodeURIComponent(debounced.trim())}` : null,
  );

  if (value.rating_key !== null) {
    return (
      <button
        className="ms-btn on"
        title="Clear title filter"
        onClick={() => onChange({ ...value, rating_key: null, ratingKeyLabel: null })}
      >
        {value.ratingKeyLabel} ✕
      </button>
    );
  }

  return (
    <div className="ms">
      <input
        className="search"
        placeholder="One title…"
        value={query}
        onFocus={() => setOpen(true)}
        onChange={(e) => {
          setQuery(e.target.value);
          setOpen(true);
        }}
      />
      {open && results.data && results.data.length > 0 && (
        <div className="ms-menu wide">
          {results.data.map((t) => (
            <button
              key={t.rating_key}
              className="ms-item as-button"
              onClick={() => {
                onChange({ ...value, rating_key: t.rating_key, ratingKeyLabel: t.title });
                setQuery("");
                setOpen(false);
              }}
            >
              {t.title}
              {t.year ? <span className="muted"> {t.year}</span> : null}
            </button>
          ))}
        </div>
      )}
    </div>
  );
}
