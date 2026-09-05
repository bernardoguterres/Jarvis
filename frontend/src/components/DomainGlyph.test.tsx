import { render } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import DomainGlyph from "./DomainGlyph";
import { DOMAIN_SLUG_ORDER } from "../domainOrder";

/** The canonical slug → Lucide icon mapping (`docs/DECISIONS.md` D94) —
 * verified here by the CSS class Lucide stamps on every icon
 * (`lucide-<kebab-case-name>`), which is a real, stable signal of which
 * icon actually rendered, not just an assumption. */
const EXPECTED_LUCIDE_CLASS: Record<string, string> = {
  body: "lucide-activity",
  build: "lucide-boxes",
  life: "lucide-calendar-days",
  mind: "lucide-brain",
  path: "lucide-compass",
  people: "lucide-users-round",
};

describe("DomainGlyph — the canonical lucide-react icon per domain (D94)", () => {
  it("renders the exact approved Lucide icon for every domain, never a substitute", () => {
    for (const slug of DOMAIN_SLUG_ORDER) {
      const { container } = render(<DomainGlyph slug={slug} />);
      const svg = container.querySelector("svg");
      expect(svg).not.toBeNull();
      expect(svg!.classList.contains(EXPECTED_LUCIDE_CLASS[slug])).toBe(true);
    }
  });

  it("every domain maps to a distinct icon — no two domains accidentally share one", () => {
    const classes = new Set(Object.values(EXPECTED_LUCIDE_CLASS));
    expect(classes.size).toBe(DOMAIN_SLUG_ORDER.length);
  });

  it("uses currentColor and a transparent (fill=none) background, never a hardcoded colour", () => {
    for (const slug of DOMAIN_SLUG_ORDER) {
      const { container } = render(<DomainGlyph slug={slug} />);
      const svg = container.querySelector("svg")!;
      expect(svg.getAttribute("stroke")).toBe("currentColor");
      expect(svg.getAttribute("fill")).toBe("none");
    }
  });

  it("never contains a letter fallback, embedded background circle, or any fill shape of its own", () => {
    for (const slug of DOMAIN_SLUG_ORDER) {
      const { container } = render(<DomainGlyph slug={slug} />);
      const svg = container.querySelector("svg")!;
      expect(svg.textContent).toBe(""); // no letter mark of any kind
      // Every shape inside inherits stroke/fill from the svg root (i.e.
      // has no shape-level fill/color override of its own) — none of the
      // six icons draw a filled background shape.
      const shapesWithOwnFill = Array.from(svg.querySelectorAll("[fill]")).filter(
        (el) => el.getAttribute("fill") !== "none" && el.getAttribute("fill") !== "currentColor",
      );
      expect(shapesWithOwnFill).toHaveLength(0);
    }
  });

  it("is purely decorative — aria-hidden and not focusable, never duplicating the enclosing control's own accessible name", () => {
    const { container } = render(<DomainGlyph slug="body" />);
    const svg = container.querySelector("svg")!;
    expect(svg.getAttribute("aria-hidden")).toBe("true");
    expect(svg.getAttribute("focusable")).toBe("false");
    expect(svg.getAttribute("aria-label")).toBeNull();
    expect(svg.getAttribute("role")).not.toBe("img");
  });

  it("renders nothing for an unrecognized slug rather than guessing", () => {
    const { container } = render(<DomainGlyph slug="not-a-real-domain" />);
    expect(container.querySelector("svg")).toBeNull();
  });

  it("carries the shared .domain-glyph class plus any caller-provided className, so CSS sizes/colors it identically regardless of call site", () => {
    const { container } = render(<DomainGlyph slug="mind" className="domain-node-glyph" />);
    const svg = container.querySelector("svg")!;
    expect(svg.classList.contains("domain-glyph")).toBe(true);
    expect(svg.classList.contains("domain-node-glyph")).toBe(true);
  });

  it("applies the same stroke width (in the icon's own viewBox units) to every domain, so no icon reads heavier or lighter than its peers", () => {
    const widths = DOMAIN_SLUG_ORDER.map((slug) => {
      const { container } = render(<DomainGlyph slug={slug} />);
      return container.querySelector("svg")!.getAttribute("stroke-width");
    });
    expect(new Set(widths).size).toBe(1);
  });
});
