import { useEffect, useRef, useState, type ReactNode } from "react";

/* Asking a question without leaving the app.
 *
 * Everything here used to be window.confirm, window.prompt or window.alert.
 * Those are the browser's dialogs, not this app's: they arrive in the wrong
 * typeface in the wrong place, say "127.0.0.1:6277 says", cannot show a
 * poster or a file size or a warning in red, and on some browsers carry a
 * "don't let this page ask again" tickbox that silently turns every later
 * question into a no. BanDialog already proved the shape; this is the same
 * idea for the rest.
 *
 * Call it like the thing it replaces:
 *
 *     if (!(await askConfirm({ title: "Delete this rule?" }))) return;
 *     const why = await askText({ title: "Reason, for the Log" });
 *
 * A module-level host rather than a context, so a call site does not have to
 * be rewired to reach it. Nothing is mounted means nothing was asked, and the
 * answer is no rather than a crash.
 */

type Confirm = {
  kind: "confirm";
  title: string;
  body?: ReactNode;
  confirm?: string;
  cancel?: string;
  danger?: boolean;
  resolve: (ok: boolean) => void;
};

type Text = {
  kind: "text";
  title: string;
  body?: ReactNode;
  label?: string;
  placeholder?: string;
  initial?: string;
  required?: boolean;
  confirm?: string;
  danger?: boolean;
  resolve: (value: string | null) => void;
};

type Tell = {
  kind: "tell";
  title: string;
  body?: ReactNode;
  danger?: boolean;
  resolve: (ok: boolean) => void;
};

type Request = Confirm | Text | Tell;

let show: ((request: Request) => void) | null = null;

export function askConfirm(options: Omit<Confirm, "kind" | "resolve">): Promise<boolean> {
  return new Promise((resolve) => {
    if (!show) return resolve(false);
    show({ ...options, kind: "confirm", resolve });
  });
}

export function askText(options: Omit<Text, "kind" | "resolve">): Promise<string | null> {
  return new Promise((resolve) => {
    if (!show) return resolve(null);
    show({ ...options, kind: "text", resolve });
  });
}

/* Something went wrong and there is nowhere on the page to say so. Prefer a
 * note next to whatever failed; this is for the handfuls that have no such
 * place. */
export function tell(title: string, body?: ReactNode): Promise<boolean> {
  return new Promise((resolve) => {
    if (!show) return resolve(true);
    show({ kind: "tell", title, body, danger: true, resolve });
  });
}

export default function AskHost() {
  const ref = useRef<HTMLDialogElement>(null);
  const [request, setRequest] = useState<Request | null>(null);
  const [value, setValue] = useState("");

  useEffect(() => {
    show = (next) => {
      setValue(next.kind === "text" ? (next.initial ?? "") : "");
      setRequest(next);
    };
    return () => {
      show = null;
    };
  }, []);

  useEffect(() => {
    const dialog = ref.current;
    if (!dialog) return;
    if (request && !dialog.open) dialog.showModal();
    else if (!request && dialog.open) dialog.close();
  }, [request]);

  function finish(answer: boolean) {
    if (!request) return;
    // Escape and the backdrop mean no, which is what a cancel is.
    if (request.kind === "text") request.resolve(answer ? value : null);
    else request.resolve(answer);
    setRequest(null);
  }

  const text = request?.kind === "text" ? request : null;
  const short = request === null || request.kind !== "text";

  return (
    <dialog
      ref={ref}
      className="dialog ask"
      onCancel={(e) => {
        e.preventDefault();
        finish(false);
      }}
      aria-labelledby="ask-title"
    >
      {request && (
        <form
          onSubmit={(e) => {
            e.preventDefault();
            finish(true);
          }}
        >
          <h2 id="ask-title">{request.title}</h2>
          {request.body && <div className="muted small ask-body">{request.body}</div>}
          {text && (
            <label>
              {text.label ?? "Your answer"}
              <input
                value={value}
                placeholder={text.placeholder}
                onChange={(e) => setValue(e.target.value)}
                autoFocus
              />
            </label>
          )}
          <div className="row dialog-actions">
            {request.kind !== "tell" && (
              <button type="button" className="btn" onClick={() => finish(false)}>
                {request.kind === "confirm" ? (request.cancel ?? "Cancel") : "Cancel"}
              </button>
            )}
            <button
              type="submit"
              className={request.danger ? "btn danger" : "btn primary"}
              disabled={Boolean(text?.required) && !value.trim()}
              autoFocus={short}
            >
              {request.kind === "tell" ? "Close" : (request.confirm ?? "Yes")}
            </button>
          </div>
        </form>
      )}
    </dialog>
  );
}
