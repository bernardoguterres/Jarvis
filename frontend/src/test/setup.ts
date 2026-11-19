import "@testing-library/jest-dom/vitest";
import { cleanup } from "@testing-library/react";
import { afterEach, beforeEach } from "vitest";

afterEach(() => {
  cleanup();
});

// jsdom has never implemented window.matchMedia. It is needed since the
// voice-waveform pass added a real useReducedMotion() hook (application
// code, not just CSS). Defaults every test to "no preference" (matches:
// false); a test that specifically needs reduced motion overrides this
// per-test via vi.stubGlobal.
beforeEach(() => {
  if (typeof window.matchMedia !== "function") {
    window.matchMedia = (query: string) => ({
      matches: false,
      media: query,
      onchange: null,
      addListener: () => {},
      removeListener: () => {},
      addEventListener: () => {},
      removeEventListener: () => {},
      dispatchEvent: () => false,
    });
  }
});

// jsdom has no object URLs either. Spoken replies create one per chunk and
// release it when playback stops, which can happen during cleanup's unmount,
// after a test has already restored its own URL stub.
beforeEach(() => {
  if (typeof URL.createObjectURL !== "function") URL.createObjectURL = () => "blob:jsdom";
  if (typeof URL.revokeObjectURL !== "function") URL.revokeObjectURL = () => {};
});
