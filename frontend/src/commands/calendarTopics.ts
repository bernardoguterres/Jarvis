// The calendar counterpart of healthTopics.ts. Google Calendar data only
// enters a turn when LIFE is in scope, so a Home voice question such as
// "what's on tomorrow?" could only be answered with "switch to LIFE". When
// Bernardo's own words clearly ask about his schedule, that one turn
// includes LIFE (D121). A fixed word list, never a model call; it can only
// ever add LIFE.

const CALENDAR_TOPIC_PATTERNS: RegExp[] = [
  /\bcalendar\b/,
  /\bschedule\b/,
  /\bagenda\b/,
  /\bmeetings?\b/,
  /\bappointments?\b/,
  /\breminders?\b/,
  /\b(?:my|any|next|upcoming) events?\b/,
  /\bam i (?:free|busy|available)\b/,
  /\b(?:free|busy) (?:today|tomorrow|tonight|this|next|on|at)\b/,
  /\bwhat(?:'s| is) on\b/,
  /\bwhat do i have\b/,
  /\bwhat have i got\b/,
  /\bwhat am i doing (?:today|tomorrow|tonight|this|next|on|at)\b/,
  /\b(?:my|any) plans\b/,
  /\bplans (?:for|this|tomorrow|today|tonight)\b/,
  /\bcoming up\b/,
  /\b(?:when|what time) is my\b/,
];

// "Don't check my calendar" asks for the opposite, so LIFE is not added.
const NEGATED_CALENDAR_PATTERN =
  /\b(?:don'?t|do not|never|without|no need to)\b[^.?!]{0,30}\b(?:calendar|schedule|agenda|meetings?|appointments?|events?)\b/;

/** Returns the calendar phrase found in `text` (lowercased), or null when
 * there is none or the text asks not to use the calendar. */
export function findCalendarTopic(text: string): string | null {
  const normalized = text.toLowerCase().replace(/[’']/g, "'");
  if (NEGATED_CALENDAR_PATTERN.test(normalized)) return null;
  let best: { index: number; phrase: string } | null = null;
  for (const pattern of CALENDAR_TOPIC_PATTERNS) {
    const match = pattern.exec(normalized);
    if (match && (best === null || match.index < best.index)) best = { index: match.index, phrase: match[0] };
  }
  return best?.phrase ?? null;
}
