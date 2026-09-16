import { useEffect, useRef, useState } from "react";

export type Option = { value: string | number; label: string };

type Props = {
  label: string;
  options: Option[];
  selected: (string | number)[];
  onChange: (next: (string | number)[]) => void;
};

/* A button that opens a checkbox list.
 *
 * Native <select multiple> is the lazier option and was tried first: it needs
 * ctrl-click to pick a second value, shows about four rows, and can't display
 * how many are chosen. Not worth the saved lines here, since five filters use
 * this.
 */
export default function MultiSelect({ label, options, selected, onChange }: Props) {
  const [open, setOpen] = useState(false);
  const root = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!open) return;
    function onDocument(e: MouseEvent) {
      if (!root.current?.contains(e.target as Node)) setOpen(false);
    }
    function onKey(e: KeyboardEvent) {
      if (e.key === "Escape") setOpen(false);
    }
    document.addEventListener("mousedown", onDocument);
    document.addEventListener("keydown", onKey);
    return () => {
      document.removeEventListener("mousedown", onDocument);
      document.removeEventListener("keydown", onKey);
    };
  }, [open]);

  function toggle(value: string | number) {
    onChange(
      selected.includes(value) ? selected.filter((v) => v !== value) : [...selected, value],
    );
  }

  return (
    <div className="ms" ref={root}>
      <button
        className={selected.length ? "ms-btn on" : "ms-btn"}
        onClick={() => setOpen((o) => !o)}
        aria-expanded={open}
      >
        {label}
        {selected.length > 0 && <span className="ms-count">{selected.length}</span>}
      </button>

      {open && (
        <div className="ms-menu">
          {options.length === 0 && <p className="muted ms-empty">Nothing to choose yet.</p>}
          {options.map((o) => (
            <label key={String(o.value)} className="ms-item">
              <input
                type="checkbox"
                checked={selected.includes(o.value)}
                onChange={() => toggle(o.value)}
              />
              <span>{o.label}</span>
            </label>
          ))}
          {selected.length > 0 && (
            <button className="ms-clear" onClick={() => onChange([])}>
              Clear
            </button>
          )}
        </div>
      )}
    </div>
  );
}
