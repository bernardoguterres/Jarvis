import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import App from "./App";
import Home from "./views/Home";
import ErrorBoundary from "./components/diagnostic/ErrorBoundary";
import ControllerOfflineDiagnostic from "./components/diagnostic/ControllerOfflineDiagnostic";
import { ModuleErrorState } from "./components/diagnostic/Diagnostic";
import * as api from "./api";
import type { Domain } from "./api";

const DOMAINS: Domain[] = [
  { id: "1", slug: "body", name: "BODY", description: "Fitness and health.", created_at: "", updated_at: "" },
  { id: "2", slug: "mind", name: "MIND", description: "Mood and habits.", created_at: "", updated_at: "" },
  { id: "3", slug: "people", name: "PEOPLE", description: "Relationships.", created_at: "", updated_at: "" },
  { id: "4", slug: "path", name: "PATH", description: "Career and education.", created_at: "", updated_at: "" },
  { id: "5", slug: "build", name: "BUILD", description: "Projects and code.", created_at: "", updated_at: "" },
  { id: "6", slug: "life", name: "LIFE", description: "Calendar and finances.", created_at: "", updated_at: "" },
];

beforeEach(() => {
  vi.restoreAllMocks();
  window.history.replaceState(null, "", "/");
  vi.spyOn(api, "fetchHomeBriefing").mockResolvedValue({
    generated_at: "2026-08-29T09:00:00Z",
    items: [],
    sources: [],
    include_body: true,
    include_mind: false,
    include_people: false,
    acknowledged_and_snoozed: [],
    mission_focus: [],
  });
});

afterEach(() => {
  vi.restoreAllMocks();
  window.history.replaceState(null, "", "/");
});

describe("Unknown route (404)", () => {
  it("renders the navigation-fault diagnostic for an unrecognized path, never a bare error", async () => {
    window.history.pushState({}, "", "/some/unknown/path");
    vi.spyOn(api, "fetchHealth").mockResolvedValue({ status: "ok" });
    vi.spyOn(api, "fetchDomains").mockResolvedValue(DOMAINS);
    vi.spyOn(api, "fetchAgentStatus").mockResolvedValue({
      hermes_available: true,
      model_configured: true,
      model: "m",
      provider: "hermes",
    });

    render(<App />);

    expect(await screen.findByText(/signal not found/i)).toBeInTheDocument();
    expect(screen.getByText(/navigation fault/i)).toBeInTheDocument();
    expect(screen.queryByText("BODY")).not.toBeInTheDocument();
  });

  it("returns to the real Home screen without a reload", async () => {
    window.history.pushState({}, "", "/nonexistent");
    vi.spyOn(api, "fetchHealth").mockResolvedValue({ status: "ok" });
    vi.spyOn(api, "fetchDomains").mockResolvedValue(DOMAINS);
    vi.spyOn(api, "fetchAgentStatus").mockResolvedValue({
      hermes_available: true,
      model_configured: true,
      model: "m",
      provider: "hermes",
    });
    const user = userEvent.setup();

    render(<App />);
    await screen.findByText(/signal not found/i);
    await user.click(screen.getByRole("button", { name: /return to jarvis/i }));

    expect(await screen.findByText("BODY")).toBeInTheDocument();
  });
});

