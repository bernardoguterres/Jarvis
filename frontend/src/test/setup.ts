import "@testing-library/jest-dom/vitest";
import { cleanup } from "@testing-library/react";
import { afterEach, beforeEach } from "vitest";

afterEach(() => {
  cleanup();
});

// jsdom has never implemented window.matchMedia — needed since Phase 6's
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
