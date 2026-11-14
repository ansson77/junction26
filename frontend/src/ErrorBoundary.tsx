import { Component, type ReactNode } from "react";

/** Shows a crash in a page as a message with a reload button, instead of a blank screen. */
export default class ErrorBoundary extends Component<{ children: ReactNode }, { error: Error | null }> {
  state = { error: null as Error | null };

  static getDerivedStateFromError(error: Error) {
    return { error };
  }

  render() {
    if (!this.state.error) return this.props.children;
    return (
      <div className="page narrow">
        <h1>Something went wrong</h1>
        <div className="error">{this.state.error.message}</div>
        <div className="actions">
          <a className="btn" href="#/">Home</a>
          <button className="btn primary" onClick={() => location.reload()}>Reload</button>
        </div>
      </div>
    );
  }
}
