import { render } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import JarvisCore, { type CoreState } from "./JarvisCore";

describe("JarvisCore — Mission Control's focusActive never outranks a real voice state", () => {
  it("applies is-focus-active only when state is idle", () => {
    const { container } = render(<JarvisCore state="idle" focusActive />);
    const hud = container.querySelector(".jarvis-hud");
    expect(hud?.className).toContain("state-idle");
    expect(hud?.className).toContain("is-focus-active");
  });

  it.each<CoreState>(["listening", "transcribing", "thinking", "speaking", "error"])(
    "never adds is-focus-active while state is %s, even with focusActive true",
    (state) => {
      const { container } = render(<JarvisCore state={state} focusActive />);
      const hud = container.querySelector(".jarvis-hud");
      expect(hud?.className).toContain(`state-${state}`);
      expect(hud?.className).not.toContain("is-focus-active");
    },
  );

  it("omits is-focus-active entirely when focusActive is false or omitted", () => {
    const { container } = render(<JarvisCore state="idle" />);
    expect(container.querySelector(".jarvis-hud")?.className).not.toContain("is-focus-active");
  });
});
