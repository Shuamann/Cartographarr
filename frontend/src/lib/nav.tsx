import { createContext, useContext } from "react";
import type { LiveSession } from "./api";
import type { FilterState } from "./filters";
import type { PeopleFilter } from "./tabs";

/* Ways to go and look at something, available anywhere.
 *
 * Shared components (a stream, a log entry) link to users, devices and the
 * map. Passing each callback down through every route in between is how the
 * same card ended up with different buttons in different places, so the shell
 * provides them once here instead. Anything left undefined is simply not
 * offered, which is how viewers do not get admin actions.
 */
export type Nav = {
  isAdmin: boolean;
  openUser?: (userId: number) => void;
  openDevice?: (machineId: string) => void;
  openAddress?: (ip: string) => void;
  showOnMap?: (session: LiveSession) => void;
  /* Ask, then add to the ban list. Resolves true if it was banned. */
  blockDevice?: (machineId: string, label: string) => Promise<boolean>;
  unbanDevice?: (machineId: string, label: string) => Promise<boolean>;
  /* Open Map or History with the filters narrowed, for example to one user. */
  filterTo?: (tab: "Map" | "History", patch: Partial<FilterState>) => void;
  /* Open People, optionally with one of its list filters switched on. */
  openPeople?: (filter?: PeopleFilter) => void;
};

export const NavContext = createContext<Nav>({ isAdmin: false });

export function useNav(): Nav {
  return useContext(NavContext);
}
