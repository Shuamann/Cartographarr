import { useMemo, useState, type ReactNode } from "react";

export type Column<T> = {
  key: string;
  label: string;
  numeric?: boolean;
  /** Value used for sorting. Omit to make the column unsortable. */
  sort?: (row: T) => string | number;
  render: (row: T) => ReactNode;
};

type Props<T> = {
  rows: T[];
  columns: Column<T>[];
  rowKey: (row: T) => string | number;
  initialSort?: string;
  initialAscending?: boolean;
  onRowClick?: (row: T) => void;
  isSelected?: (row: T) => boolean;
  empty?: string;
};

/* Sortable table, shared by Users, Devices and History.
 *
 * Client-side sorting: these pages fetch a page at a time and a few hundred
 * rows sort instantly. History paginates server-side because it does not.
 */
export default function DataTable<T>({
  rows,
  columns,
  rowKey,
  initialSort,
  initialAscending = false,
  onRowClick,
  isSelected,
  empty = "Nothing to show.",
}: Props<T>) {
  const [sort, setSort] = useState(initialSort ?? columns[0].key);
  const [ascending, setAscending] = useState(initialAscending);

  const sorted = useMemo(() => {
    const column = columns.find((c) => c.key === sort);
    if (!column?.sort) return rows;
    const get = column.sort;
    return [...rows].sort((a, b) => {
      const [x, y] = [get(a), get(b)];
      const cmp = typeof x === "string" ? x.localeCompare(y as string) : (x as number) - (y as number);
      return ascending ? cmp : -cmp;
    });
  }, [rows, columns, sort, ascending]);

  if (rows.length === 0) return <p className="muted">{empty}</p>;

  return (
    <table className="table locations">
      <thead>
        <tr>
          {columns.map((c) => {
            const active = sort === c.key;
            return (
              <th
                key={c.key}
                className={`${c.numeric ? "num " : ""}${active ? "sorted" : ""}`}
                onClick={() => {
                  if (!c.sort) return;
                  if (active) setAscending(!ascending);
                  else {
                    setSort(c.key);
                    setAscending(Boolean(c.numeric) === false);
                  }
                }}
                style={c.sort ? undefined : { cursor: "default" }}
              >
                {c.label}
                {active && c.sort && <span className="caret">{ascending ? "▲" : "▼"}</span>}
              </th>
            );
          })}
        </tr>
      </thead>
      <tbody>
        {sorted.map((row) => (
          <tr
            key={rowKey(row)}
            className={`${onRowClick ? "loc-row" : ""} ${isSelected?.(row) ? "selected" : ""}`}
            onClick={onRowClick ? () => onRowClick(row) : undefined}
          >
            {columns.map((c) => (
              <td key={c.key} className={c.numeric ? "num" : undefined}>
                {c.render(row)}
              </td>
            ))}
          </tr>
        ))}
      </tbody>
    </table>
  );
}

export function duration(seconds: number | null | undefined): string {
  if (!seconds) return "0m";
  const hours = Math.floor(seconds / 3600);
  const minutes = Math.round((seconds % 3600) / 60);
  return hours ? `${hours.toLocaleString()}h ${minutes}m` : `${minutes}m`;
}

export function when(epoch: number | null | undefined): string {
  return epoch ? new Date(epoch * 1000).toLocaleString() : "never";
}
