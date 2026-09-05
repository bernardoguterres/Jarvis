// A deterministic, allowlisted, model-independent interface-command
// registry and parser. This never guesses via Hermes or any model — it is
// plain string normalization plus a fixed alias table, shared by the
// Command Palette (typed input) and DomainView's voice transcript handling
// (spoken input), so both surfaces agree on exactly the same set of safe
// navigation commands and the same refusal behavior for anything
// mutating/destructive.

export type CentreTarget =
  | "memory_centre"
  | "actions_centre"
  | "skills_centre"
  | "integrations_centre"
  | "routine_centre"
  | "data_management"
  | "recall_centre"
  | "research_centre"
  | "decision_centre";

export type DomainSlug = "body" | "mind" | "people" | "path" | "build" | "life";

// "general" opens the general Jarvis conversation itself — a scope, not a
// seventh domain (see docs/DECISIONS.md D75/D79).
export type NavigateTarget = "home" | "back" | "command_palette" | "general" | CentreTarget | `domain:${DomainSlug}`;

export interface SensitiveControl {
  navigateTo: CentreTarget;
  controlId: string; // matches a data-command-target attribute in the DOM
  controlLabel: string;
}

// Safe direct actions: read-only or trivially reversible, and execute
// immediately from anywhere (Home, a Centre, a domain conversation, the
// general conversation) without any confirmation step — CLAUDE.md §12's
// "Read" tier. Never anything that mutates external state or local
// configuration; those are `confirm_required` or the Phase 8 proposal
// lifecycle instead.
export type SafeAction =
  | { kind: "sync_provider"; provider: "google_calendar" | "google_health"; providerLabel: string }
  | { kind: "retry_connection" }
  | { kind: "run_routine"; routineType: "morning_briefing" | "evening_checkin" | "weekly_review"; routineLabel: string }
  // Mission Control (Phase 12D-adjacent — see CLAUDE.md §9's Mission
  // Control addendum): every one of these is a local, reversible,
  // non-Hermes state change on `focus_sessions` — never a Calendar/
  // memory/task mutation, so all six are CLAUDE.md §12 "Read"-tier safe
  // actions, same as sync_provider/run_routine above.
  | { kind: "focus_start"; durationMinutes: number | null }
  | { kind: "focus_pause" }
  | { kind: "focus_resume" }
  | { kind: "focus_complete" }
  | { kind: "focus_abandon" }
  | { kind: "focus_show_current" }
  | { kind: "focus_show_history" }
  // Phase 12D Unified Recall: a deterministic local search, never a model
  // call — reads exactly like the others in this table (never mutates
  // anything, never requires confirmation). `domainHint` is set only when
  // the phrase names a real domain as an explicit trailing scope ("...in
  // BODY") — resolved via the exact same DOMAIN_ALIASES table `findDomain`
  // already uses for plain navigation, never a second table.
  | { kind: "open_recall"; query: string; domainHint: DomainSlug | null };

// Confirmation-required actions: a real, named, consequential local
// configuration change — CLAUDE.md §12's "Confirm" tier. The registry only
// ever identifies *which* action was named; it never calls anything
// itself, and the UI must show an explicit confirm/cancel before the
// caller executes it.
export type ConfirmAction =
  | { kind: "disconnect_integration"; provider: "google_calendar" | "google_health"; providerLabel: string }
  | { kind: "export_data" };

export type ParsedCommand =
  | { kind: "navigate"; target: NavigateTarget; heard: string; interpreted: string }
  | { kind: "focus_control"; control: SensitiveControl; heard: string; interpreted: string }
  | { kind: "safe_action"; action: SafeAction; heard: string; interpreted: string }
  | { kind: "confirm_required"; action: ConfirmAction; heard: string; interpreted: string; warning: string }
  | { kind: "blocked"; heard: string; explanation: string }
  | { kind: "none"; heard: string };

