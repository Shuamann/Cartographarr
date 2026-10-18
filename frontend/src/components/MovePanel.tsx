import { useState } from "react";
import { askConfirm } from "./Ask";
import Loading from "./Loading";
import { api, useApi } from "../lib/api";
import { size } from "../routes/Library";

/* Moving a title from one library source to another.
 *
 * An array fills up and the answer is to move things off it. Radarr and Sonarr
 * each move the files and update their own record in one operation, which
 * nothing outside them can do correctly, so this asks for that rather than
 * moving anything itself.
 *
 * The free space is the service's own reading of each share and is labelled
 * that way. A share that over reports fools it exactly as it fools everything
 * else: on the library this was built against one set of roots reports 61 TB
 * on a disk of twenty, which is the same figure the Storage page has a setting
 * to correct and the service has no way to know about.
 */

type Where = { id: number; path: string; free: number | null; accessible: boolean };

type Plan = {
  from: string | null;
  to: string;
  bytes: number;
  blockers: string[];
  warnings: string[];
  can_move: boolean;
};

type Options = {
  service: string;
  title: string | null;
  here: string | null;
  bytes: number;
  /* The service keeps one folder per series, so asking about an episode moves
     the show and a season cannot go anywhere on its own. */
  whole_show: boolean;
  destinations: Where[];
  free_is_from: string;
  plan: Plan | null;
};

export default function MovePanel({
  ratingKey,
  onClose,
  onMoved,
}: {
  ratingKey: number;
  onClose: () => void;
  onMoved?: () => void;
}) {
  const options = useApi<Options>(`/library/file/${ratingKey}/move`);
  const [picked, setPicked] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState<{ text: string; ok: boolean } | null>(null);

  /* Asked for the one destination somebody is looking at rather than for all
     of them at once: each plan asks the service what it is doing with the
     title, and six of those to draw a list nobody has chosen from yet is five
     wasted. */
  const plan = useApi<Options>(
    // null, not an empty string: useApi skips only on null, and "" asks the
    // server for the API root and takes a 404 every time the panel opens.
    picked ? `/library/file/${ratingKey}/move?to=${encodeURIComponent(picked)}` : null,
    [picked],
  );

  const o = options.data;
  const chosen = plan.data?.plan ?? null;

  async function go() {
    if (!picked || !chosen?.can_move || !o) return;
    const room = o.destinations.find((d) => d.path === picked)?.free;
    if (
      !(await askConfirm({
        title: `Move ${o.title ?? "this title"}?`,
        body: (
          <>
            <p>
              {o.service} will move {size(chosen.bytes)} from {chosen.from ?? "where it is"} to {picked}, and update
              its own record. Plex is told about both folders afterwards.
              {o.whole_show && " That is the whole show, every season of it."}
            </p>
            <p>
              {picked} has {room === null || room === undefined ? "an unknown amount of" : size(room)} free, as{" "}
              {o.free_is_from} reads it. A share that over reports its own size fools {o.free_is_from} the same way
              it fools anything else.
            </p>
            {chosen.warnings.map((w) => (
              <p key={w} className="note warn-note">
                {w}
              </p>
            ))}
            <p>Nothing is deleted. It can be moved back the same way.</p>
          </>
        ),
        confirm: "Move it",
        danger: true,
      }))
    )
      return;
    setBusy(true);
    setMessage(null);
    try {
      await api.post(`/library/file/${ratingKey}/move`, { to: picked });
      setMessage({
        text: `Queued. Moves run one at a time, and it is watched until the files are actually there. Follow it under Library, Remediation queue.`,
        ok: true,
      });
      onMoved?.();
    } catch (err) {
      setMessage({ text: (err as Error).message, ok: false });
    } finally {
      setBusy(false);
    }
  }

  if (options.error)
    return (
      <p className="note bad-note" role="alert">
        {options.error}
      </p>
    );
  if (!o) return <Loading label="Asking where it could go" />;

  return (
    <section className="move-panel">
      <h4>Move it somewhere else</h4>
      <p className="muted small move-why">
        {o.service} moves the files and updates its own record in one go, which is the only way the two stay
        honest. It is holding {size(o.bytes)} for {o.whole_show ? "this whole show" : "this title"}, in{" "}
        {o.here ?? "a folder it has not named"}. The room shown is {o.free_is_from}&apos;s own reading of each
        share.
      </p>
      {o.whole_show && (
        <p className="note move-why">
          This moves the whole show, every season of it. {o.service} keeps one folder per series, so a single
          season cannot be sent somewhere else on its own.
        </p>
      )}
      <div className="move-list">
        {o.destinations
          .filter((d) => d.path !== o.here)
          .map((d) => (
            <label key={d.path} className={picked === d.path ? "move-row on" : "move-row"}>
              <input
                type="radio"
                name={`move-${ratingKey}`}
                checked={picked === d.path}
                onChange={() => setPicked(d.path)}
              />
              <span className="min0 move-path mono">{d.path}</span>
              <span className="muted small move-free">
                {d.free === null || d.free === undefined ? "room not stated" : `${size(d.free)} free`}
                {!d.accessible && ` · ${o.service} cannot reach it`}
              </span>
            </label>
          ))}
      </div>

      {picked && plan.error && (
        <p className="note bad-note" role="alert">
          {plan.error}
        </p>
      )}
      {picked && !plan.data && !plan.error && <Loading label="Checking whether it can move" />}
      {chosen && (
        <>
          {chosen.blockers.length > 0 && (
            <div className="note warn-note">
              Not now, because:
              <ul className="move-reasons">
                {chosen.blockers.map((b) => (
                  <li key={b}>{b}</li>
                ))}
              </ul>
            </div>
          )}
          {chosen.warnings.map((w) => (
            <p key={w} className="note">
              {w}
            </p>
          ))}
        </>
      )}

      {message && <p className={message.ok ? "note ok-note" : "note bad-note"}>{message.text}</p>}
      <div className="file-actions">
        <button className="btn primary" disabled={!chosen?.can_move || busy} onClick={go}>
          {busy ? "Asking" : "Move it"}
        </button>
        <button className="btn" onClick={onClose}>
          Done
        </button>
      </div>
    </section>
  );
}
