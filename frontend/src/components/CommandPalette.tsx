import { useEffect, useMemo, useRef, useState } from "react";

export interface PaletteAction {
  id: string;
  label: string;
  run: () => void;
}

interface CommandPaletteProps {
  actions: PaletteAction[];
  onClose: () => void;
  /** Shared deterministic command parser (commands/registry.ts) — resolves
   * a raw typed query into an executable action when it names a command
   * (including its aliases, e.g. "health area") that isn't already covered
   * by the static `actions` list below. Optional so this component stays
   * usable/testable without the full command layer wired in. */
  resolveCommand?: (text: string) => PaletteAction | null;
}

/** Command palette (Cmd+K) — a filtered static action list, plus the same
 * deterministic command parser DomainView's voice transcript handling
 * uses, so aliases and system commands work identically whether typed or
 * spoken. */
function CommandPalette({ actions, onClose, resolveCommand }: CommandPaletteProps) {
  const [query, setQuery] = useState("");
  const [highlighted, setHighlighted] = useState(0);
  const inputRef = useRef<HTMLInputElement | null>(null);

  useEffect(() => {
    inputRef.current?.focus();
  }, []);

  const filtered = useMemo(() => {
    const q = query.trim().toLowerCase();
    if (!q) return actions;
    const staticMatches = actions.filter((action) => action.label.toLowerCase().includes(q));
    const resolved = resolveCommand?.(query);
    if (resolved && !staticMatches.some((a) => a.id === resolved.id || a.label === resolved.label)) {
      return [resolved, ...staticMatches];
    }
    return staticMatches;
  }, [query, actions, resolveCommand]);

  useEffect(() => {
    setHighlighted(0);
  }, [query]);

  function runHighlighted() {
    const action = filtered[highlighted];
    if (action) {
      action.run();
      onClose();
    }
  }

  return (
    <div className="command-palette-overlay" role="presentation" onClick={onClose}>
      <div
        className="command-palette"
        role="dialog"
        aria-label="Command palette"
        onClick={(event) => event.stopPropagation()}
      >
        <input
          ref={inputRef}
          type="text"
          placeholder="Type a command…"
          value={query}
          onChange={(event) => setQuery(event.target.value)}
          onKeyDown={(event) => {
            if (event.key === "ArrowDown") {
              event.preventDefault();
              setHighlighted((prev) => Math.min(prev + 1, filtered.length - 1));
            } else if (event.key === "ArrowUp") {
              event.preventDefault();
              setHighlighted((prev) => Math.max(prev - 1, 0));
            } else if (event.key === "Enter") {
              event.preventDefault();
              runHighlighted();
            } else if (event.key === "Escape") {
              event.preventDefault();
              onClose();
            }
          }}
        />
        <ul className="command-palette-list">
          {filtered.map((action, index) => (
            <li key={action.id}>
              <button
                type="button"
                className={index === highlighted ? "highlighted" : ""}
                onMouseEnter={() => setHighlighted(index)}
                onClick={() => {
                  action.run();
                  onClose();
                }}
              >
                {action.label}
              </button>
            </li>
          ))}
          {filtered.length === 0 && <li className="command-palette-empty">No matching commands.</li>}
        </ul>
      </div>
    </div>
  );
}

export default CommandPalette;
