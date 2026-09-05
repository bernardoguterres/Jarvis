import { useEffect, useState } from "react";

/** True when the user has requested reduced motion. Used by the voice
 * waveform to drop decorative interpolation/pulsing/sweeping while still
 * reflecting real microphone levels (a waveform communicating live input
 * is information, not decoration — CSS's blanket animation-duration:0
 * rule can't distinguish that, so this hook exists specifically for the
 * places that need to keep responding to real data under reduced motion). */
export function useReducedMotion(): boolean {
  const [reduced, setReduced] = useState(
    () => typeof window !== "undefined" && window.matchMedia("(prefers-reduced-motion: reduce)").matches,
  );

  useEffect(() => {
    const mql = window.matchMedia("(prefers-reduced-motion: reduce)");
    const onChange = () => setReduced(mql.matches);
    mql.addEventListener("change", onChange);
    return () => mql.removeEventListener("change", onChange);
  }, []);

  return reduced;
}
