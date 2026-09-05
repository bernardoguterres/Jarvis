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

interface DomainGlyphProps {
  slug: string;
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
function DomainGlyph({ slug, className }: DomainGlyphProps) {
  if (!isDomainGlyphSlug(slug)) return null;
  const Icon = ICONS[slug];
  return (
    <Icon
      className={`domain-glyph${className ? ` ${className}` : ""}`}
      strokeWidth={STROKE_WIDTH}
      absoluteStrokeWidth
      aria-hidden="true"
      focusable="false"
    />
  );
}

export default DomainGlyph;