describe("Controller (backend) offline", () => {
  it("renders the offline diagnostic instead of a broken Home when the backend is unreachable", async () => {
    vi.spyOn(api, "fetchHealth").mockRejectedValue(new Error("network error"));
    vi.spyOn(api, "fetchDomains").mockRejectedValue(new Error("network error"));
    vi.spyOn(api, "fetchAgentStatus").mockRejectedValue(new Error("network error"));

    render(<App />);

    expect(await screen.findByText(/local controller unavailable/i)).toBeInTheDocument();
    expect(screen.getByText(/offline/i)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /retry connection/i })).toBeInTheDocument();
    // Never claims data was lost.
    expect(screen.getByText(/has not been deleted/i)).toBeInTheDocument();
  });

  it("manual retry calls checkHealth and recovers cleanly into Home without a reload", async () => {
    const checkHealth = vi.fn().mockResolvedValueOnce(false).mockResolvedValueOnce(true);
    const onRecovered = vi.fn();
    const user = userEvent.setup();

    render(<ControllerOfflineDiagnostic checkHealth={checkHealth} onRecovered={onRecovered} />);

    await user.click(screen.getByRole("button", { name: /retry connection/i }));
    await waitFor(() => expect(checkHealth).toHaveBeenCalledTimes(1));
    expect(onRecovered).not.toHaveBeenCalled();

    await user.click(screen.getByRole("button", { name: /retry connection/i }));
    await waitFor(() => expect(onRecovered).toHaveBeenCalledTimes(1));
  });

  it("plays a genuine RESTORED transition before handing off — never claims success before checkHealth resolves true", async () => {
    const checkHealth = vi.fn().mockResolvedValue(true);
    const onRecovered = vi.fn();
    const user = userEvent.setup();

    render(<ControllerOfflineDiagnostic checkHealth={checkHealth} onRecovered={onRecovered} />);
    await user.click(screen.getByRole("button", { name: /retry connection/i }));

    // The RESTORED label appears only after checkHealth has genuinely
    // resolved true, and onRecovered (the real hand-off to Home) still
    // hasn't fired yet — the transition is real time, not instant.
    expect(await screen.findByText(/controller link \/\/ restored/i)).toBeInTheDocument();
    expect(onRecovered).not.toHaveBeenCalled();

    await waitFor(() => expect(onRecovered).toHaveBeenCalledTimes(1));
  });

  it("shows 'Attempting reconnection…' status while a retry is genuinely in flight", async () => {
    let resolveCheck: (v: boolean) => void = () => {};
    const checkHealth = vi.fn().mockReturnValue(new Promise<boolean>((r) => (resolveCheck = r)));
    const user = userEvent.setup();

    render(<ControllerOfflineDiagnostic checkHealth={checkHealth} onRecovered={vi.fn()} />);
    await user.click(screen.getByRole("button", { name: /retry connection/i }));

    expect(await screen.findByText(/attempting reconnection…/i)).toBeInTheDocument();
    resolveCheck(false);
  });

  it("schedules bounded automatic retries at 5s, then 10s", async () => {
    vi.useFakeTimers();
    const checkHealth = vi.fn().mockResolvedValue(false);
    const onRecovered = vi.fn();

    render(<ControllerOfflineDiagnostic checkHealth={checkHealth} onRecovered={onRecovered} />);

    expect(checkHealth).not.toHaveBeenCalled();
    await vi.advanceTimersByTimeAsync(5000);
    expect(checkHealth).toHaveBeenCalledTimes(1);
    await vi.advanceTimersByTimeAsync(10000);
    expect(checkHealth).toHaveBeenCalledTimes(2);

    vi.useRealTimers();
  });

  it("shows launch instructions with the generic jarvisctl.sh open command, no absolute path", async () => {
    const user = userEvent.setup();
    render(<ControllerOfflineDiagnostic checkHealth={vi.fn().mockResolvedValue(false)} onRecovered={vi.fn()} />);

    await user.click(screen.getByText(/show launch instructions/i));
    expect(screen.getByText("jarvisctl.sh open")).toBeInTheDocument();
    expect(screen.getByText(/hide launch instructions/i)).toBeInTheDocument();
    expect(screen.queryByText(/show launch instructions/i)).not.toBeInTheDocument();
  });

  it("shows native-app guidance instead of a terminal command when running inside the packaged app", async () => {
    const user = userEvent.setup();
    (window as unknown as { __TAURI__?: unknown }).__TAURI__ = {};
    try {
      render(<ControllerOfflineDiagnostic checkHealth={vi.fn().mockResolvedValue(false)} onRecovered={vi.fn()} />);

      await user.click(screen.getByText(/show launch instructions/i));
      expect(screen.queryByText("jarvisctl.sh open")).not.toBeInTheDocument();
      expect(screen.queryByRole("button", { name: /copy command/i })).not.toBeInTheDocument();
      expect(screen.getByText(/quit jarvis.*reopen it/i)).toBeInTheDocument();
    } finally {
      delete (window as unknown as { __TAURI__?: unknown }).__TAURI__;
    }
  });

  it("has exactly one launch-instructions disclosure control, never a duplicate", async () => {
    const user = userEvent.setup();
    render(<ControllerOfflineDiagnostic checkHealth={vi.fn().mockResolvedValue(false)} onRecovered={vi.fn()} />);

    expect(document.querySelectorAll("details.technical-details")).toHaveLength(1);
    await user.click(screen.getByText(/show launch instructions/i));
    expect(document.querySelectorAll("details.technical-details")).toHaveLength(1);
    expect(screen.getAllByText(/launch instructions/i)).toHaveLength(1);
  });
});

