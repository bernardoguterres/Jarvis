import DomainGlyph from "./DomainGlyph";
import { domainNumber } from "../domainOrder";

interface DomainEmblemProps {
  slug: string;
  name: string;
}

/** A small circular domain identity badge for a domain view's own header —
 * the landing target for the Home→domain shared View Transition (see
 * `transitions/domainViewTransition.ts`). Deliberately much smaller than
 * Home's orbital node and carries no ring/sweep animation of its own: it
 * exists to give the morphing circle somewhere to resolve into, not to
 * turn every internal screen into another orbital scene. The
 * `data-domain-transition-slug` attribute is what lets the transition
 * helper find this element — it is the only thing that makes it a valid
 * transition target, the badge itself is otherwise ordinary content. The
 * bespoke `DomainGlyph` (Phase 6, D91) replaces the previous plain first-
 * letter mark; it's purely decorative (`aria-hidden`), never carrying its
 * own accessible name, so the domain view's real name/heading remains the
 * single source of truth. */
function DomainEmblem({ slug, name }: DomainEmblemProps) {
  const number = domainNumber(slug);
  return (
    <span className="domain-emblem" data-domain-transition-slug={slug} title={name} aria-hidden="true">
      <span className="domain-emblem-kbd">{number ?? ""}</span>
      <DomainGlyph slug={slug} />
    </span>
  );
}

export default DomainEmblem;
