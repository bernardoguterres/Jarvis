import { useEffect, useLayoutEffect, useRef, useState } from "react";
import { createPortal } from "react-dom";

export interface SystemsMenuItem {
  id: string;
  label: string;
  onSelect: () => void;
}

interface SystemsMenuProps {
  items: SystemsMenuItem[];
}

/** A single "Systems" control that opens a compact menu of the six
 * management centres, replacing six equally-weighted pill buttons in the
 * top bar. Every destination/route this previously exposed is still
 * reachable — nothing lost, just no longer six identical rectangles.
 *
 * The panel is rendered through a portal into document.body rather than
 * as a normal absolutely-positioned child of the trigger: the top bar
 * needs `overflow-x: auto` for its own narrow-width horizontal scroll
 * (see .top-bar in index.css), which — per the same CSS quirk that once
 * broke page-level scrolling (see docs/DECISIONS.md D72) — silently gives
 * it `overflow-y: auto` too, clipping any ordinary absolutely-positioned
 * dropdown to the bar's own ~52px height. Portaling out from under that
 * ancestor is the general, correct fix for a dropdown in a scrollable
 * container, not just a one-off patch for this one menu. */
function SystemsMenu({ items }: SystemsMenuProps) {
  const [open, setOpen] = useState(false);
  const [panelPos, setPanelPos] = useState<{ top: number; right: number } | null>(null);
  const rootRef = useRef<HTMLDivElement | null>(null);
  const triggerRef = useRef<HTMLButtonElement | null>(null);
  const panelRef = useRef<HTMLDivElement | null>(null);

  useLayoutEffect(() => {
    if (!open || !triggerRef.current) return;
    const rect = triggerRef.current.getBoundingClientRect();
    setPanelPos({ top: rect.bottom + 8, right: window.innerWidth - rect.right });
  }, [open]);

  useEffect(() => {
    if (!open) return;

    function onPointerDown(event: PointerEvent) {
      const target = event.target as Node;
      if (rootRef.current?.contains(target)) return;
      if (panelRef.current?.contains(target)) return;
      setOpen(false);
    }
    function onKeyDown(event: KeyboardEvent) {
      if (event.key === "Escape") {
        event.stopPropagation();
        setOpen(false);
        triggerRef.current?.focus();
      }
    }
    function onReposition() {
      if (!triggerRef.current) return;
      const rect = triggerRef.current.getBoundingClientRect();
      setPanelPos({ top: rect.bottom + 8, right: window.innerWidth - rect.right });
    }

    document.addEventListener("pointerdown", onPointerDown);
    document.addEventListener("keydown", onKeyDown);
    window.addEventListener("resize", onReposition);
    window.addEventListener("scroll", onReposition, true);
    return () => {
      document.removeEventListener("pointerdown", onPointerDown);
      document.removeEventListener("keydown", onKeyDown);
      window.removeEventListener("resize", onReposition);
      window.removeEventListener("scroll", onReposition, true);
    };
  }, [open]);

  return (
    <div className="systems-menu" ref={rootRef}>
      <button
        type="button"
        ref={triggerRef}
        className="systems-menu-trigger"
        aria-haspopup="true"
        aria-expanded={open}
        onClick={() => setOpen((prev) => !prev)}
      >
        <span className="systems-menu-icon" aria-hidden="true" />
        Systems
      </button>
      {open &&
        panelPos &&
        createPortal(
          <div
            ref={panelRef}
            className="systems-menu-panel"
            role="menu"
            aria-label="Systems"
            style={{ position: "fixed", top: panelPos.top, right: panelPos.right }}
          >
            {items.map((item) => (
              <button
                key={item.id}
                type="button"
                role="menuitem"
                className="systems-menu-item"
                onClick={() => {
                  setOpen(false);
                  item.onSelect();
                }}
              >
                {item.label}
              </button>
            ))}
          </div>,
          document.body,
        )}
    </div>
  );
}

export default SystemsMenu;
