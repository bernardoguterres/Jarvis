import { readFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import { describe, expect, it } from "vitest";

/** Regression coverage for a real defect found during real-Mac
 * acceptance: the Home `JarvisCore` button (`.jarvis-hud-interactive`)
 * carried its own `background: none; border: none;` reset, but a
 * higher-specificity global `button:not(.primary):not(.back-button):
 * not(.domain-button):not(.push-to-talk-button)` base rule — which never
 * listed `.jarvis-hud-interactive` in its exclusion set — still applied a
 * rectangular panel background/border/border-radius on top of it,
 * producing a visible square behind the circular ring assembly (clearest
 * while a domain like BUILD was focused, since the square's own border
 * color follows `--ring-color`). jsdom doesn't apply real cascade/
 * specificity resolution from an external stylesheet, so this asserts
 * directly against the CSS source rather than a computed style — the
 * actual visual fix was confirmed separately via a real browser (see
 * docs/DECISIONS.md). */
describe("Home JarvisCore — no rectangular panel behind the rings", () => {
  const css = readFileSync(join(dirname(fileURLToPath(import.meta.url)), "index.css"), "utf-8");

  it("the generic button base-style rule explicitly excludes .jarvis-hud-interactive", () => {
    const genericButtonRules = css.match(/^button:not\([^{]*\)\s*\{/gm) ?? [];
    expect(genericButtonRules.length).toBeGreaterThan(0);
    for (const rule of genericButtonRules) {
      expect(rule).toContain(":not(.jarvis-hud-interactive)");
    }
  });

  it(".jarvis-hud-interactive still resets background/border/padding to nothing itself", () => {
    const match = css.match(/\.jarvis-hud-interactive\s*\{([^}]*)\}/);
    expect(match).not.toBeNull();
    const body = match![1];
    expect(body).toMatch(/background:\s*none/);
    expect(body).toMatch(/border:\s*none/);
    expect(body).toMatch(/padding:\s*0/);
  });

  it("the domain-node activation scale stays within the restrained 1.02-1.04 range, not the old 1.14 balloon", () => {
    const match = css.match(/\.domain-node\.is-focusing \.domain-button\s*\{([^}]*)\}/);
    expect(match).not.toBeNull();
    const scaleMatch = match![1].match(/transform:\s*scale\(([\d.]+)\)/);
    expect(scaleMatch).not.toBeNull();
    const scale = Number(scaleMatch![1]);
    expect(scale).toBeGreaterThanOrEqual(1.0);
    expect(scale).toBeLessThanOrEqual(1.05);
  });
});

describe("Home↔domain shared View Transition CSS — reduced-motion structural guard", () => {
  const css = readFileSync(join(dirname(fileURLToPath(import.meta.url)), "index.css"), "utf-8");

  it("every custom view-transition-* rule and the no-View-Transitions fallback fade live inside a prefers-reduced-motion: no-preference block", () => {
    const guardedBlockMatch = css.match(
      /@media \(prefers-reduced-motion: no-preference\) \{([\s\S]*?)\n\}\n\n@keyframes jarvis-domain-reveal/,
    );
    expect(guardedBlockMatch).not.toBeNull();
    expect(guardedBlockMatch![1]).toContain("::view-transition-group(jarvis-domain-shared)");
    expect(guardedBlockMatch![1]).toContain("::view-transition-new(root)");

    const fallbackGuardMatch = css.match(
      /@media \(prefers-reduced-motion: no-preference\) \{\s*\.no-view-transitions \.home,/,
    );
    expect(fallbackGuardMatch).not.toBeNull();
  });

  it("no bare (unguarded) ::view-transition-* rule exists outside a no-preference media block", () => {
    const cssWithoutComments = css.replace(/\/\*[\s\S]*?\*\//g, "");
    const totalOccurrences = cssWithoutComments.match(/::view-transition-(group|old|new)\(/g) ?? [];
    const guardedBlockMatch = cssWithoutComments.match(
      /@media \(prefers-reduced-motion: no-preference\) \{([\s\S]*?)\n\}\n\n@keyframes jarvis-domain-reveal/,
    );
    const occurrencesInsideGuardedBlock = guardedBlockMatch![1].match(/::view-transition-(group|old|new)\(/g) ?? [];
    // Every occurrence in the whole file must live inside the one guarded
    // block asserted above — if a future edit adds a ::view-transition-*
    // rule outside it, this count stops matching.
    expect(totalOccurrences.length).toBeGreaterThan(0);
    expect(occurrencesInsideGuardedBlock.length).toBe(totalOccurrences.length);
  });
});
