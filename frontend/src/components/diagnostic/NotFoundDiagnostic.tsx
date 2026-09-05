import { useState } from "react";
import { DiagnosticPage } from "./Diagnostic";

interface NotFoundDiagnosticProps {
  onReturnHome: () => void;
  onOpenPalette: () => void;
}

/** A genuine unknown-route fallback. This app has exactly one real
 * frontend route ("/") — everything else reaching this component means
 * the backend's SPA fallback (see app/main.py) served index.html for a
 * path this interface doesn't recognize, so it renders this instead of
 * silently pretending to be Home. Deliberately violet/cyan, not red —
 * the system itself isn't broken, a URL just doesn't correspond to
 * anything. */
function NotFoundDiagnostic({ onReturnHome, onOpenPalette }: NotFoundDiagnosticProps) {
  const [canGoBack] = useState(() => window.history.length > 1);

  return (
    <DiagnosticPage
      microLabel="NAVIGATION FAULT // 404"
      heading="Signal not found"
      explanation="The requested console does not exist or is no longer available."
      tone="neutral"
      variant="gap"
      actions={
        <>
          <button type="button" className="primary" onClick={onReturnHome}>
            Return to Jarvis
          </button>
          <button type="button" onClick={onOpenPalette}>
            Open command palette
          </button>
          {canGoBack && (
            <button type="button" onClick={() => window.history.back()}>
              Go back
            </button>
          )}
        </>
      }
    />
  );
}

export default NotFoundDiagnostic;
