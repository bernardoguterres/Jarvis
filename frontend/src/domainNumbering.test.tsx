import { fireEvent, render, screen, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import App from "./App";
import * as api from "./api";
import type { Domain } from "./api";
import { DOMAIN_SLUG_ORDER, domainNumber } from "./domainOrder";

/** Backend order (`GET /api/domains`, `order_by(Domain.slug)`) — this
 * fixture deliberately matches the real API's alphabetical ordering, the
 * same ordering `DOMAIN_SLUG_ORDER` encodes, so this test can assert
 * every surface agrees with the one shared source rather than merely
 * agreeing with each other by accident. */
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

describe("Domain numbering — one authoritative mapping across every surface", () => {
  it("every domain shows the same number on its Home node, its domain-header emblem, and via its 1-6 keyboard shortcut", async () => {
    baseMocks();
    render(<App />);
    await screen.findByText("BODY");

    for (const domain of DOMAINS) {
      const expected = domainNumber(domain.slug);
      expect(expected).not.toBeNull();

      // Home's orbital node badge.
      const button = screen.getByRole("button", { name: new RegExp(`^Open ${domain.name}:`, "i") });
      expect(within(button).getByText(String(expected))).toBeInTheDocument();

      // The 1-6 keyboard shortcut opens exactly the domain that number
      // stands for, and the destination header's own badge agrees.
      fireEvent.keyDown(window, { key: String(expected) });
      expect(await screen.findByRole("heading", { name: domain.name })).toBeInTheDocument();
      const headerBadge = document.querySelector(".domain-emblem-kbd");
      expect(headerBadge).not.toBeNull();
      expect(headerBadge!.textContent).toBe(String(expected));

      fireEvent.keyDown(window, { key: "0" }); // back to Home for the next iteration
      await screen.findByText("BODY");
    }
  });

  it("DOMAIN_SLUG_ORDER has exactly the six real domain slugs, each exactly once", () => {
    const realSlugs = DOMAINS.map((d) => d.slug).sort();
    expect([...DOMAIN_SLUG_ORDER].sort()).toEqual(realSlugs);
  });
});
