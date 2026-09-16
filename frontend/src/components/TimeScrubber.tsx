import { useEffect, useMemo, useRef, useState } from "react";
import { useApi } from "../lib/api";
import type { FilterState } from "../lib/filters";

type Day = { day: string; plays: number };

const WINDOWS = [
  { label: "1 day", days: 1 },
  { label: "1 week", days: 7 },
  { label: "1 month", days: 30 },
  { label: "3 months", days: 90 },
];

const STEP_MS = 400;

function iso(date: Date): string {
  // Local parts, not toISOString. That converts to UTC first, so west of
  // Greenwich the filter ends up a day off from the label beside it.
  const pad = (n: number) => String(n).padStart(2, "0");
  return `${date.getFullYear()}-${pad(date.getMonth() + 1)}-${pad(date.getDate())}`;
}

function addDays(date: Date, days: number): Date {
  const out = new Date(date);
  out.setDate(out.getDate() + days);
  return out;
}

/* Move a window through time and watch the map redraw.
 *
 * It drives the same start and end filters the date pickers do, so nothing
 * downstream needs to know this exists. The shape behind it is every day in
 * the library, fetched unfiltered, so the outline stays still while the window
 * moves across it.
 */
export default function TimeScrubber({
  filters,
  onChange,
}: {
  filters: FilterState;
  onChange: (next: FilterState) => void;
}) {
  // Deliberately unfiltered: the backdrop is the whole history, so it does not
  // reshape itself every time the window moves.
  const all = useApi<Day[]>("/stats/over-time");
  const [windowDays, setWindowDays] = useState(7);
  const [playing, setPlaying] = useState(false);

  const days = all.data ?? [];
  const span = useMemo(() => {
    if (days.length === 0) return null;
    return { first: new Date(days[0].day), last: new Date(days[days.length - 1].day) };
  }, [days]);

  const totalDays = span
    ? Math.max(1, Math.round((+span.last - +span.first) / 86400000))
    : 1;

  // Position is the window's start, counted in days from the first play.
  const [offset, setOffset] = useState(0);
  const maxOffset = Math.max(0, totalDays - windowDays);

  function apply(nextOffset: number, nextWindow = windowDays) {
    if (!span) return;
    const start = addDays(span.first, nextOffset);
    onChange({ ...filters, start: iso(start), end: iso(addDays(start, nextWindow)) });
  }

  const timer = useRef<number | null>(null);
  useEffect(() => {
    if (!playing || !span) return;
    timer.current = window.setInterval(() => {
      setOffset((current) => {
        const next = current + Math.max(1, Math.round(windowDays / 7));
        if (next >= maxOffset) {
          setPlaying(false);
          return maxOffset;
        }
        return next;
      });
    }, STEP_MS);
    return () => {
      if (timer.current) window.clearInterval(timer.current);
    };
  }, [playing, span, windowDays, maxOffset]);

  // Applied here rather than inside the interval so dragging the slider and
  // playing both go through one path.
  useEffect(() => {
    if (span && (playing || offset > 0)) apply(offset);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [offset]);

  if (!span) return null;

  const windowStart = addDays(span.first, offset);
  const windowEnd = addDays(windowStart, windowDays);
  const peak = Math.max(...days.map((d) => d.plays), 1);
  const left = (offset / totalDays) * 100;
  const width = (windowDays / totalDays) * 100;

  return (
    <div className="scrubber">
      <button
        className="ms-btn"
        onClick={() => {
          if (!playing && offset >= maxOffset) setOffset(0);
          setPlaying(!playing);
        }}
        title={playing ? "Pause" : "Play through time"}
      >
        {playing ? "Pause" : "Play"}
      </button>

      <div className="scrubber-track">
        <svg viewBox={`0 0 ${Math.max(days.length, 1)} 30`} preserveAspectRatio="none">
          <path
            className="spark-fill"
            d={
              days
                .map((d, i) => `${i === 0 ? "M" : "L"} ${i} ${30 - (d.plays / peak) * 30}`)
                .join(" ") + ` L ${days.length - 1} 30 L 0 30 Z`
            }
          />
        </svg>
        <div className="scrubber-window" style={{ left: `${left}%`, width: `${width}%` }} />
        <input
          type="range"
          min={0}
          max={maxOffset}
          value={Math.min(offset, maxOffset)}
          onChange={(e) => {
            setPlaying(false);
            setOffset(Number(e.target.value));
          }}
          aria-label="Move through time"
        />
      </div>

      <select
        value={windowDays}
        onChange={(e) => {
          const next = Number(e.target.value);
          setWindowDays(next);
          apply(Math.min(offset, Math.max(0, totalDays - next)), next);
        }}
      >
        {WINDOWS.map((w) => (
          <option key={w.days} value={w.days}>
            {w.label}
          </option>
        ))}
      </select>

      <span className="muted small nowrap">
        {windowStart.toLocaleDateString()} to {windowEnd.toLocaleDateString()}
      </span>

      {(filters.start || filters.end) && (
        <button
          className="tab"
          onClick={() => {
            setPlaying(false);
            setOffset(0);
            onChange({ ...filters, start: "", end: "" });
          }}
        >
          All time
        </button>
      )}
    </div>
  );
}
