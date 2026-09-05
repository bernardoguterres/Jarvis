import { readFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import { describe, expect, it } from "vitest";

/** Regression coverage for a real WCAG AA contrast defect found by
 * axe-core during Research Centre container QA: `--text-tertiary`
 * (`.ledger-row-meta`, `.ledger-empty`, `.console-eyebrow`,
 * `.console-description`, `.change-badge`, `.briefing-item-subtitle`, and
 * ~25 other shared selectors — 44 usages total) measured 4.466:1 against
 * the lightest panel background it is ever paired with
 * (`--bg-panel-hover`), a genuine miss of the 4.5:1 normal-text threshold
 * — present on every already-shipped Centre using these selectors, not
 * just Research Centre, since the token itself was short. Fixed centrally
 * at the token (index.css `:root`), not per-selector, so every current
 * and future user of `--text-tertiary` benefits. jsdom has no real
 * rendering/compositing engine, so — mirroring homeCoreStyling.test.ts's
 * established pattern — this asserts directly against the real CSS
 * source's token values via the same WCAG relative-luminance formula
 * axe-core itself uses, rather than a screenshot/pixel-sampling test. */

const css = readFileSync(join(dirname(fileURLToPath(import.meta.url)), "index.css"), "utf-8");

function cssVariable(name: string): string {
  const match = css.match(new RegExp(`--${name}:\\s*(#[0-9a-fA-F]{6})`));
  expect(match, `--${name} not found (or not a plain #rrggbb value) in index.css`).not.toBeNull();
  return match![1];
}

function relativeLuminance(hex: string): number {
  const channel = (c: number) => {
    const s = c / 255;
    return s <= 0.03928 ? s / 12.92 : ((s + 0.055) / 1.055) ** 2.4;
  };
  const r = parseInt(hex.slice(1, 3), 16);
  const g = parseInt(hex.slice(3, 5), 16);
  const b = parseInt(hex.slice(5, 7), 16);
  return 0.2126 * channel(r) + 0.7152 * channel(g) + 0.0722 * channel(b);
}

function contrastRatio(hexA: string, hexB: string): number {
  const [l1, l2] = [relativeLuminance(hexA), relativeLuminance(hexB)].sort((a, b) => b - a);
  return (l1 + 0.05) / (l2 + 0.05);
}

// Every panel/canvas background --text-tertiary is ever composited
// against in this app's single (always-dark) theme — see index.css's
// `:root` background-token block. --bg-panel-hover is the lightest of
// these, and is therefore always the binding (worst-case) constraint.
const BACKGROUND_TOKENS = ["bg-void", "bg-deep", "bg-panel", "bg-panel-raised", "bg-panel-hover", "bg-panel-sunken"];

const WCAG_AA_NORMAL_TEXT = 4.5;
// A deliberate margin above the bare 4.5:1 minimum — the fix should not
// land at exactly the threshold, where routine future rounding/anti-
// aliasing differences could tip it back under.
const SAFETY_MARGIN = 4.6;

describe("--text-tertiary meets WCAG AA (4.5:1) against every panel background, with margin", () => {
  const textTertiary = cssVariable("text-tertiary");

  it.each(BACKGROUND_TOKENS)("contrast against --%s is >= 4.5:1", (bgToken) => {
    const bg = cssVariable(bgToken);
    expect(contrastRatio(textTertiary, bg)).toBeGreaterThanOrEqual(WCAG_AA_NORMAL_TEXT);
  });

  it("the worst-case background (--bg-panel-hover) clears 4.5:1 with a real safety margin, not exactly 4.50", () => {
    const worst = Math.min(...BACKGROUND_TOKENS.map((token) => contrastRatio(textTertiary, cssVariable(token))));
    expect(worst).toBeGreaterThanOrEqual(SAFETY_MARGIN);
  });

  it("--text-primary and --text-secondary (the higher-emphasis tiers) still contrast at least as well as --text-tertiary — the fix did not invert the existing text hierarchy", () => {
    const textPrimary = cssVariable("text-primary");
    const textSecondary = cssVariable("text-secondary");
    const worstBg = cssVariable("bg-panel-hover");
    const tertiaryWorst = contrastRatio(textTertiary, worstBg);
    expect(contrastRatio(textSecondary, worstBg)).toBeGreaterThanOrEqual(tertiaryWorst);
    expect(contrastRatio(textPrimary, worstBg)).toBeGreaterThanOrEqual(contrastRatio(textSecondary, worstBg));
  });
});