const CENTRE_ALIASES: Record<CentreTarget, string[]> = {
  memory_centre: ["memory centre", "memory center", "memory"],
  actions_centre: ["actions centre", "actions center", "actions"],
  skills_centre: ["skills centre", "skills center", "skills"],
  integrations_centre: ["integrations centre", "integrations center", "integrations", "integration centre", "integration center"],
  routine_centre: ["routine centre", "routines centre", "routine center", "routines centre", "routines", "routine"],
  data_management: ["data management", "data centre", "data center", "export centre", "backups"],
  recall_centre: ["recall centre", "recall center", "recall", "search jarvis", "unified recall"],
  // Navigation only — deliberately no "research this for me" safe action.
  // A research workspace is only ever created or drafted by a direct
  // in-Centre action (CLAUDE.md's Phase 12E boundary); a spoken/typed
  // phrase may only open the Centre itself, never execute research.
  research_centre: ["research centre", "research center", "research", "research workspace", "open research", "show research centre"],
  // Navigation only — deliberately no autonomous "decide this for me"
  // action. Jarvis must never finalize or execute a decision on its own
  // (CLAUDE.md's Phase 12F boundary); a spoken/typed phrase may only ever
  // open the Decision Room itself.
  decision_centre: ["decision room", "decision centre", "decision center", "decisions", "open decisions", "show decision room", "review my decisions"],
};

const DOMAIN_ALIASES: Record<DomainSlug, string[]> = {
  body: ["body", "health area", "physical health", "fitness", "training"],
  mind: ["mind", "mind space", "mental health", "mood"],
  people: ["people", "people space", "relationships"],
  path: ["path", "career space", "career", "education", "learning"],
  build: ["build", "build space", "projects", "engineering", "code"],
  life: ["life", "life space", "calendar and finances"],
};

/** Runtime guard for a value that claims to be a `NavigateTarget` but
 * didn't come from `parseCommand` itself — e.g. a `link_target` string the
 * backend attaches to a Phase 12A briefing item (api.ts's `BriefingItem`).
 * Never trust such a string without this check first; an unrecognized
 * value must never navigate anywhere (see components/BriefingStrip.tsx). */
export function isNavigateTarget(value: string | null | undefined): value is NavigateTarget {
  if (!value) return false;
  if (value === "home" || value === "back" || value === "command_palette" || value === "general") return true;
  if (value in CENTRE_ALIASES) return true;
  if (value.startsWith("domain:")) {
    const slug = value.slice("domain:".length);
    return slug in DOMAIN_ALIASES;
  }
  return false;
}

const NAV_VERB_PREFIX = /^(open|show|go to|go|navigate to|take me to|display|switch to|jump to)\s+/;

// Every entry's `requires` regexes must ALL match, in any order — voice
// transcripts don't reliably preserve word order ("connect google
// calendar" vs "google calendar connect"), so this deliberately checks
// for the presence of each required word rather than a fixed sequence.
// More specific entries (disconnect, writing, auto-sync) are listed before
// the plain "connect" entries they'd otherwise also match, since the first
// entry whose every `requires` regex matches wins.
const SENSITIVE_CONTROLS: Array<{ requires: RegExp[]; control: SensitiveControl }> = [
  { requires: [/\bcalendar\b/, /\bwriting\b/], control: { navigateTo: "integrations_centre", controlId: "google_calendar.enable_writing", controlLabel: "Enable Calendar writing" } },
  { requires: [/\bcalendar\b/, /\b(auto(matic)? sync|sync schedule)\b/], control: { navigateTo: "integrations_centre", controlId: "google_calendar.auto_sync_toggle", controlLabel: "Automatic sync (Google Calendar)" } },
  { requires: [/\bcalendar\b/, /\bconnect\b/], control: { navigateTo: "integrations_centre", controlId: "google_calendar.connect", controlLabel: "Connect (Google Calendar)" } },
  { requires: [/\bhealth\b/, /\b(auto(matic)? sync|sync schedule)\b/], control: { navigateTo: "integrations_centre", controlId: "google_health.auto_sync_toggle", controlLabel: "Automatic sync (Google Health)" } },
  { requires: [/\bhealth\b/, /\bconnect\b/], control: { navigateTo: "integrations_centre", controlId: "google_health.connect", controlLabel: "Connect (Google Health)" } },
];

