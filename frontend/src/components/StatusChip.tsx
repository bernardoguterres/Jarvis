export type ChipTone = "ok" | "error" | "warn" | "active" | "neutral";

interface StatusChipProps {
  label: string;
  tone: ChipTone;
}

/** A consistent status-as-text+color chip. Always renders the literal
 * label as text (never color alone) — safe to use anywhere a plain status
 * string was previously rendered inline, since it doesn't change what
 * text is on the page, only how it's framed. */
function StatusChip({ label, tone }: StatusChipProps) {
  return <span className={`status-chip tone-${tone}`}>{label}</span>;
}

export default StatusChip;
