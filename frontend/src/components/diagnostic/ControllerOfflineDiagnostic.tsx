import { useCallback, useEffect, useRef, useState } from "react";
import { DiagnosticPage, type DiagnosticTone } from "./Diagnostic";
import { isRunningInNativeApp } from "../../nativeShell";

// 5, 10, 20, then 30s — bounded (never shorter, never keeps escalating
// faster), so a real outage never gets hammered with requests.
const RETRY_DELAYS_MS = [5000, 10000, 20000, 30000];

// The recovery flash: red -> violet -> cyan, then hand off to Home. Total
// stays within the requested ~500-800ms window.
const RECOVERY_STEP_MS = 260;
const RECOVERY_HANDOFF_MS = 650;

interface ControllerOfflineDiagnosticProps {
  /** Resolves true/false for whether the controller answered — never
   * throws; App.tsx's own health check already normalizes that. */
  checkHealth: () => Promise<boolean>;
  /** Called once the recovery flash has played — App.tsx owns what
   * "recovered" actually means (re-fetching domains, etc.), not this
   * component. */
  onRecovered: () => void;
}

function ControllerOfflineDiagnostic({ checkHealth, onRecovered }: ControllerOfflineDiagnosticProps) {
  const [attempt, setAttempt] = useState(0);
  const [scanning, setScanning] = useState(false);
  const [secondsUntilRetry, setSecondsUntilRetry] = useState<number | null>(null);
  const [showLaunchInstructions, setShowLaunchInstructions] = useState(false);
  const [copied, setCopied] = useState(false);
  const [recoveryTone, setRecoveryTone] = useState<DiagnosticTone | null>(null);
  const timeoutRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const countdownRef = useRef<ReturnType<typeof setInterval> | null>(null);
  const recoveryTimeoutsRef = useRef<ReturnType<typeof setTimeout>[]>([]);

  const playRecoveryAndHandOff = useCallback(() => {
    // Red -> violet -> cyan, then the real hand-off to Home — never
    // claims success before checkHealth has already resolved true.
    setRecoveryTone("recovered");
    recoveryTimeoutsRef.current.push(
      setTimeout(() => setRecoveryTone("neutral"), RECOVERY_STEP_MS),
      setTimeout(onRecovered, RECOVERY_HANDOFF_MS),
    );
  }, [onRecovered]);

  const runCheck = useCallback(async () => {
    setScanning(true);
    const ok = await checkHealth();
    setScanning(false);
    if (ok) {
      playRecoveryAndHandOff();
      return true;
    }
    return false;
  }, [checkHealth, playRecoveryAndHandOff]);

  const scheduleNextRetry = useCallback(
    (nextAttempt: number) => {
      if (document.hidden) return; // never retry while the tab isn't visible
      const delay = RETRY_DELAYS_MS[Math.min(nextAttempt, RETRY_DELAYS_MS.length - 1)];
      let remaining = Math.round(delay / 1000);
      setSecondsUntilRetry(remaining);
      countdownRef.current = setInterval(() => {
        remaining -= 1;
        setSecondsUntilRetry(Math.max(remaining, 0));
      }, 1000);
      timeoutRef.current = setTimeout(async () => {
        if (countdownRef.current) clearInterval(countdownRef.current);
        const recovered = await runCheck();
        if (!recovered) {
          setAttempt(nextAttempt + 1);
        }
      }, delay);
    },
    [runCheck],
  );

  useEffect(() => {
    scheduleNextRetry(attempt);
    return () => {
      if (timeoutRef.current) clearTimeout(timeoutRef.current);
      if (countdownRef.current) clearInterval(countdownRef.current);
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [attempt]);

  useEffect(() => {
    function onVisibilityChange() {
      if (document.hidden) {
        if (timeoutRef.current) clearTimeout(timeoutRef.current);
        if (countdownRef.current) clearInterval(countdownRef.current);
        setSecondsUntilRetry(null);
      } else if (secondsUntilRetry === null) {
        scheduleNextRetry(attempt);
      }
    }
    document.addEventListener("visibilitychange", onVisibilityChange);
    return () => document.removeEventListener("visibilitychange", onVisibilityChange);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [attempt, secondsUntilRetry]);

  useEffect(() => {
    return () => {
      recoveryTimeoutsRef.current.forEach(clearTimeout);
    };
  }, []);

  async function handleManualRetry() {
    if (timeoutRef.current) clearTimeout(timeoutRef.current);
    if (countdownRef.current) clearInterval(countdownRef.current);
    setSecondsUntilRetry(null);
    const recovered = await runCheck();
    if (!recovered) {
      setAttempt((prev) => prev + 1);
    }
  }

  async function handleCopyCommand() {
    try {
      await navigator.clipboard.writeText("jarvisctl.sh open");
      setCopied(true);
      setTimeout(() => setCopied(false), 1500);
    } catch {
      // Clipboard access can be denied; the command is still visible to
      // copy manually, so this is not treated as an error state.
    }
  }

  const recovering = recoveryTone !== null;

  return (
    <DiagnosticPage
      microLabel={recovering ? "CONTROLLER LINK // RESTORED" : "CONTROLLER LINK // OFFLINE"}
      heading="Local controller unavailable"
      explanation="Jarvis's local controller is not responding. Your locally stored data has not been deleted."
      tone={recoveryTone ?? "critical"}
      variant="reconnecting"
      scanning={scanning}
      recovering={recovering}
      large
      meta={
        recovering
          ? undefined
          : secondsUntilRetry !== null
            ? `Retrying in ${secondsUntilRetry}s…`
            : scanning
              ? "Attempting reconnection…"
              : undefined
      }
      actions={
        <>
          <button type="button" className="primary" onClick={handleManualRetry} disabled={scanning}>
            {scanning ? "Retrying…" : "Retry connection"}
          </button>
        </>
      }
    >
      <details
        className="technical-details"
        open={showLaunchInstructions}
        onToggle={(e) => setShowLaunchInstructions(e.currentTarget.open)}
      >
        <summary>{showLaunchInstructions ? "Hide launch instructions" : "Show launch instructions"}</summary>
        <div className="technical-details-body">
          {isRunningInNativeApp() ? (
            <>
              <p>
                Jarvis is supervising its own local controller and will keep retrying automatically
                (the button above also retries immediately).
              </p>
              <p>If this persists, quit Jarvis (menu bar icon, or Cmd+Q) and reopen it.</p>
            </>
          ) : (
            <>
              <p>
                Jarvis's local controller normally starts from your Mac's launcher shortcut, or from the
                existing command-line launcher for this installation.
              </p>
              <pre style={{ whiteSpace: "pre-wrap" }}>jarvisctl.sh open</pre>
              <button type="button" onClick={handleCopyCommand}>
                {copied ? "Copied" : "Copy command"}
              </button>
              <p>This page cannot start the controller itself — a browser tab has no way to launch a local process.</p>
            </>
          )}
        </div>
      </details>
    </DiagnosticPage>
  );
}

export default ControllerOfflineDiagnostic;