// Confirmation-required (CLAUDE.md §12 "Confirm" tier): a real, named,
// consequential local configuration change. The registry only ever names
// *which* action was requested — it never calls anything itself. Checked
// before SENSITIVE_CONTROLS/BLOCKED_VERBS so "disconnect google calendar"
// resolves here (a real confirm dialog, then a real disconnect if
// accepted) rather than being merely shown or refused outright.
const CONFIRM_ACTIONS: Array<{ requires: RegExp[]; action: ConfirmAction; interpreted: string; warning: string }> = [
  {
    requires: [/\bcalendar\b/, /\bdisconnect\b/],
    action: { kind: "disconnect_integration", provider: "google_calendar", providerLabel: "Google Calendar" },
    interpreted: "Disconnect Google Calendar",
    warning: "This disconnects Google Calendar — cached events stay local, but sync stops until you reconnect.",
  },
  {
    requires: [/\bhealth\b/, /\bdisconnect\b/],
    action: { kind: "disconnect_integration", provider: "google_health", providerLabel: "Google Health" },
    interpreted: "Disconnect Google Health",
    warning: "This disconnects Google Health — cached data stays local, but sync stops until you reconnect.",
  },
  {
    requires: [/\bexport\b/, /\b(data|jarvis|everything)\b/],
    action: { kind: "export_data" },
    interpreted: "Export Jarvis data",
    warning: "This creates a full local export archive now.",
  },
];

// Safe direct actions (CLAUDE.md §12 "Read" tier): read-only or trivially
// reversible, so these execute immediately from anywhere with no
// confirmation step. Checked before BLOCKED_VERBS for the same reason as
// CONFIRM_ACTIONS above — "sync calendar" must resolve here, not be
// refused as a generic mutating phrase. `excludes` (checked first, if
// present) keeps a broad word like "sync" from shadowing the more
// specific "automatic sync" *schedule toggle* phrasing, which stays a
// SENSITIVE_CONTROLS focus_control (a real configuration change, not a
// one-shot read-only sync).
const SAFE_ACTIONS: Array<{ requires: RegExp[]; excludes?: RegExp[]; action: SafeAction; interpreted: string }> = [
  {
    requires: [/\bcalendar\b/, /\bsync\b/],
    excludes: [/\bauto(matic)?\b/, /\bschedule\b/],
    action: { kind: "sync_provider", provider: "google_calendar", providerLabel: "Google Calendar" },
    interpreted: "Sync Google Calendar now",
  },
  {
    requires: [/\bhealth\b/, /\bsync\b/],
    excludes: [/\bauto(matic)?\b/, /\bschedule\b/],
    action: { kind: "sync_provider", provider: "google_health", providerLabel: "Google Health" },
    interpreted: "Sync Google Health now",
  },
  {
    requires: [/\brun\b/, /\bmorning\b/, /\bbriefing\b/],
    action: { kind: "run_routine", routineType: "morning_briefing", routineLabel: "Morning Briefing" },
    interpreted: "Run Morning Briefing now",
  },
  {
    requires: [/\brun\b/, /\bevening\b/, /\bcheck(-|\s)?in\b/],
    action: { kind: "run_routine", routineType: "evening_checkin", routineLabel: "Evening Check-in" },
    interpreted: "Run Evening Check-in now",
  },
  {
    requires: [/\brun\b/, /\bweekly\b/, /\breview\b/],
    action: { kind: "run_routine", routineType: "weekly_review", routineLabel: "Weekly Review" },
    interpreted: "Run Weekly Review now",
  },
  // Mission Control lifecycle controls — never require confirmation (they
  // never touch Calendar/memory/an external system), so they're safe
  // actions like everything else in this table, and get the exact same
  // negation/question gating below.
  {
    requires: [/\bpause\b/, /\b(focus|mission|session)\b/],
    action: { kind: "focus_pause" },
    interpreted: "Pause the current focus session",
  },
  {
    requires: [/\bresume\b/, /\b(focus|mission|session)\b/],
    action: { kind: "focus_resume" },
    interpreted: "Resume the current focus session",
  },
  {
    requires: [/\b(complete|finish)\b/, /\b(focus|mission|session)\b/],
    action: { kind: "focus_complete" },
    interpreted: "Complete the current focus session",
  },
  {
    requires: [/\babandon\b/, /\b(focus|mission|session)\b/],
    action: { kind: "focus_abandon" },
    interpreted: "Abandon the current focus session",
  },
];

