/** Shared between ResearchCentre.tsx and DecisionCentre.tsx so both
 * surfaces never drift into inconsistent handling of a model-generated
 * draft/critique's "[n]" citation markers. */

export interface ParsedTextRun {
  text: string;
  citationNumber: number | null;
}

/** Splits model-generated text on "[n]" citation markers so each chunk
 * can be rendered as plain text (never HTML/executable) with a clearly-
 * flagged, distinct treatment for a number that doesn't resolve to any
 * citation actually supplied to the model. */
export function splitOnCitations(text: string): ParsedTextRun[] {
  const runs: ParsedTextRun[] = [];
  const pattern = /\[(\d+)\]/g;
  let lastIndex = 0;
  let match: RegExpExecArray | null;
  while ((match = pattern.exec(text)) !== null) {
    if (match.index > lastIndex) runs.push({ text: text.slice(lastIndex, match.index), citationNumber: null });
    runs.push({ text: match[0], citationNumber: Number(match[1]) });
    lastIndex = match.index + match[0].length;
  }
  if (lastIndex < text.length) runs.push({ text: text.slice(lastIndex), citationNumber: null });
  return runs;
}
