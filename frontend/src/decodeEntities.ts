/** Some server-rendered snapshot fields (Research/Decision evidence
 * `snippet_snapshot`, `backend/app/recall_service.py::make_snippet_html`)
 * are HTML-escaped once, server-side, so they can be safely used with
 * `dangerouslySetInnerHTML` when a query match needs a `<mark>` wrapper.
 * When that same escaped string is instead rendered as a plain React text
 * child (no highlighting needed), it must never be shown as raw escaped
 * text such as `What&#x27;s` — this is the one, single decode boundary
 * for that case.
 *
 * Deliberately a small, fixed lookup rather than a general HTML parser:
 * it only ever turns a known HTML entity back into its literal character,
 * so a decoded result can still be rendered safely as a plain React text
 * child afterwards (never via `dangerouslySetInnerHTML`) — React always
 * escapes a text child again before painting it, so even a decoded string
 * that happens to look like a tag (e.g. from a double-escaped `&lt;` or
 * already-literal `<script>`) is displayed as inert text, never parsed as
 * markup. Idempotent: text with no entities, or text already decoded,
 * passes through unchanged rather than being mangled or double-decoded. */
const ENTITIES: Record<string, string> = {
  "&amp;": "&",
  "&lt;": "<",
  "&gt;": ">",
  "&quot;": '"',
  "&#39;": "'",
  "&#x27;": "'",
  "&apos;": "'",
};

const ENTITY_PATTERN = /&(?:amp|lt|gt|quot|#39|#x27|apos);/g;

export function decodeHtmlEntities(text: string): string {
  if (!text) return text;
  return text.replace(ENTITY_PATTERN, (entity) => ENTITIES[entity] ?? entity);
}