// "Start focus" needs a captured duration ("focus on this for 45 minutes"),
// which SAFE_ACTIONS' static requires/action table can't express — matched
// separately, but through the exact same explanatoryOnly (negation/
// question) gate as everything else in that table (see parseCommand).
// Anchored at the start of the (already-normalized) text, unlike
// SAFE_ACTIONS' keyword-presence matching, to avoid firing on ordinary
// conversation that merely mentions "focus" in passing.
const FOCUS_START_PATTERN =
  /^(start( a| the)? focus( session)?( on (this|it))?|begin( a| the)? focus( session)?( on (this|it))?|focus on (this|it))\b/;
const FOCUS_DURATION_PATTERN = /(\d{1,3})\s*(minutes?|mins?)\b/;

function matchFocusStart(normalized: string): Extract<SafeAction, { kind: "focus_start" }> | null {
  if (!FOCUS_START_PATTERN.test(normalized)) return null;
  const durationMatch = FOCUS_DURATION_PATTERN.exec(normalized);
  const minutes = durationMatch ? parseInt(durationMatch[1], 10) : null;
  return { kind: "focus_start", durationMinutes: minutes !== null && minutes >= 5 && minutes <= 180 ? minutes : null };
}

// Phase 12D Unified Recall: three natural phrasings. Each strips its own
// leading trigger phrase, leaving the rest of the text to inspect for a
// TRAILING "in my memories" (no domain scope, just strips the phrase) or
// "in <domain>" clause (scopes the search — resolved via the exact same
// DOMAIN_ALIASES/findDomain table plain navigation already uses, never a
// second domain table). An ordinary query that merely happens to contain
// " in " but whose trailing segment isn't a real domain or "my memories"
// (e.g. "search jarvis for coffee in Lisbon") is never mis-split — the
// whole remainder is kept as the query text.
//
// "find X" alone (with no "in my memories"/domain qualifier) is
// deliberately NOT matched — "find" is far too common in ordinary
// conversation ("find out if...", "find the article about...") to safely
// treat as a search-Jarvis command without a qualifier; "search jarvis
// for X" and "look up X" are unambiguous enough on their own.
const OPEN_RECALL_TRIGGERS: Array<{ pattern: RegExp; requiresInClause: boolean }> = [
  { pattern: /^search( jarvis| my (memories|jarvis))? for\s+(?<rest>.+)$/, requiresInClause: false },
  { pattern: /^find\s+(?<rest>.+)$/, requiresInClause: true },
  { pattern: /^look\s*up\s+(?<rest>.+)$/, requiresInClause: false },
];

function matchOpenRecall(normalized: string): Extract<SafeAction, { kind: "open_recall" }> | null {
  let rest: string | null = null;
  let requiresInClause = false;
  for (const { pattern, requiresInClause: needsClause } of OPEN_RECALL_TRIGGERS) {
    const match = pattern.exec(normalized);
    if (match?.groups?.rest) {
      rest = match.groups.rest.trim();
      requiresInClause = needsClause;
      break;
    }
  }
  if (!rest) return null;

  const inMatch = /^(.+?)\s+in\s+(.+)$/.exec(rest);
  if (inMatch) {
    const trailing = inMatch[2].trim();
    if (trailing === "my memories" || trailing === "memories") {
      return { kind: "open_recall", query: inMatch[1].trim(), domainHint: null };
    }
    const domain = findDomain(trailing);
    if (domain) {
      return { kind: "open_recall", query: inMatch[1].trim(), domainHint: domain };
    }
  }
  // "find X" requires an explicit qualifier ("in my memories"/"in
  // <domain>") — if none resolved above, this isn't a confident enough
  // match to treat as a command.
  if (requiresInClause) return null;
  return { kind: "open_recall", query: rest, domainHint: null };
}

