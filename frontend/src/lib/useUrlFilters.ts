import { useEffect, useState } from "react";
import { EMPTY, fromQuery, toQuery, type FilterState } from "./filters";

/* Filter state that lives in the address bar.
 *
 * So a filtered view can be bookmarked, or pasted to someone else, instead of
 * being rebuilt by hand. Only one route is mounted at a time, so there is no
 * argument over who owns the query string.
 *
 * replaceState rather than pushState: every checkbox tick would otherwise add
 * a history entry and make the back button useless.
 */
export function useUrlFilters(): [FilterState, (next: FilterState) => void] {
  const [filters, setFilters] = useState<FilterState>(() =>
    window.location.search ? fromQuery(window.location.search) : EMPTY,
  );

  useEffect(() => {
    const params = new URLSearchParams(toQuery(filters));
    // The tab is owned by the shell, not by the filters, and writing the query
    // string wholesale would drop it. Its effect only reruns when the tab
    // changes, so it would not put it back.
    const tab = new URLSearchParams(window.location.search).get("tab");
    if (tab) params.set("tab", tab);

    const query = params.toString();
    const url = `${window.location.pathname}${query ? `?${query}` : ""}${window.location.hash}`;
    window.history.replaceState(null, "", url);
  }, [filters]);

  return [filters, setFilters];
}
