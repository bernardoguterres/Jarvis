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
  // Everyday wordings found missing in real use (D120). Kept to phrases that
  // are about Bernardo's own body, so "run the tests" or "walk me through"
  // never match.
  /\bdid i (?:run|walk|train|exercise|work out)\b/,
  /\bhow far did i\b/,
  /\b(?:my|last|latest|recent|next) (?:runs?|walks?|jogs?|rides?|swims?|gym session|training session)\b/,
  /\bwalk(?:ed)? enough\b/,
  /\bjog(?:ged|ging)?\b/,
  /\bgym\b/,
  /\bshould i (?:train|run|rest|work out)\b/,
  /\brest day\b/,
  /\bphysically\b/,
  /\bmy fitness\b/,
  /\bwork(?:ing)? out\b(?! (?:how|what|why|whether|if|the|a|this|that|which|when|where))/,
];

// "Don't look at my health data" names a health topic but asks for the
// opposite, so BODY is not added. Only a negation shortly before a health
// word counts.
const NEGATED_HEALTH_PATTERN =
  /\b(?:don'?t|do not|never|without|no need to)\b[^.?!]{0,30}\b(?:health|body|fitness|sleep|weight|steps|workouts?)\b/;

/** Returns the health phrase found in `text` (as written, lowercased), or
 * null when there is none or the text asks not to use health data. */
export function findHealthTopic(text: string): string | null {
  const normalized = text.toLowerCase().replace(/[’']/g, "'");
  if (NEGATED_HEALTH_PATTERN.test(normalized)) return null;
  let best: { index: number; phrase: string } | null = null;
  for (const pattern of HEALTH_TOPIC_PATTERNS) {
    const match = pattern.exec(normalized);
    if (match && (best === null || match.index < best.index)) best = { index: match.index, phrase: match[0] };
  }
  return best?.phrase ?? null;
}
