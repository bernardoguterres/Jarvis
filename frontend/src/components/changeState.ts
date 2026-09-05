import type { BriefingChangeState } from "../api";

/** Shared between BriefingStrip.tsx and MissionFocusRail.tsx so the two
 * surfaces never drift into inconsistent labels for the same underlying
 * Phase 12B change-state value. */
export const CHANGE_LABEL: Record<BriefingChangeState, string> = {
  new: "NEW",
  changed: "CHANGED",
  ongoing: "ONGOING",
  resolved: "RESOLVED",
  reopened: "REOPENED",
};
