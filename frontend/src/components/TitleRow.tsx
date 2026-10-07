import { Fragment, type ReactNode } from "react";
import { titleParts, type Titled } from "../lib/titles";

/* A row about a title, in the house style, for any list that names one.
 *
 * The same pieces the Issues rows use: the artwork across the row behind a
 * scrim, a poster, the year above the title, the facts as label and value,
 * and one action. A list of plays drawn as lines of text says what it is
 * about only once it is read; with the artwork it says so before.
 *
 * The title shortens the way the stream tiles do, an episode's own name
 * first and its season and episode never, so a long show name cannot push
 * out the part that says which episode it was.
 *
 * Rows go inside a TitleRows, which lays them out by the width they are
 * given rather than the width of the window: the same row sits in a map
 * drawer a third of a phone wide and in a page across an ultrawide. */

export type TitleFact = { label: string; value: ReactNode };

type Props = {
  ratingKey: number | null;
  item: Titled & { year?: number | null };
  /* A line under the title, for what the facts cannot say. */
  note?: ReactNode;
  facts: TitleFact[];
  /* The one thing to do, beside the facts. A link or button inside a fact
     stops its click going on to the row, or it would open the row as well. */
  action?: ReactNode;
  open?: boolean;
  onToggle?: () => void;
};

export function TitleRows({ children }: { children: ReactNode }) {
  return <div className="title-rows">{children}</div>;
}

export function TitleName({ item }: { item: Titled }) {
  const { show, code, episode } = titleParts(item);
  const whole = [show, code, episode].filter(Boolean).join(" - ") || "Untitled";
  if (!show || !code) {
    return (
      <span className="media-row-title" title={whole}>
        {episode || "Untitled"}
      </span>
    );
  }
  return (
    <span className="media-row-title card-title" title={whole}>
      <span className="card-title-show">{show}</span>
      <span className="muted card-title-sep">-</span>
      <span className="card-title-code">{code}</span>
      {episode ? (
        <>
          <span className="muted card-title-sep">-</span>
          <span className="card-title-name">{episode}</span>
        </>
      ) : null}
    </span>
  );
}

export default function TitleRow({ ratingKey, item, note, facts, action, open, onToggle }: Props) {
  const body = (
    <>
      {ratingKey ? (
        <span
          className="media-row-art"
          aria-hidden="true"
          style={{ backgroundImage: `url(/api/media/${ratingKey}/image?kind=art&width=900&height=506)` }}
        />
      ) : null}
      {ratingKey ? (
        <img
          className="media-row-poster"
          src={`/api/media/${ratingKey}/image?width=92&height=138`}
          alt=""
          loading="lazy"
          onError={(e) => ((e.currentTarget as HTMLImageElement).style.visibility = "hidden")}
        />
      ) : (
        <span className="media-row-poster" />
      )}
      <span className="media-row-what">
        {item.year ? <span className="media-row-year">{item.year}</span> : null}
        <TitleName item={item} />
        {note ? <span className="media-row-note">{note}</span> : null}
      </span>
      {facts.length > 0 && (
        <dl className="media-row-facts">
          {facts.map((f) => (
            <Fragment key={f.label}>
              <dt>{f.label}</dt>
              <dd>{f.value}</dd>
            </Fragment>
          ))}
        </dl>
      )}
      {action ? <span className="media-row-do">{action}</span> : null}
    </>
  );

  if (!onToggle) return <div className="media-row still">{body}</div>;
  return (
    /* A div rather than a button, because the facts can hold links and a
       button inside a button is neither valid nor well behaved. It keeps the
       keyboard behaviour a button has. */
    <div
      className={open ? "media-row on" : "media-row"}
      role="button"
      tabIndex={0}
      aria-expanded={open}
      onClick={onToggle}
      onKeyDown={(e) => {
        // Only the row's own keys: Enter on a link inside it bubbles up here.
        if (e.target !== e.currentTarget) return;
        if (e.key === "Enter" || e.key === " ") {
          e.preventDefault();
          onToggle();
        }
      }}
    >
      {body}
    </div>
  );
}
