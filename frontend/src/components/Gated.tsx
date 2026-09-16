import { createContext, useContext, type ReactNode } from "react";
import type { Capabilities } from "../lib/api";

const Ctx = createContext<Capabilities | null>(null);

export const CapabilityProvider = Ctx.Provider;
export const useCapabilities = () => useContext(Ctx);

export function useIsAvailable(requirement: string): { ok: boolean; reason: string | null } {
  const caps = useContext(Ctx);
  if (!caps) return { ok: false, reason: "Still checking what this server supports…" };

  if (requirement === "plex_pass") {
    return {
      ok: caps.plex_pass.active === true,
      reason: caps.plex_pass.reason,
    };
  }
  if (requirement.startsWith("integration:")) {
    const name = requirement.slice("integration:".length);
    const state = caps.integrations[name];
    return {
      ok: state === "ok",
      reason: state ? `${name} is ${state}` : `${name} isn't set up yet`,
    };
  }
  return { ok: true, reason: null };
}

/* Renders children disabled, with the reason, when a requirement isn't met.
 *
 * Disabled and explained, never hidden: a hidden feature teaches people it
 * doesn't exist, while a greyed-out one with "Requires Plex Pass" teaches them
 * what to turn on. The API refuses independently; this is a courtesy, not a
 * control.
 */
export default function Gated({
  requires,
  children,
}: {
  requires: string;
  children: ReactNode;
}) {
  const { ok, reason } = useIsAvailable(requires);
  if (ok) return <>{children}</>;

  return (
    <span className="gated" title={reason ?? undefined} aria-disabled="true">
      {children}
      <span className="gated-reason">{reason}</span>
    </span>
  );
}