// Pure reads (never start/pause/resume/complete/abandon anything) —
// matched as exact aliases, same as RETRY_CONNECTION_ALIASES/
// GENERAL_CONVERSATION_ALIASES below, and for the same reason those two
// need no negation/question gate: a negated phrase ("don't show mission
// history") is a different string than the alias itself and simply fails
// to match, and a genuine question phrasing ("what did I accomplish
// today?") is deliberately usable here as a real trigger — CLAUDE.md's
// Mission Control core-experience list names it explicitly as a command,
// not a request for an explanation the way "what happens if I finish
// this?" is for the mutating focus_complete action above.
const SHOW_CURRENT_MISSION_ALIASES = [
  "show current mission",
  "show my current mission",
  "show current focus",
  "show my focus session",
  "current focus session",
  "current mission",
  "what am i focusing on",
  "what should i focus on now",
  "what's my current mission",
];
const SHOW_MISSION_HISTORY_ALIASES = [
  "show mission history",
  "show my mission history",
  "show focus history",
  "show my focus history",
  "show my sessions",
  "what did i accomplish today",
  "what have i completed today",
];

const RETRY_CONNECTION_ALIASES = ["retry connection", "retry the connection", "reconnect", "retry connecting"];
const GENERAL_CONVERSATION_ALIASES = [
  "talk to jarvis",
  "ask jarvis",
  "general conversation",
  "start a new conversation",
  "start a general conversation",
  "start a new general conversation",
];

// Verbs that mutate, execute, or reach an external service. Never
// auto-clicked, even when a specific control is identified above (those
// still only navigate + focus + explain, never click) — this list exists
// to catch every OTHER mutating phrasing that doesn't match a known
// control, so it can still be refused explicitly rather than silently
// ignored or, worse, misrouted into a conversation turn.
const BLOCKED_VERBS = /\b(connect|disconnect|enable|disable|delete|remove|restore|import|approve|deny|reject|execute|run\s*now|sync\s*now|archive|unarchive)\b/;

// The blocked-verb check only fires alongside one of these — a mutating
// verb used in ordinary domain conversation ("I need to delete this bad
// habit") must never be misread as a UI command. Requiring a system noun
// too keeps the refusal scoped to genuine attempts to operate Jarvis's own
// controls, not incidental word choice in a real conversation.
const SYSTEM_NOUN = /\b(calendar|health|integration|action|skill|routine|backup|export|import|document|file|archive|memory|record|schedule|sync)\b/;

const POSITIONAL_SELECTION = /\b(press|click|tap)\s+the\s+(first|second|third|fourth|fifth|\d+(st|nd|rd|th)?)\s+(button|item|option)\b/;

