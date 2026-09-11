import type { CSSProperties } from "react";
import { Activity, Boxes, Brain, CalendarDays, Compass, UsersRound, type LucideIcon } from "lucide-react";
import { DOMAIN_SLUG_ORDER, type DomainSlug } from "../domainOrder";

function isDomainGlyphSlug(value: string): value is DomainSlug {
  return (DOMAIN_SLUG_ORDER as readonly string[]).includes(value);
}

/** The one canonical icon per domain (`docs/DECISIONS.md` D94) — official
 * `lucide-react` icons, chosen and approved directly by Bernardo, not a
 * hand-drawn approximation. Do not redraw or reinterpret these; if a
 * domain's icon ever needs to change, that is a deliberate future
 * decision, not something to explore speculatively. Only these six named
 * imports are used (never a barrel/wildcard import) so tree-shaking keeps
 * the rest of the Lucide set out of the bundle. */
const ICONS: Record<DomainSlug, LucideIcon> = {
  body: Activity,
  build: Boxes,
  life: CalendarDays,
  mind: Brain,
  path: Compass,
  people: UsersRound,
};

/** The one stroke weight every glyph renders at, in the icon's own 24×24
 * viewBox units — since CSS (never this component) controls the
 * rendered pixel size (`.domain-node-glyph` for Home, `.domain-glyph`'s
 * base rule for the header emblem), a shared viewBox-relative stroke
 * width already scales proportionally with whatever size CSS assigns, so
 * every icon stays equally weighted rather than some reading thicker or
 * thinner than its peers. `absoluteStrokeWidth` is set too, as a second,
 * explicit guarantee independent of how the element ends up sized. */
const STROKE_WIDTH = 1.75;

/** Every Lucide icon shares one 24×24 viewBox, but each icon's own drawn
 * content fills a different fraction of that square (a thin diagonal
 * "Activity" line versus a wide, near-edge-to-edge "UsersRound"
 * silhouette) — so identical CSS width/height do not read as identical
 * optical size. This is a small, deliberately narrow correction applied
 * uniformly across every context (Home orbit, header emblem, selector
 * chips) via a single `transform: scale()` on the glyph itself, never a
 * per-page override. It changes paint only — the element's layout box
 * (and therefore any surrounding badge/count-bubble position) is
 * unaffected, and `transform-origin: 50% 50%` keeps the icon centered in
 * place at every size and on every color/selection-state change. Revisit
 * these only alongside a deliberate, visually-verified icon audit — never
 * tune a single value in isolation from the other five. */
const OPTICAL_SCALE: Record<DomainSlug, number> = {
  body: 1.06,
  build: 0.97,
  life: 1,
  mind: 1,
  path: 1.05,
  people: 0.87,
};

/** The fixed set of semantic sizes every call site chooses from, rather
 * than an arbitrary per-page pixel/rem value:
 *  - "sm": compact metadata/inline contexts (a Recall/Mission Control
 *    result row's leading glyph).
 *  - "md": selectors, chips, and a domain view's own header emblem.
 *  - "lg" (the default, no extra class): Home's orbital nodes, which stay
 *    on their existing responsive `--node-size`-relative sizing rather
 *    than a fixed rem value, since they must scale continuously with the
 *    orbit's own responsive layout — but still resolve to one shared
 *    class (`domain-node-glyph`) so all six render at the same size. */
type DomainGlyphSize = "sm" | "md";

interface DomainGlyphProps {
  slug: string;
  size?: DomainGlyphSize;
  className?: string;
}

/** The one shared icon component for all six fixed Jarvis domains —
 * canonical `lucide-react` icons (never hand-drawn SVG, a raster image,
 * an emoji, or a first-letter fallback), rendered with `fill="none"`,
 * `currentColor`, and rounded caps/joins so they inherit this app's
 * violet/cyan state colors from their surrounding button/emblem rather
 * than carrying any color, background, glow, or animation of their own —
 * the Jarvis node/ring chrome around the icon owns all of that. The icon
 * itself never rotates or otherwise animates; only what's around it does.
 * Purely decorative (`aria-hidden`, `focusable="false"`, no `aria-label`
 * of its own) — the enclosing control's real accessible name (a domain
 * button's `aria-label`, or a domain view's `<h1>`) is always the single
 * source of truth for what a domain is called, both on Home and in the
 * domain header, since both call sites render this exact same component.
 * Falls back to rendering nothing for an unrecognized slug rather than
 * guessing. */
function DomainGlyph({ slug, size, className }: DomainGlyphProps) {
  if (!isDomainGlyphSlug(slug)) return null;
  const Icon = ICONS[slug];
  const sizeClass = size ? ` domain-glyph--${size}` : "";
  return (
    <Icon
      className={`domain-glyph${sizeClass}${className ? ` ${className}` : ""}`}
      style={{ "--domain-glyph-scale": OPTICAL_SCALE[slug] } as CSSProperties}
      strokeWidth={STROKE_WIDTH}
      absoluteStrokeWidth
      aria-hidden="true"
      focusable="false"
    />
  );
}

export default DomainGlyph;
