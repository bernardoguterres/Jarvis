import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import VoiceCaptureOverlay from "./VoiceCaptureOverlay";

describe("VoiceCaptureOverlay", () => {
  it("renders nothing while idle", () => {
    const { container } = render(
      <VoiceCaptureOverlay voiceState="idle" scope="HOME" micStream={null} ttsAudioElement={null} />,
    );
    expect(container).toBeEmptyDOMElement();
  });

  it("calls onDismiss when the overlay itself is clicked while in the error state", () => {
    // Regression test: a stuck "VOICE ERROR" screen previously had no
    // click-anywhere dismissal at all — only Escape (and only after a
    // separate cancel() bug was fixed) could clear it, which a viewer with
    // no keyboard handy, or who simply didn't know the shortcut, had no way
    // to discover.
    const onDismiss = vi.fn();
    render(
      <VoiceCaptureOverlay
        voiceState="error"
        scope="HOME"
        micStream={null}
        ttsAudioElement={null}
        errorMessage="Could not hear anything to transcribe."
        onDismiss={onDismiss}
      />,
    );
    fireEvent.click(screen.getByText("Could not hear anything to transcribe."));
    expect(onDismiss).toHaveBeenCalledTimes(1);
  });

  it("renders an explicit, focusable Dismiss button in the error state as a guaranteed hit target", () => {
    const onDismiss = vi.fn();
    render(
      <VoiceCaptureOverlay
        voiceState="error"
        scope="HOME"
        micStream={null}
        ttsAudioElement={null}
        errorMessage="Could not hear anything to transcribe."
        onDismiss={onDismiss}
      />,
    );
    fireEvent.click(screen.getByRole("button", { name: "Dismiss" }));
    expect(onDismiss).toHaveBeenCalledTimes(1);
  });

  it("never intercepts a click while listening, so a push-to-talk release still reaches the real control underneath", () => {
    const onDismiss = vi.fn();
    render(
      <VoiceCaptureOverlay
        voiceState="listening"
        scope="HOME"
        micStream={null}
        ttsAudioElement={null}
        onDismiss={onDismiss}
      />,
    );
    // Rendered via createPortal into document.body, not into the local
    // render container.
    const overlay = document.body.querySelector(".voice-capture-overlay");
    expect(overlay).not.toHaveClass("is-dismissible");
    fireEvent.click(overlay!);
    expect(onDismiss).not.toHaveBeenCalled();
  });
});
