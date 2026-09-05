import { describe, expect, it } from "vitest";
import { DOMAIN_SLUG_ORDER, domainNumber, domainSlugForNumber } from "./domainOrder";

describe("domainOrder — the one authoritative domain shortcut/display-order mapping", () => {
  it("matches the canonical BODY(1) BUILD(2) LIFE(3) MIND(4) PATH(5) PEOPLE(6) order", () => {
    expect(DOMAIN_SLUG_ORDER).toEqual(["body", "build", "life", "mind", "path", "people"]);
  });

  it("domainNumber and domainSlugForNumber are exact inverses for every domain", () => {
    for (let n = 1; n <= 6; n++) {
      const slug = domainSlugForNumber(n);
      expect(slug).not.toBeNull();
      expect(domainNumber(slug!)).toBe(n);
    }
  });

  it("domainNumber returns null for an unrecognized slug, never a guessed number", () => {
    expect(domainNumber("unknown")).toBeNull();
    expect(domainNumber("")).toBeNull();
  });

  it("domainSlugForNumber returns null outside 1-6, never wrapping or guessing", () => {
    expect(domainSlugForNumber(0)).toBeNull();
    expect(domainSlugForNumber(7)).toBeNull();
    expect(domainSlugForNumber(-1)).toBeNull();
  });
});
