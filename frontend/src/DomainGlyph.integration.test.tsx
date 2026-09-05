import { fireEvent, render, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import App from "./App";
import * as api from "./api";
import type { Domain } from "./api";

const DOMAINS: Domain[] = [
  { id: "1", slug: "body", name: "BODY", description: "Fitness and health.", created_at: "", updated_at: "" },
  { id: "2", slug: "build", name: "BUILD", description: "Projects and code.", created_at: "", updated_at: "" },
  { id: "3", slug: "life", name: "LIFE", description: "Calendar and finances.", created_at: "", updated_at: "" },
  { id: "4", slug: "mind", name: "MIND", description: "Mood and habits.", created_at: "", updated_at: "" },
  { id: "5", slug: "path", name: "PATH", description: "Career and education.", created_at: "", updated_at: "" },
  { id: "6", slug: "people", name: "PEOPLE", description: "Relationships.", created_at: "", updated_at: "" },
];

function baseMocks() {
  vi.spyOn(api, "fetchHealth").mockResolvedValue({ status: "ok" });
  vi.spyOn(api, "fetchDomains").mockResolvedValue(DOMAINS);
  vi.spyOn(api, "fetchAgentStatus").mockResolvedValue({
    hermes_available: false,
    model_configured: false,
    model: null,
    provider: "hermes",
  });
  vi.spyOn(api, "fetchConversations").mockResolvedValue([]);
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
}

beforeEach(() => {
  vi.restoreAllMocks();
});

afterEach(() => {
  vi.restoreAllMocks();
});

describe("DomainGlyph — shared across Home and the domain header (D94)", () => {
  it("Home's BODY node and BODY's own header both render the exact same lucide-activity icon, via the same DomainGlyph component", async () => {
    baseMocks();
    render(<App />);
    const bodyButton = await screen.findByRole("button", { name: /open body/i });
    expect(bodyButton.querySelector("svg.domain-glyph.lucide-activity")).not.toBeNull();

    fireEvent.click(bodyButton);
    expect(await screen.findByRole("heading", { name: "BODY" })).toBeInTheDocument();
    const headerEmblem = document.querySelector(".domain-emblem");
    expect(headerEmblem!.querySelector("svg.domain-glyph.lucide-activity")).not.toBeNull();
  });

  it("the decorative glyph is hidden from assistive technology while the enclosing button keeps its real, distinct accessible name", async () => {
    baseMocks();
    render(<App />);
    const mindButton = await screen.findByRole("button", { name: /open mind/i });
    const svg = mindButton.querySelector("svg.domain-glyph")!;
    expect(svg.getAttribute("aria-hidden")).toBe("true");
    // The button's own accessible name (from its aria-label) already
    // includes the real domain name/description — computed independent
    // of the hidden glyph's own (nonexistent) label.
    expect(mindButton.getAttribute("aria-label")).toMatch(/^Open MIND:/);
  });

  it("reduced motion never removes the glyph or the domain's identity — only animation/transition durations are affected", async () => {
    const mediaQueryList = {
      matches: true,
      media: "(prefers-reduced-motion: reduce)",
      addEventListener: () => {},
      removeEventListener: () => {},
    } as unknown as MediaQueryList;
    const matchMediaSpy = vi.spyOn(window, "matchMedia").mockReturnValue(mediaQueryList);

    baseMocks();
    render(<App />);
    const lifeButton = await screen.findByRole("button", { name: /open life/i });
    // Still present, still the correct icon, still carrying the domain's
    // real name — reduced motion is a purely visual/animation concern.
    expect(lifeButton.querySelector("svg.domain-glyph.lucide-calendar-days")).not.toBeNull();
    expect(screen.getByText("LIFE")).toBeInTheDocument();

    matchMediaSpy.mockRestore();
  });
});
