import type { CSSProperties } from "react";
import type { Domain } from "../api";
import { DOMAIN_SUBTITLES } from "../domainSubtitles";
import DomainGlyph from "./DomainGlyph";
import { domainNumber } from "../domainOrder";

interface DomainNodeProps {
  domain: Domain;
  x: number;
  y: number;
  angleDeg: number;
  focusing?: boolean;
  onSelect: (slug: string) => void;
  /** Pointer entered — gated behind Home's hover-intent delay before the
   * hover ring actually activates. */
  onPointerEnter: (slug: string) => void;
  onPointerLeave: () => void;
  /** Keyboard focus — applied immediately, bypassing the pointer
   * hover-intent delay entirely (a keyboard user is never "passing
   * through" a node the way a moving pointer can be). */
  onFocus: (slug: string) => void;
  onBlur: () => void;
}

/** One orbital domain node. Position is passed in as container-relative
 * percentages (computed by Home from the node count) rather than fixed
 * pixel coordinates, so the layout stays proportional at any container
 * size. `angleDeg` is the same angle used to place the node, used only to
 * orient the short inward "connector" stub shown on hover/focus — it never
 * fabricates data, purely decorative. The node itself shows only the name
 * and a short fixed subtitle; the full truthful description lives in
 * Home's contextual info panel, not inside the circle.
 *
 * `.node-ring-outer`/`.node-ring-inner` are the node's own small echo of
 * JarvisCore's ring language — always rotating (index.css), just invisible
 * (opacity:0) until `:hover`/`:focus-within`/`.is-focusing` reveals it, so
 * it's already mid-turn rather than restarting from frame 0 every time.
 * `focusing` is true
 * both for the brief moment after a click (before navigating) and — via
 * Home's `commandFocusSlug` — when a typed/spoken command targets this
 * domain while already on Home; that's the only sense in which "the
 * selected domain" is a real, trackable state here (Home unmounts once a
 * domain is actually open, so there's nothing left to keep lit). */
function DomainNode({
  domain,
  x,
  y,
  angleDeg,
  focusing = false,
  onSelect,
  onPointerEnter,
  onPointerLeave,
  onFocus,
  onBlur,
}: DomainNodeProps) {
  return (
    <li
      className={`domain-node${focusing ? " is-focusing" : ""}`}
      style={{ left: `${x}%`, top: `${y}%`, "--connector-angle": `${angleDeg + 180}deg` } as CSSProperties}
      onMouseEnter={() => onPointerEnter(domain.slug)}
      onMouseLeave={onPointerLeave}
    >
      <span className="domain-connector" aria-hidden="true" />
      <span className="node-ring node-ring-outer" aria-hidden="true" />
      <span className="node-ring node-ring-inner" aria-hidden="true" />
      <button
        type="button"
        className="domain-button"
        data-domain-transition-slug={domain.slug}
        onClick={() => onSelect(domain.slug)}
        onFocus={() => onFocus(domain.slug)}
        onBlur={onBlur}
        aria-label={`Open ${domain.name}: ${domain.description}`}
      >
        <span className="domain-kbd" aria-hidden="true">
          {domainNumber(domain.slug) ?? ""}
        </span>
        <DomainGlyph slug={domain.slug} className="domain-node-glyph" />
        <span className="domain-name">{domain.name}</span>
        <span className="domain-subtitle">{DOMAIN_SUBTITLES[domain.slug] ?? ""}</span>
      </button>
    </li>
  );
}

export default DomainNode;