describe("Hermes/model link degraded", () => {
  it("shows the degraded model-link banner while keeping domains usable, and never implies the backend is down", async () => {
    const user = userEvent.setup();
    render(
      <Home
        onSelectDomain={() => {}}
        onOpenGeneral={() => {}}
        onNavigate={() => {}}
        health="ok"
        modelDegraded
        onRetryModel={vi.fn()}
      />,
    );
    vi.spyOn(api, "fetchDomains").mockResolvedValue(DOMAINS);

    expect(await screen.findByText(/model link unavailable/i)).toBeInTheDocument();
    expect(screen.getByText(/local notes, memories, records and saved data remain available/i)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /retry model connection/i })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /continue without model/i })).toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: /continue without model/i }));
    expect(screen.queryByText(/model link unavailable/i)).not.toBeInTheDocument();
  });

  it("does not show the banner when Hermes is available", () => {
    render(<Home onSelectDomain={() => {}} onOpenGeneral={() => {}} onNavigate={() => {}} health="ok" modelDegraded={false} />);
    expect(screen.queryByText(/model link unavailable/i)).not.toBeInTheDocument();
  });
});

function Bomb(): never {
  throw new Error("deliberate test failure");
}

describe("Unexpected interface failure (ErrorBoundary)", () => {
  it("renders the interface-fault diagnostic instead of crashing the whole app", () => {
    const consoleSpy = vi.spyOn(console, "error").mockImplementation(() => {});
    render(
      <ErrorBoundary>
        <Bomb />
      </ErrorBoundary>,
    );

    expect(screen.getByText(/unexpected error/i)).toBeInTheDocument();
    expect(screen.getByText(/interface fault/i)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /try again/i })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /return to jarvis/i })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /reload interface/i })).toBeInTheDocument();
    consoleSpy.mockRestore();
  });

  it("never renders a stack trace or technical detail outside a collapsed disclosure", () => {
    const consoleSpy = vi.spyOn(console, "error").mockImplementation(() => {});
    render(
      <ErrorBoundary>
        <Bomb />
      </ErrorBoundary>,
    );

    const details = document.querySelector("details.technical-details");
    if (details) {
      expect(details).not.toHaveAttribute("open");
    }
    consoleSpy.mockRestore();
  });
});

describe("Accessibility", () => {
  it("announces the diagnostic state via a live region and keeps actions keyboard-reachable", async () => {
    vi.spyOn(api, "fetchHealth").mockRejectedValue(new Error("network error"));
    vi.spyOn(api, "fetchDomains").mockRejectedValue(new Error("network error"));
    vi.spyOn(api, "fetchAgentStatus").mockRejectedValue(new Error("network error"));

    render(<App />);
    await screen.findByText(/local controller unavailable/i);

    const live = document.querySelector('[role="status"][aria-live="polite"]');
    expect(live).toBeInTheDocument();
    expect(live).toHaveTextContent(/local controller unavailable/i);

    const retryButton = screen.getByRole("button", { name: /retry connection/i });
    retryButton.focus();
    expect(retryButton).toHaveFocus();
  });
});

describe("Module-level failure", () => {
  it("shows a compact failure for one module without claiming an empty/zero state", () => {
    render(<ModuleErrorState label="Sync history" onRetry={() => {}} />);
    expect(screen.getByText(/sync history unavailable/i)).toBeInTheDocument();
    expect(screen.getByText(/status is unknown, not empty/i)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /retry/i })).toBeInTheDocument();
  });
});
