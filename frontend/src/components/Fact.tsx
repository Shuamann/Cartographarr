import type { ReactNode } from "react";

/* One fact, as a label and a value on one line, inside a `dl.spec`.
 *
 * A div between a dl and its dt is allowed and screen readers still read the
 * pairs. The pair is its own box so that a long value takes the room it needs
 * without wrapping inside its column and leaving the block ragged.
 *
 * Three copies of this existed, one per screen, which is how a layout drifts:
 * the same five lines in four files cannot be fixed in one place. The fourth,
 * People's Stat, carries a second line and stays as it is.
 *
 * A value too long for its column is clipped with an ellipsis rather than
 * pushing the card sideways, so the whole of it goes in a title: a file path
 * cut off with no way to read it is worse than one that has to be hovered.
 */
export default function Fact({ label, children }: { label: string; children: ReactNode }) {
  return (
    <div className="spec-pair">
      <dt>{label}</dt>
      <dd title={typeof children === "string" || typeof children === "number" ? String(children) : undefined}>
        {children}
      </dd>
    </div>
  );
}
