import { describe, expect, it } from "vitest";
import { formatDateTime } from "./formatDateTime";

describe("formatDateTime", () => {
  it("returns the fallback (default empty string) for a null/undefined timestamp", () => {
    expect(formatDateTime(null)).toBe("");
    expect(formatDateTime(undefined)).toBe("");
    expect(formatDateTime(null, "—")).toBe("—");
  });

  it("treats a timezone-less API timestamp as UTC, not local time", () => {
    // Regression test for the actual bug: the backend sends timestamps
    // like "2026-09-04T12:00:00" with no "Z"/offset (SQLite/SQLAlchemy
    // strips timezone info on retrieval even though the value is stored
    // as UTC) — JavaScript's Date parser treats a timezone-less date-TIME
    // string as *local*, silently misinterpreting an actual UTC value.
    // Appending "Z" ourselves before parsing is what fixes this.
    const withoutZ = formatDateTime("2026-09-04T12:00:00");
    const withZ = formatDateTime("2026-09-04T12:00:00Z");
    expect(withoutZ).toBe(withZ);
  });

  it("does not double-append Z for a timestamp that already has one", () => {
    // If this regressed (e.g. "...ZZ"), Date parsing would fail and
    // produce "Invalid Date" instead of a real formatted string.
    const result = formatDateTime("2026-09-04T12:00:00Z");
    expect(result).not.toContain("Invalid");
  });

  it("does not double-append an offset for a timestamp that already has one", () => {
    const result = formatDateTime("2026-09-04T12:00:00+02:00");
    expect(result).not.toContain("Invalid");
  });
});
