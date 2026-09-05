import { Component, type ErrorInfo, type ReactNode } from "react";
import { DiagnosticPage } from "./Diagnostic";
import { TechnicalDetails } from "../console/Console";

interface ErrorBoundaryProps {
  children: ReactNode;
}

interface ErrorBoundaryState {
  error: Error | null;
  /** A short, non-secret local correlation code — never derived from the
   * error's own message/stack, so it can never leak anything sensitive
   * even if generated from otherwise-untrusted state. */
  referenceId: string | null;
}

function generateReferenceId(): string {
  if (typeof crypto.randomUUID === "function") return crypto.randomUUID().slice(0, 8);
  return Math.random().toString(16).slice(2, 10);
}

/** Catches uncaught React rendering failures anywhere below it. Renders a
 * calm, distinct diagnostic screen instead of a blank page or a raw stack
 * trace — the stack itself only ever appears sanitized, under a collapsed
 * Technical details control, and only when `import.meta.env.DEV`. */
class ErrorBoundary extends Component<ErrorBoundaryProps, ErrorBoundaryState> {
  state: ErrorBoundaryState = { error: null, referenceId: null };

  static getDerivedStateFromError(error: Error): ErrorBoundaryState {
    return { error, referenceId: generateReferenceId() };
  }

  componentDidCatch(error: Error, info: ErrorInfo) {
    // Logged only to the local browser console — never sent anywhere,
    // never rendered directly into the page outside the Technical details
    // disclosure below.
    // eslint-disable-next-line no-console
    console.error("Jarvis interface fault", error, info.componentStack);
  }

  handleTryAgain = () => {
    this.setState({ error: null, referenceId: null });
  };

  handleReturnHome = () => {
    window.location.assign("/");
  };

  handleReload = () => {
    window.location.reload();
  };

  render() {
    const { error, referenceId } = this.state;
    if (!error) return this.props.children;

    return (
      <DiagnosticPage
        microLabel="INTERFACE FAULT"
        heading="Jarvis encountered an unexpected error"
        explanation="Something in the interface itself failed to render. Your locally stored data is untouched — this is a display fault, not a data or backend problem."
        tone="critical"
        variant="interrupted"
        meta={referenceId ? `Reference: ${referenceId}` : undefined}
        actions={
          <>
            <button type="button" className="primary" onClick={this.handleTryAgain}>
              Try again
            </button>
            <button type="button" onClick={this.handleReturnHome}>
              Return to Jarvis
            </button>
            <button type="button" onClick={this.handleReload}>
              Reload interface
            </button>
          </>
        }
      >
        {import.meta.env.DEV && (
          <TechnicalDetails summary="Technical details (development only)">
            <p>{error.message}</p>
            {error.stack && <pre style={{ whiteSpace: "pre-wrap" }}>{error.stack}</pre>}
          </TechnicalDetails>
        )}
      </DiagnosticPage>
    );
  }
}

export default ErrorBoundary;
