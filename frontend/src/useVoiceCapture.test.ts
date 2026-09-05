import { act, renderHook } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { useVoiceCapture } from "./hooks/useVoiceCapture";

describe("useVoiceCapture", () => {
  it("cancel() clears a stuck error state back to idle", async () => {
    // jsdom has no navigator.mediaDevices.getUserMedia, so start() hits
    // the exact same real "not supported"/permission-failure path a
    // genuine microphone access failure does — no mocking needed. This
    // is the regression test for a real bug: Escape (and every surface's
    // own cancel button) called cancel() unconditionally, but cancel()
    // itself silently no-op'd unless voiceState was "listening" — so a
    // voice error, once shown, had no way to be dismissed short of
    // quitting the app.
    const { result } = renderHook(() =>
      useVoiceCapture({ submitTurn: async () => ({ ok: true, assistantMessage: null }) }),
    );

    expect(result.current.voiceState).toBe("idle");

    await act(async () => {
      result.current.start();
    });

    expect(result.current.voiceState).toBe("error");
    expect(result.current.voiceError).toBeTruthy();

    act(() => {
      result.current.cancel();
    });

    expect(result.current.voiceState).toBe("idle");
    expect(result.current.voiceError).toBeNull();
  });

  it("cancel() is still a no-op from idle (never throws, never changes state)", () => {
    const { result } = renderHook(() =>
      useVoiceCapture({ submitTurn: async () => ({ ok: true, assistantMessage: null }) }),
    );

    act(() => {
      result.current.cancel();
    });

    expect(result.current.voiceState).toBe("idle");
  });
});