// CONFIRM_ACTIONS/SAFE_ACTIONS match by keyword *presence*, not sequence or
// grammar (see the comment above SENSITIVE_CONTROLS) — "don't disconnect
// google calendar" contains exactly the same keywords as "disconnect
// google calendar" and would otherwise resolve identically. A safe_action
// executes immediately with no confirmation step at all, so this is a real
// gap, not a cosmetic one: reliability-audit finding, D83/D84. Checked once
// and used to skip only those two tables — SENSITIVE_CONTROLS stays
// unaffected by negation, since it never activates anything regardless
// ("shows, does not activate"), so a negated phrase merely navigating to
// and highlighting a control is harmless either way.
const NEGATION_PATTERN = /\b(don'?t|do not|never|shouldn'?t|should not|won'?t|will not|not now)\b/;

// The same keyword-presence matching means a genuine QUESTION about a
// command ("what does sync calendar do", "how do I export data") contains
// the identical keywords as the command itself — "what does sync calendar
// do" previously resolved to safe_action and ran a real sync immediately,
// purely from being asked what it does. Matches a leading question word/
// phrase; a trailing "?" is checked separately in parseCommand against the
// un-normalized text, since normalize() strips trailing punctuation before
// this would ever see it. Reliability-audit finding, D83/D84.
const QUESTION_PATTERN = /^(what|how|why|when|who|which|can you|could you|would you|does|is|are|will|should)\b/;

function normalize(text: string): string {
  return text
    .toLowerCase()
    .trim()
    .replace(/[.!?]+$/, "")
    .replace(/\s+/g, " ");
}

// Deliberately exact-match only (against the string with a leading nav
// verb already stripped) rather than "contains" or "ends with" matching.
// A looser match would let an ordinary sentence that happens to end in a
// domain word ("This knee pain is really affecting my body") get silently
// rerouted into a navigation command instead of being sent as a real
// conversation message — exactness is what keeps this deterministic and
// safe to run on every voice transcript, not just palette queries typed
// with clear intent.
function matchAlias(exact: string, aliases: string[]): boolean {
  return aliases.includes(exact);
}

function findCentre(exact: string): CentreTarget | null {
  for (const [centre, aliases] of Object.entries(CENTRE_ALIASES) as [CentreTarget, string[]][]) {
    if (matchAlias(exact, aliases)) return centre;
  }
  return null;
}

function findDomain(exact: string): DomainSlug | null {
  for (const [slug, aliases] of Object.entries(DOMAIN_ALIASES) as [DomainSlug, string[]][]) {
    if (matchAlias(exact, aliases)) return slug;
  }
  return null;
}

/**
 * Parse free text (typed or transcribed) into a deterministic command.
 * `inDomain` indicates whether there's currently an active domain
 * conversation to fall back to when nothing matches — see the `none`
 * result's handling contract in the caller (DomainView continues the
 * conversation; outside a domain the caller should ask the user to pick
 * one rather than send anything ambiguous anywhere).
 */
export function parseCommand(rawText: string): ParsedCommand {
  const heard = rawText.trim();
  const normalized = normalize(heard);
  if (!normalized) return { kind: "none", heard };

  if (POSITIONAL_SELECTION.test(normalized)) {
    return {
      kind: "blocked",
      heard,
      explanation: "Jarvis never selects a control by its position on screen — say what the control actually is (e.g. its label) instead.",
    };
  }

  if (normalized === "go home" || normalized === "home" || normalized === "jarvis home" || normalized === "0" || normalized === "zero") {
    return { kind: "navigate", target: "home", heard, interpreted: "Go home" };
  }
  if (normalized === "go back" || normalized === "back") {
    return { kind: "navigate", target: "back", heard, interpreted: "Go back" };
  }
  if (normalized === "open command palette" || normalized === "command palette") {
    return { kind: "navigate", target: "command_palette", heard, interpreted: "Open command palette" };
  }
  if (RETRY_CONNECTION_ALIASES.includes(normalized)) {
    return { kind: "safe_action", action: { kind: "retry_connection" }, heard, interpreted: "Retry connection" };
  }
  if (GENERAL_CONVERSATION_ALIASES.includes(normalized)) {
    return { kind: "navigate", target: "general", heard, interpreted: "Talk to Jarvis" };
  }
  if (SHOW_CURRENT_MISSION_ALIASES.includes(normalized)) {
    return { kind: "safe_action", action: { kind: "focus_show_current" }, heard, interpreted: "Show current mission" };
  }
  if (SHOW_MISSION_HISTORY_ALIASES.includes(normalized)) {
    return { kind: "safe_action", action: { kind: "focus_show_history" }, heard, interpreted: "Show mission history" };
  }

  // Negated phrasing ("don't disconnect google calendar", "never sync
  // health") and genuine questions ("what does sync calendar do", "how do
  // I export data?") must not resolve to the same result as the affirmative
  // command — CONFIRM_ACTIONS/SAFE_ACTIONS match on keyword presence
  // regardless of grammar, so without this check a safe_action would
  // execute immediately despite the user only asking or explicitly saying
  // not to. Skips only these two tables; see NEGATION_PATTERN's comment
  // for why SENSITIVE_CONTROLS is unaffected — the same reasoning applies
  // to questions (it's still only "show, don't activate").
  const explanatoryOnly = NEGATION_PATTERN.test(normalized) || QUESTION_PATTERN.test(normalized) || heard.trim().endsWith("?");

  // Confirmation-required actions are checked before the plain sensitive
  // controls and the blocked-verb catch-all below, since a real named
  // action ("disconnect google calendar", "export data") resolves to a
  // genuine confirm dialog here, not a passive "go look at it yourself"
  // or an outright refusal.
  if (!explanatoryOnly) {
    for (const { requires, action, interpreted, warning } of CONFIRM_ACTIONS) {
      if (requires.every((re) => re.test(normalized))) {
        return { kind: "confirm_required", action, heard, interpreted, warning };
      }
    }
  }

  // Safe direct actions — read-only or trivially reversible, execute
  // immediately, checked before the sensitive controls/blocked-verb
  // catch-all for the same reason.
  if (!explanatoryOnly) {
    const focusStart = matchFocusStart(normalized);
    if (focusStart) {
      return {
        kind: "safe_action",
        action: focusStart,
        heard,
        interpreted: focusStart.durationMinutes
          ? `Start a focus session for ${focusStart.durationMinutes} minutes`
          : "Start a focus session",
      };
    }
    const openRecall = matchOpenRecall(normalized);
    if (openRecall) {
      return {
        kind: "safe_action",
        action: openRecall,
        heard,
        interpreted: openRecall.domainHint
          ? `Search "${openRecall.query}" in ${openRecall.domainHint.toUpperCase()}`
          : `Search Jarvis for "${openRecall.query}"`,
      };
    }
    for (const { requires, excludes, action, interpreted } of SAFE_ACTIONS) {
      if (excludes?.some((re) => re.test(normalized))) continue;
      if (requires.every((re) => re.test(normalized))) {
        return { kind: "safe_action", action, heard, interpreted };
      }
    }
  }

  // A sensitive-control phrase can appear combined with an explicit
  // navigation verb ("go to integrations and show google health automatic
  // sync") or on its own ("show the google calendar disconnect button") —
  // check this before the generic blocked-verb catch-all below, since
  // these DO resolve to a specific, safely-navigable target.
  for (const { requires, control } of SENSITIVE_CONTROLS) {
    if (requires.every((re) => re.test(normalized))) {
      return {
        kind: "focus_control",
        control,
        heard,
        interpreted: `Show ${control.controlLabel} in Integrations Centre`,
      };
    }
  }

  const withoutVerb = normalized.replace(NAV_VERB_PREFIX, "");

  const centre = findCentre(withoutVerb);
  if (centre) {
    const label = CENTRE_LABELS[centre];
    return { kind: "navigate", target: centre, heard, interpreted: `Open ${label}` };
  }

  const domain = findDomain(withoutVerb);
  if (domain) {
    return { kind: "navigate", target: `domain:${domain}`, heard, interpreted: `Go to ${domain.toUpperCase()}` };
  }

  // Nothing safe matched. If it still looks like an instruction to mutate
  // or reach an external system, refuse explicitly rather than letting it
  // fall through silently (e.g. into a conversation turn that might be
  // misread as authorization).
  if (BLOCKED_VERBS.test(normalized) && SYSTEM_NOUN.test(normalized)) {
    return {
      kind: "blocked",
      heard,
      explanation: "That sounds like it would change or connect something. Jarvis never does that from a spoken or typed command alone — open the relevant centre and confirm it there yourself.",
    };
  }

  return { kind: "none", heard };
}

const CENTRE_LABELS: Record<CentreTarget, string> = {
  memory_centre: "Memory Centre",
  actions_centre: "Actions Centre",
  skills_centre: "Skills Centre",
  integrations_centre: "Integrations Centre",
  routine_centre: "Routine Centre",
  data_management: "Data Management",
  recall_centre: "Recall",
  research_centre: "Research",
  decision_centre: "Decision Room",
};

export { CENTRE_ALIASES, DOMAIN_ALIASES, CENTRE_LABELS };
