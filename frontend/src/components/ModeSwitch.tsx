/* Record only, or act. Used by every built in list: the ban list, the country
 * list, and each saved rule. */
export default function ModeSwitch({
  recordOnly,
  locked,
  onChange,
}: {
  recordOnly: boolean;
  locked: boolean;
  onChange: (recordOnly: boolean) => void;
}) {
  return (
    <div
      className="segmented mode-switch"
      title={locked ? "Locked to record only by ENFORCE_DRY_RUN in the container configuration" : undefined}
    >
      <button className={recordOnly ? "seg on" : "seg"} onClick={() => !recordOnly && onChange(true)} disabled={locked}>
        Record only
      </button>
      <button className={!recordOnly ? "seg on act" : "seg"} onClick={() => recordOnly && onChange(false)} disabled={locked}>
        Act
      </button>
    </div>
  );
}
