/** The backend stores timestamps in UTC but SQLite/SQLAlchemy strips
 * timezone info on retrieval, so every timestamp the API sends looks like
 * "2026-09-04T12:17:40.120323" — no "Z", no offset. JavaScript's `Date`
 * parser treats a date-time string with no timezone marker as *local*
 * time, not UTC (unlike a date-only string, which defaults to UTC) — so
 * parsing that string directly silently misinterprets an actual UTC value
 * as already-local, displaying a time that's off by exactly the viewer's
 * UTC offset. Every caller must go through this function rather than
 * constructing `new Date(iso)` directly from a raw API timestamp. */
function asUtcDate(iso: string): Date {
  const hasTimezone = /Z$|[+-]\d{2}:?\d{2}$/.test(iso);
  return new Date(hasTimezone ? iso : `${iso}Z`);
}

/** House format already established across BriefingStrip/MissionFocusRail/
 * RecallCentre/ResearchCentre/DecisionCentre — "Sep 4, 12:17 PM" in the
 * viewer's own local timezone. Returns `fallback` (default empty string)
 * for a missing/null timestamp. */
export function formatDateTime(iso: string | null | undefined, fallback = ""): string {
  if (!iso) return fallback;
  return asUtcDate(iso).toLocaleString(undefined, { month: "short", day: "numeric", hour: "2-digit", minute: "2-digit" });
}
