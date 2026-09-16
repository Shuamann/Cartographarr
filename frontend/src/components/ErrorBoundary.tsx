import { Component, type ErrorInfo, type ReactNode } from "react";

/* Keeps one broken screen from taking down the whole app.
 *
 * Without this, anything that throws during render unmounts everything — nav
 * bar included — and leaves a blank page with no way back and no clue what
 * happened.
 */
export default class ErrorBoundary extends Component<
  { children: ReactNode; name: string },
  { error: Error | null }
> {
  state = { error: null as Error | null };

  static getDerivedStateFromError(error: Error) {
    return { error };
  }

  componentDidCatch(error: Error, info: ErrorInfo) {
    console.error(`${this.props.name} crashed:`, error, info.componentStack);
  }

  render() {
    if (!this.state.error) return this.props.children;

    return (
      <div className="pad">
        <h1>{this.props.name} couldn't load</h1>
        <p className="note bad-note">{this.state.error.message}</p>
        <p className="muted">
          The rest of the app still works — pick another tab. Details are in the browser
          console.
        </p>
        <button className="btn" onClick={() => this.setState({ error: null })}>
          Try again
        </button>
      </div>
    );
  }
}
