import { useEffect, useState } from "react";

/* Something is on its way. An animated bar so a slow answer does not look like
 * a frozen page, what is being waited on, and after a few seconds how long it
 * has been, with an optional note on why it can be slow.
 *
 * No percentage: nearly everything here is one request to Tautulli or Plex,
 * which does not report progress, and a made-up bar is worse than an honest
 * one that just moves.
 */
export default function Loading({
  label = "Loading",
  slowHint,
  compact,
}: {
  label?: string;
  slowHint?: string;
  compact?: boolean;
}) {
  const [seconds, setSeconds] = useState(0);
  useEffect(() => {
    const started = Date.now();
    const timer = setInterval(() => setSeconds(Math.floor((Date.now() - started) / 1000)), 1000);
    return () => clearInterval(timer);
  }, []);

  return (
    <div className={compact ? "loading compact" : "loading"} role="status" aria-live="polite">
      <div className="loading-bar" aria-hidden="true">
        <span />
      </div>
      <p className="muted small">
        {label}
        {seconds >= 3 ? ` (${seconds}s)` : "…"}
      </p>
      {slowHint && seconds >= 8 && <p className="muted small">{slowHint}</p>}
    </div>
  );
}
