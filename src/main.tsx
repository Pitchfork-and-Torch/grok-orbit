import React from "react";
import ReactDOM from "react-dom/client";
import App from "./App";
import "./styles.css";

class BootError extends React.Component<{ children: React.ReactNode }, { err: string | null }> {
  state = { err: null as string | null };
  static getDerivedStateFromError(err: unknown) {
    return { err: String(err) };
  }
  render() {
    if (this.state.err) {
      return (
        <div style={{ padding: 24, color: "#e6ebe4", background: "#07080b", minHeight: "100%" }}>
          <p>Orbit Star failed to paint.</p>
          <pre style={{ whiteSpace: "pre-wrap" }}>{this.state.err}</pre>
        </div>
      );
    }
    return this.props.children;
  }
}

ReactDOM.createRoot(document.getElementById("root") as HTMLElement).render(
  <React.StrictMode>
    <BootError>
      <App />
    </BootError>
  </React.StrictMode>,
);
