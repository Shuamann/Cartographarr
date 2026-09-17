import { displayTitle } from "../lib/titles";
import { useMemo, useState } from "react";
import { useApi, useUserNames, type HistoryPage, type HistoryRow } from "../lib/api";
import FilterBar from "../components/FilterBar";
import { toQuery, type FilterState } from "../lib/filters";
import { when } from "../components/DataTable";
import PlayDetail from "../components/PlayDetail";

const SIZE = 100;

const SORTABLE: Record<string, string> = {
  started: "When",
  full_title: "Title",
  user_id: "User",
  platform: "Platform",
  player: "Device",
  media_type: "Type",
  percent_complete: "Progress",
};

/* Paginated and sorted server-side, unlike Users and Devices.
 *
 * There are tens of thousands of rows, so sorting in the browser would mean
 * shipping all of them first.
 */
export default function HistoryRoute({
  onOpenMedia,
  onOpenUser,
  filters,
  onFilters,
}: {
  onOpenMedia?: (row: HistoryRow) => void;
  onOpenUser?: (userId: number) => void;
  filters: FilterState;
  onFilters: (next: FilterState) => void;
}) {
  const names = useUserNames();
  const [page, setPage] = useState(1);
  const [sort, setSort] = useState("started");
  const [order, setOrder] = useState<"asc" | "desc">("desc");
  // One row open at a time, like the Log.
  const [open, setOpen] = useState<number | null>(null);

  const query = useMemo(() => toQuery(filters), [filters]);
  const url = `/history${query}${query ? "&" : "?"}page=${page}&size=${SIZE}&sort=${sort}&order=${order}`;
  const data = useApi<HistoryPage>(url);

  // Any filter change invalidates the page number.
  function changeFilters(next: FilterState) {
    onFilters(next);
    setPage(1);
  }

  function sortBy(key: string) {
    if (sort === key) setOrder(order === "asc" ? "desc" : "asc");
    else {
      setSort(key);
      setOrder("desc");
    }
    setPage(1);
  }

  const total = data.data?.total ?? 0;
  const pages = Math.max(1, Math.ceil(total / SIZE));

  return (
    <div className="map-page">
      <FilterBar value={filters} onChange={changeFilters} />

      <div className="viewbar">
        <span className="muted small">
          {total.toLocaleString()} {total === 1 ? "play" : "plays"}
        </span>
        <div className="row" style={{ marginLeft: "auto" }}>
          <button className="ms-btn" disabled={page <= 1} onClick={() => setPage(page - 1)}>
            Previous
          </button>
          <span className="muted small">
            Page {page.toLocaleString()} of {pages.toLocaleString()}
          </span>
          <button className="ms-btn" disabled={page >= pages} onClick={() => setPage(page + 1)}>
            Next
          </button>
        </div>
      </div>

      <div className="view-body">
        <div className="list-wrap">
          {data.error && <p className="note bad-note pad">{data.error}</p>}
          <table className="table locations">
            <thead>
              <tr>
                {Object.entries(SORTABLE).map(([key, label]) => (
                  <th
                    key={key}
                    className={sort === key ? "sorted" : ""}
                    onClick={() => sortBy(key)}
                  >
                    {label}
                    {sort === key && <span className="caret">{order === "asc" ? "▲" : "▼"}</span>}
                  </th>
                ))}
                <th>Where</th>
              </tr>
            </thead>
            <tbody>
              {data.data?.items.map((row) => [
                <tr
                  key={row.row_id}
                  className={open === row.row_id ? "loc-row selected" : "loc-row"}
                  onClick={() =>
                    (row as HistoryRow & { anonymised?: boolean }).anonymised
                      ? undefined
                      : onOpenMedia
                        ? onOpenMedia(row)
                        : setOpen(open === row.row_id ? null : row.row_id)
                  }
                  aria-expanded={open === row.row_id}
                >
                  <td className="muted">{when(row.started)}</td>
                  <td>
                    {(row as HistoryRow & { anonymised?: boolean }).anonymised ? (
                      <span className="muted">Withheld, another viewer</span>
                    ) : (
                      displayTitle(row)
                    )}
                  </td>
                  <td>
                    {row.user_id !== null && onOpenUser ? (
                      <button
                        className="linkish"
                        onClick={(e) => {
                          e.stopPropagation();
                          onOpenUser(row.user_id as number);
                        }}
                      >
                        {names.get(row.user_id) ?? row.user_id}
                      </button>
                    ) : (
                      names.get(row.user_id ?? -1) ?? row.user_id
                    )}
                  </td>
                  <td className="muted">{row.platform}</td>
                  <td className="muted">{row.player}</td>
                  <td>
                    <span className="pill">{row.media_type}</span>
                    {row.transcode_decision === "transcode" && (
                      <span className="pill warn">transcode</span>
                    )}
                  </td>
                  <td className="num">{row.percent_complete ?? 0}%</td>
                  <td className="muted">{row.ip_address}</td>
                </tr>,
                open === row.row_id && (
                  <tr key={`${row.row_id}-detail`} className="play-detail-row">
                    <td colSpan={Object.keys(SORTABLE).length + 1}>
                      <PlayDetail rowId={row.row_id} />
                    </td>
                  </tr>
                ),
              ])}
            </tbody>
          </table>
        </div>
      </div>
    </div>
  );
}
