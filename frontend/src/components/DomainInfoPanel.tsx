import type { Domain } from "../api";

interface DomainInfoPanelProps {
  domain: Domain | null;
}

/** The full, truthful domain description — sourced directly from the API,
 * never fabricated — shown in a side panel instead of crowding the orbital
 * node itself. Renders nothing (rather than an empty shell) when no domain
 * is hovered/focused, so it never occupies layout space at rest. */
function DomainInfoPanel({ domain }: DomainInfoPanelProps) {
  if (!domain) return null;
  return (
    <aside className="domain-info-panel" aria-live="polite">
      <span className="domain-info-name">{domain.name}</span>
      <p className="domain-info-description">{domain.description}</p>
    </aside>
  );
}

export default DomainInfoPanel;
