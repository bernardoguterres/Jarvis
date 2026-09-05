/** The one authoritative domain shortcut/display-order mapping — every
 * place that shows or interprets a "1"-"6" domain number (Home's orbital
 * badges, a domain view's header emblem badge, the `1`-`6` keyboard
 * shortcuts) must derive it from here, never maintain its own array.
 *
 * This is alphabetical by slug, which is also exactly what the backend
 * returns from `GET /api/domains` (`order_by(Domain.slug)`,
 * `backend/app/routers/domains.py`) — so Home's badges (numbered by
 * `fetchDomains()`'s response order) and everything here always agree by
 * construction, not by coincidence kept in sync by hand. This is a
 * presentation/navigation-order concern only: domain slugs, database
 * identities, stored records, and context-isolation logic are completely
 * unaffected by this file. */
export const DOMAIN_SLUG_ORDER = ["body", "build", "life", "mind", "path", "people"] as const;

export type DomainSlug = (typeof DOMAIN_SLUG_ORDER)[number];

function isDomainSlug(value: string): value is DomainSlug {
  return (DOMAIN_SLUG_ORDER as readonly string[]).includes(value);
}

/** 1-6 for a known domain slug, or `null` for anything else (never 0 or a
 * silently wrong guess). */
export function domainNumber(slug: string): number | null {
  return isDomainSlug(slug) ? DOMAIN_SLUG_ORDER.indexOf(slug) + 1 : null;
}

/** The inverse of `domainNumber` — used by the `1`-`6` keyboard shortcut
 * handler. `n` is 1-indexed to match the physical key pressed. */
export function domainSlugForNumber(n: number): DomainSlug | null {
  return n >= 1 && n <= DOMAIN_SLUG_ORDER.length ? DOMAIN_SLUG_ORDER[n - 1] : null;
}
