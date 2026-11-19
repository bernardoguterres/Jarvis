// A voice question asked from Home or a Centre page goes to the ambient
// general conversation, which has no domain of its own, so BODY's Google
// Health data and records never reached the model and it could only send
// Bernardo to BODY. When his own words clearly name a health topic, that
// one turn includes BODY (D119). The match is a fixed word list, never a
// model call, and it can only ever add BODY: MIND and PEOPLE are never
// included this way.

const HEALTH_TOPIC_PATTERNS: RegExp[] = [
  /\bgoogle health\b/,
  /\bfitbit\b/,
  /\bpixel watch\b/,
  /\bhealth (?:data|stats|statistics|metrics|numbers|summary)\b/,
  /\bmy health\b/,
  /\bsleep(?:ing)?\b/,
  /\bslept\b/,
  /\bsteps\b/,
  /\bstep count\b/,
  /\bheart ?rate\b/,
  /\bhrv\b/,
  /\bpulse\b/,
  /\bmy weight\b/,
  /\bweigh(?:ed|ing)?\b/,
  /\bbody fat\b/,
  /\bcalories\b/,
  /\bworkouts?\b/,
  /\bexercis(?:e|es|ed|ing)\b/,
  /\bknee\b/,
];

/** Returns the health phrase found in `text` (as written, lowercased), or
 * null when there is none. */
export function findHealthTopic(text: string): string | null {
  const normalized = text.toLowerCase().replace(/[’']/g, "'");
  let best: { index: number; phrase: string } | null = null;
  for (const pattern of HEALTH_TOPIC_PATTERNS) {
    const match = pattern.exec(normalized);
    if (match && (best === null || match.index < best.index)) best = { index: match.index, phrase: match[0] };
  }
  return best?.phrase ?? null;
}
