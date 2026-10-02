import { render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import MemoryItemCard from "./MemoryItemCard";
import type { MemoryItem } from "../api";

function makeMemory(overrides: Partial<MemoryItem> = {}): MemoryItem {
  return {
    id: "mem-1",
    scope: "domain",
    domain_id: "build-domain-id",
    kind: "goal",
    title: "Ship the release",
    status: "active",
    importance: 3,
    confidence: 1,
    sensitivity: "normal",
    event_date: null,
    created_at: "2026-09-06T00:00:00Z",
    updated_at: "2026-09-06T00:00:00Z",
    current_version_id: "v1",
    supersedes_id: null,
    superseded_by_id: null,
    ...overrides,
  };
}

describe("MemoryItemCard — status/title layout", () => {
  it("renders the status label as plain text with no leading plus sign — a passive state, not an add action", () => {
    render(<MemoryItemCard memory={makeMemory({ status: "active" })} onChanged={vi.fn()} />);
    const status = screen.getByText("active");
    expect(status.textContent).toBe("active");
    expect(status.textContent?.startsWith("+")).toBe(false);
  });

  it("renders the record-type badge and status badge in a metadata row separate from the title", () => {
    const { container } = render(<MemoryItemCard memory={makeMemory()} onChanged={vi.fn()} />);
    const header = container.querySelector(".memory-card-header")!;
    const title = container.querySelector(".memory-card-title")!;
    expect(header).not.toBeNull();
    expect(title).not.toBeNull();
    // The title is not inside the metadata row; it's its own row below it.
    expect(header.contains(title)).toBe(false);
    expect(title.textContent).toBe("Ship the release");
  });

  it("keeps the status badge out of normal absolutely-positioned layout — real DOM order, not floated over the card", () => {
    const { container } = render(<MemoryItemCard memory={makeMemory()} onChanged={vi.fn()} />);
    const statusWrapper = container.querySelector(".memory-status")!;
    const computed = window.getComputedStyle(statusWrapper);
    expect(computed.position).not.toBe("absolute");
  });

  it("a long title never sits inside the metadata row, so it cannot collide with either badge", () => {
    const longTitle =
      "This is a deliberately long memory title used to confirm the metadata row never has to shrink around it or overlap the status badge";
    const { container } = render(<MemoryItemCard memory={makeMemory({ title: longTitle })} onChanged={vi.fn()} />);
    const header = container.querySelector(".memory-card-header")!;
    expect(header.textContent).not.toContain(longTitle);
    expect(screen.getByText(longTitle)).toHaveClass("memory-card-title");
  });

  it("still renders Edit, Archive, Version history, and Delete permanently actions below the title", () => {
    render(<MemoryItemCard memory={makeMemory()} onChanged={vi.fn()} />);
    expect(screen.getByRole("button", { name: "Edit" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Archive" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Version history" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Delete permanently" })).toBeInTheDocument();
  });
});
