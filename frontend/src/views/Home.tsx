import { useCallback, useEffect, useRef, useState } from "react";
import {
  abandonMission,
  acknowledgeBriefingItem,
  completeMission,
  createGeneralConversation,
  fetchCurrentMission,
  fetchDomains,
  fetchHomeBriefing,
  fetchMissionCandidates,
  MISSION_CONTROL_REFRESH_EVENT,
  pauseMission,
  restoreBriefingItem,
  resumeMission,
  sendTurn,
  snoozeBriefingItem,
  startMission,
  synthesizeSpeech,
  unpinMissionFocusPin,
  type BriefingItem,
  type BriefingSnoozeDuration,
  type Domain,
  type FocusSession,
  type HomeBriefing,
  type MissionCandidate,
  type MissionCandidates,
  type MissionFocusEntry,
} from "../api";
import { isNavigateTarget, type NavigateTarget } from "../commands/registry";
import type { DomainSlug } from "../domainOrder";
import BriefingStrip from "../components/BriefingStrip";
import DomainNode from "../components/DomainNode";
import DomainInfoPanel from "../components/DomainInfoPanel";
import JarvisCore, { type CoreState } from "../components/JarvisCore";
import MissionControlStrip from "../components/MissionControlStrip";
import MissionFocusRail from "../components/MissionFocusRail";
import ModelLinkBanner from "../components/diagnostic/ModelLinkBanner";
import type { HealthStatus } from "../App";

// How often Home re-polls the current mission while mounted — never the
// live-timer mechanism itself (MissionControlStrip's own ActiveMission
// re-derives elapsed/remaining every second from persisted timestamps),
// only how quickly a change made elsewhere (voice, command palette,
// another tab, an ordinary restart) is picked up here.
const MISSION_CONTROL_POLL_MS = 30_000;

interface HomeProps {
  onSelectDomain: (slug: string) => void;
  /** Opens the general Jarvis conversation — the core itself, not a
   * seventh domain (see App.tsx / GeneralConversation.tsx). */
  onOpenGeneral: () => void;
  /** The single generic navigation entry point App already exposes to the
   * command layer (App.tsx's navigateToTarget) — reused here so a
   * briefing item's `link_target` (a domain or a Centre) opens through
   * exactly the same code path a typed/spoken command would, never a
   * second navigation implementation. */
  onNavigate: (target: NavigateTarget) => void;
  health: HealthStatus;
  /** Set briefly by App when a typed/spoken command targets a domain while
   * Home is the visible screen — merged into the same `focusing` treatment
   * a manual click gets, so the node's activation ring is actually seen
   * before navigating rather than skipped straight past. */
  commandFocusSlug?: string | null;
  /** True only when the backend is reachable but Hermes/the model gateway
   * is not — a distinct, non-blocking degraded state, never conflated
   * with the backend itself being unavailable (see App.tsx's `health`). */
  modelDegraded?: boolean;
  onRetryModel?: () => void | Promise<void>;
  /** True whenever the fullscreen voice-capture overlay is showing over
   * Home (see App.tsx's VoiceCaptureOverlay). That overlay briefly accepts
   * pointer events itself while showing an error (see
   * VoiceCaptureOverlay.tsx's is-dismissible), which means a domain node
   * already being hovered never receives its own pointer-leave — without
   * this, its tooltip stayed stuck open underneath the overlay, as if
   * still hovered, until the pointer happened to cross it again. */
  voiceActive?: boolean;
}

const RADIUS_PERCENT = 38;
// Same idea for the core itself, tuned to the slightly longer route
// transition Phase 6 asks for when opening the general conversation.
const CORE_ACTIVATE_TRANSITION_MS = 260;
// A pointer must rest on a node for this long before its hover ring
// activates — long enough that a pointer sweeping quickly across several
// nodes on its way somewhere else never lights any of them up, short
// enough that a deliberate hover still feels immediate. Keyboard focus
// bypasses this entirely (see DomainNode's onFocus) since a keyboard user
// is never "passing through."
const HOVER_INTENT_MS = 100;
// Mirrors app/models_mission_focus.py's MISSION_FOCUS_DEFAULT_VISIBLE/
// MISSION_FOCUS_MAX_ACTIVE_PINS — display-only constants; the server is
// still the sole source of truth/enforcement for the actual 5-pin limit.
const MISSION_FOCUS_DEFAULT_VISIBLE = 3;
const MISSION_FOCUS_MAX_ACTIVE_PINS = 5;

function Home({
  onSelectDomain,
  onOpenGeneral,
  onNavigate,
  health,
  commandFocusSlug = null,
  modelDegraded = false,
  onRetryModel,
  voiceActive = false,
}: HomeProps) {
  // Guards the async continuations below (loadCurrentMission/
  // loadMissionCandidates/loadBriefing) against setting state after Home
  // has unmounted — e.g. selecting a domain while one of these requests is
  // still in flight. Must be set back to true on every effect setup, not
  // just read from useRef's initial value: Strict Mode's dev-only
  // mount->cleanup->remount cycle runs this cleanup once before the
  // component's real lifetime begins, and without the explicit reset here
  // that leaves the guard permanently false — silently dropping every
  // legitimate update for as long as Home stays mounted.
  const mountedRef = useRef(true);
  useEffect(() => {
    mountedRef.current = true;
    return () => {
      mountedRef.current = false;
    };
  }, []);

  const [domains, setDomains] = useState<Domain[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [focusingSlug, setFocusingSlug] = useState<string | null>(null);
  const [hoveredSlug, setHoveredSlug] = useState<string | null>(null);
  const [coreActivating, setCoreActivating] = useState(false);
  const [modelBannerDismissed, setModelBannerDismissed] = useState(false);
  const [retryingModel, setRetryingModel] = useState(false);
  const hoverIntentTimeoutRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const coreActivateTimeoutRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  // Phase 12A: the on-demand situational briefing — assembled entirely
  // locally/deterministically by the backend (no model call). Fetched once
  // on mount and again only on an explicit "Refresh" click; never
  // auto-polled, since nothing here needs to feel "live" the way voice
  // state does.
  const [briefing, setBriefing] = useState<HomeBriefing | null>(null);
  const [briefingLoading, setBriefingLoading] = useState(true);
  const [briefingError, setBriefingError] = useState<string | null>(null);
  const [discussing, setDiscussing] = useState(false);
  const [discussError, setDiscussError] = useState<string | null>(null);
  const [discussReply, setDiscussReply] = useState<string | null>(null);
  const [reading, setReading] = useState(false);
  // A single reusable <audio> element for "Read briefing aloud" — held in
  // state (not a ref) so its own unmount-cleanup effect below can depend on
  // it directly, rather than mutating a ref's `.current` outside an effect.
  const [readAudioEl, setReadAudioEl] = useState<HTMLAudioElement | null>(null);
  // Phase 12B: which item is currently mid-acknowledge/snooze/restore —
  // never a global loading flag, so unrelated rows stay interactive.
  const [briefingActionBusyKey, setBriefingActionBusyKey] = useState<string | null>(null);
  const [briefingActionError, setBriefingActionError] = useState<string | null>(null);

  // Phase 12C: Mission Focus — its data travels embedded in the same
  // HomeBriefing response (`briefing.mission_focus`), never a second
  // independent fetch/poll cycle.
  const [missionFocusBusyPinId, setMissionFocusBusyPinId] = useState<string | null>(null);
  const [missionFocusActionError, setMissionFocusActionError] = useState<string | null>(null);
  const [missionFocusDiscussing, setMissionFocusDiscussing] = useState(false);
  const [missionFocusDiscussError, setMissionFocusDiscussError] = useState<string | null>(null);
  const [missionFocusDiscussReply, setMissionFocusDiscussReply] = useState<string | null>(null);

  // Mission Control / Current Focus — a separate poll cycle from the
  // briefing above (never piggy-backed onto it), since a focus session's
  // lifecycle can change from voice, the command palette, or another tab
  // at any moment, independent of when the briefing itself was last
  // refreshed.
  const [missionCandidates, setMissionCandidates] = useState<MissionCandidates | null>(null);
  const [missionCandidatesLoading, setMissionCandidatesLoading] = useState(true);
  const [missionCandidatesError, setMissionCandidatesError] = useState<string | null>(null);
  const [currentMission, setCurrentMission] = useState<FocusSession | null>(null);
  const [currentMissionLoading, setCurrentMissionLoading] = useState(true);
  const [currentMissionError, setCurrentMissionError] = useState<string | null>(null);
  const [missionActionBusy, setMissionActionBusy] = useState(false);
  const [missionActionError, setMissionActionError] = useState<string | null>(null);

  const loadCurrentMission = useCallback(() => {
    setCurrentMissionError(null);
    return fetchCurrentMission()
      .then((data) => {
        if (!mountedRef.current) return data.session;
        setCurrentMission(data.session);
        setCurrentMissionLoading(false);
        return data.session;
      })
      .catch(() => {
        if (!mountedRef.current) return null;
        setCurrentMissionError("Could not load the current focus session.");
        setCurrentMissionLoading(false);
        return null;
      });
  }, []);

  const loadMissionCandidates = useCallback(() => {
    setMissionCandidatesLoading(true);
    setMissionCandidatesError(null);
    fetchMissionCandidates()
      .then((data) => {
        if (mountedRef.current) setMissionCandidates(data);
      })
      .catch(() => {
        if (mountedRef.current) setMissionCandidatesError("Could not load focus suggestions.");
      })
      .finally(() => {
        if (mountedRef.current) setMissionCandidatesLoading(false);
      });
  }, []);

  useEffect(() => {
    loadCurrentMission().then((session) => {
      if (!session) loadMissionCandidates();
    });
  }, [loadCurrentMission, loadMissionCandidates]);

  // Re-poll on a fixed interval, whenever the window regains focus, and
  // immediately on MISSION_CONTROL_REFRESH_EVENT (dispatched by App.tsx
  // right after a voice/command-palette focus_start/pause/resume/
  // complete/abandon action succeeds) — never the timer's own source of
  // truth (that's computeElapsedSeconds against the session's persisted
  // timestamps), only how quickly a change made elsewhere is noticed
  // here. Without the event listener, starting/ending a mission from the
  // command palette while already on Home would leave this strip showing
  // its stale prior state until the next poll or reload, even though the
  // change already happened server-side.
  useEffect(() => {
    function refresh() {
      loadCurrentMission().then((session) => {
        if (!session) loadMissionCandidates();
      });
    }
    const intervalId = window.setInterval(refresh, MISSION_CONTROL_POLL_MS);
    window.addEventListener("focus", refresh);
    window.addEventListener(MISSION_CONTROL_REFRESH_EVENT, refresh);
    return () => {
      window.clearInterval(intervalId);
      window.removeEventListener("focus", refresh);
      window.removeEventListener(MISSION_CONTROL_REFRESH_EVENT, refresh);
    };
  }, [loadCurrentMission, loadMissionCandidates]);

  async function handleStartMissionFromCandidate(candidate: MissionCandidate, minutes: number) {
    setMissionActionBusy(true);
    setMissionActionError(null);
    try {
      const session = await startMission({
        source_type: candidate.source_type as Parameters<typeof startMission>[0]["source_type"],
        source_id: candidate.source_ids[0] ?? null,
        target_duration_minutes: minutes,
      });
      setCurrentMission(session);
    } catch {
      setMissionActionError("Could not start this focus session.");
    } finally {
      setMissionActionBusy(false);
    }
  }

  async function handleStartManualMission(title: string, domainSlug: DomainSlug | null, minutes: number) {
    setMissionActionBusy(true);
    setMissionActionError(null);
    try {
      const session = await startMission({
        source_type: "manual",
        title,
        domain_slug: domainSlug,
        target_duration_minutes: minutes,
      });
      setCurrentMission(session);
    } catch {
      setMissionActionError("Could not start this focus session.");
    } finally {
      setMissionActionBusy(false);
    }
  }

  async function handlePauseMission() {
    if (!currentMission) return;
    setMissionActionBusy(true);
    setMissionActionError(null);
    try {
      setCurrentMission(await pauseMission(currentMission.id));
    } catch {
      setMissionActionError("Could not pause this focus session.");
    } finally {
      setMissionActionBusy(false);
    }
  }

  async function handleResumeMission() {
    if (!currentMission) return;
    setMissionActionBusy(true);
    setMissionActionError(null);
    try {
      setCurrentMission(await resumeMission(currentMission.id));
    } catch {
      setMissionActionError("Could not resume this focus session.");
    } finally {
      setMissionActionBusy(false);
    }
  }

  async function handleCompleteMission(completionNote: string | null, whatChangedNote: string | null) {
    if (!currentMission) return;
    setMissionActionBusy(true);
    setMissionActionError(null);
    try {
      await completeMission(currentMission.id, { completion_note: completionNote, what_changed_note: whatChangedNote });
      setCurrentMission(null);
      loadMissionCandidates();
    } catch {
      setMissionActionError("Could not complete this focus session.");
    } finally {
      setMissionActionBusy(false);
    }
  }

  async function handleAbandonMission() {
    if (!currentMission) return;
    setMissionActionBusy(true);
    setMissionActionError(null);
    try {
      await abandonMission(currentMission.id);
      setCurrentMission(null);
      loadMissionCandidates();
    } catch {
      setMissionActionError("Could not abandon this focus session.");
    } finally {
      setMissionActionBusy(false);
    }
  }

  useEffect(() => {
    return () => {
      readAudioEl?.pause();
    };
  }, [readAudioEl]);

  const loadBriefing = useCallback((trigger: "home_view" | "home_refresh" = "home_view") => {
    setBriefingLoading(true);
    setBriefingError(null);
    fetchHomeBriefing(trigger)
      .then((data) => {
        if (mountedRef.current) setBriefing(data);
      })
      .catch(() => {
        if (mountedRef.current) setBriefingError("Could not load the situational briefing.");
      })
      .finally(() => {
        if (mountedRef.current) setBriefingLoading(false);
      });
  }, []);

  const handleRefreshBriefing = useCallback(() => loadBriefing("home_refresh"), [loadBriefing]);

  useEffect(() => {
    let cancelled = false;

    fetchDomains()
      .then((data) => {
        if (!cancelled) setDomains(data);
      })
      .catch(() => {
        if (!cancelled) setError("Could not load domains from the backend.");
      });

    return () => {
      cancelled = true;
    };
  }, []);

  useEffect(() => {
    loadBriefing();
  }, [loadBriefing]);

  useEffect(() => {
    return () => {
      if (hoverIntentTimeoutRef.current) clearTimeout(hoverIntentTimeoutRef.current);
      if (coreActivateTimeoutRef.current) clearTimeout(coreActivateTimeoutRef.current);
    };
  }, []);

  useEffect(() => {
    if (voiceActive) {
      if (hoverIntentTimeoutRef.current) clearTimeout(hoverIntentTimeoutRef.current);
      setHoveredSlug(null);
    }
  }, [voiceActive]);

  function handleSelectBriefingItem(item: BriefingItem) {
    if (isNavigateTarget(item.link_target)) {
      onNavigate(item.link_target);
    }
    // An unrecognized/absent link_target never navigates anywhere — the
    // item stays visible, just not clickable-through.
  }

  async function handleDiscussBriefing() {
    if (!briefing || briefing.items.length === 0) return;
    setDiscussing(true);
    setDiscussError(null);
    setDiscussReply(null);
    try {
      const conversation = await createGeneralConversation("Situational briefing discussion");
      // Change labels and exact source references travel with the text —
      // still quoted reference data through the existing context
      // boundary (app/context_builder.py's REFERENCE DATA framing), never
      // treated as instructions.
      const text = briefing.items
        .map(
          (item) =>
            `[${item.category.toUpperCase()}/${item.change_state.toUpperCase()}] ${item.title}${item.subtitle ? ` — ${item.subtitle}` : ""} (source: ${item.source_type}:${item.source_ids.join(",")})`,
        )
        .join("\n");
      const result = await sendTurn(
        conversation.id,
        `Here is my current situational briefing, with each item's change status (NEW/CHANGED/ONGOING/RESOLVED/REOPENED). Can you help me think through it?\n\n${text}`,
        `briefing-discuss-${conversation.id}`,
        [],
      );
      setDiscussReply(result.assistant_message?.content ?? "(no reply)");
    } catch {
      setDiscussError("Could not send this briefing to Jarvis for discussion.");
    } finally {
      setDiscussing(false);
    }
  }

  async function handleAcknowledgeBriefingItem(stableKey: string) {
    setBriefingActionBusyKey(stableKey);
    setBriefingActionError(null);
    try {
      await acknowledgeBriefingItem(stableKey);
      loadBriefing();
    } catch {
      setBriefingActionError("Could not acknowledge this item.");
    } finally {
      setBriefingActionBusyKey(null);
    }
  }

  async function handleSnoozeBriefingItem(stableKey: string, duration: BriefingSnoozeDuration) {
    setBriefingActionBusyKey(stableKey);
    setBriefingActionError(null);
    try {
      await snoozeBriefingItem(stableKey, duration);
      loadBriefing();
    } catch {
      setBriefingActionError("Could not snooze this item.");
    } finally {
      setBriefingActionBusyKey(null);
    }
  }

  async function handleRestoreBriefingItem(stableKey: string) {
    setBriefingActionBusyKey(stableKey);
    setBriefingActionError(null);
    try {
      await restoreBriefingItem(stableKey);
      loadBriefing();
    } catch {
      setBriefingActionError("Could not restore this item.");
    } finally {
      setBriefingActionBusyKey(null);
    }
  }

  function handleViewMissionFocusSource(entry: MissionFocusEntry) {
    if (isNavigateTarget(entry.link_target)) {
      onNavigate(entry.link_target);
    }
    // An unrecognized/absent link_target (e.g. the source is no longer
    // available) never navigates anywhere.
  }

  async function handleRemoveFromMissionFocus(pinId: string) {
    setMissionFocusBusyPinId(pinId);
    setMissionFocusActionError(null);
    try {
      await unpinMissionFocusPin(pinId);
      loadBriefing();
    } catch {
      setMissionFocusActionError("Could not remove this pin.");
    } finally {
      setMissionFocusBusyPinId(null);
    }
  }

  async function handleDiscussMissionFocus() {
    const pins = briefing?.mission_focus ?? [];
    if (pins.length === 0) return;
    setMissionFocusDiscussing(true);
    setMissionFocusDiscussError(null);
    setMissionFocusDiscussReply(null);
    try {
      const conversation = await createGeneralConversation("Mission Focus discussion");
      const text = pins
        .map(
          (entry) =>
            `#${entry.rank} [${entry.domain_slug?.toUpperCase() ?? "GENERAL"}] ${entry.title} — next action: ${entry.next_action}` +
            (entry.blocker ? ` (blocked: ${entry.blocker})` : "") +
            (entry.target_at ? ` (target: ${entry.target_at})` : "") +
            (entry.resolved ? " [source already resolved]" : "") +
            (!entry.available ? " [source no longer available]" : ""),
        )
        .join("\n");
      const result = await sendTurn(
        conversation.id,
        `Here is my current Mission Focus — the small set of things I've deliberately chosen to prioritize. Can you help me think through it?\n\n${text}`,
        `mission-focus-discuss-${conversation.id}`,
        [],
      );
      setMissionFocusDiscussReply(result.assistant_message?.content ?? "(no reply)");
    } catch {
      setMissionFocusDiscussError("Could not send Mission Focus to Jarvis for discussion.");
    } finally {
      setMissionFocusDiscussing(false);
    }
  }

  async function handleReadBriefingAloud() {
    if (!briefing || briefing.items.length === 0 || reading) return;
    setReading(true);
    const audioEl = readAudioEl ?? new Audio();
    setReadAudioEl(audioEl);
    try {
      const text = briefing.items.map((item) => `${item.category}: ${item.title}.`).join(" ");
      const audioBlob = await synthesizeSpeech(text);
      const audioUrl = URL.createObjectURL(audioBlob);
      audioEl.src = audioUrl;
      audioEl.onended = () => {
        URL.revokeObjectURL(audioUrl);
        setReading(false);
      };
      await audioEl.play();
    } catch {
      setReading(false);
    }
  }

  function handleSelect(slug: string) {
    if (focusingSlug) return; // a transition is already underway
    // Immediate cyan/scale activation feedback (CSS-driven, see
    // `.domain-node.is-focusing`) and the shared View Transition both start
    // on this same synchronous call — never a `setTimeout` gap between
    // "the node reacts" and "navigation actually begins". `onSelectDomain`
    // (wired by App.tsx to `runDomainViewTransition`) owns morphing this
    // node into the destination header emblem; `focusingSlug` only drives
    // the brief local highlight and is discarded when Home unmounts.
    setFocusingSlug(slug);
    onSelectDomain(slug);
  }

  function handleActivateCore() {
    if (coreActivating) return;
    setCoreActivating(true);
    coreActivateTimeoutRef.current = setTimeout(onOpenGeneral, CORE_ACTIVATE_TRANSITION_MS);
  }

  useEffect(() => {
    if (!modelDegraded) setModelBannerDismissed(false);
  }, [modelDegraded]);

  async function handleRetryModel() {
    if (!onRetryModel || retryingModel) return;
    setRetryingModel(true);
    await onRetryModel();
    setRetryingModel(false);
  }

  // Pointer hover: gated behind HOVER_INTENT_MS so a pointer merely passing
  // over a node never activates it (see the constant's comment above).
  function handlePointerEnter(slug: string) {
    if (hoverIntentTimeoutRef.current) clearTimeout(hoverIntentTimeoutRef.current);
    hoverIntentTimeoutRef.current = setTimeout(() => setHoveredSlug(slug), HOVER_INTENT_MS);
  }

  function handlePointerLeave() {
    if (hoverIntentTimeoutRef.current) clearTimeout(hoverIntentTimeoutRef.current);
    setHoveredSlug(null);
  }

  // Keyboard focus is immediate — a keyboard user tabbing onto a node is
  // never "passing through" the way a moving pointer can be.
  function handleFocus(slug: string) {
    if (hoverIntentTimeoutRef.current) clearTimeout(hoverIntentTimeoutRef.current);
    setHoveredSlug(slug);
  }

  // The orbital core has no voice pipeline of its own yet (push-to-talk is
  // scoped to an active domain conversation — see DomainView). Its state
  // here reflects only the one real signal available at that level:
  // whether the backend is actually reachable. It must never be animated
  // to imply activity that isn't happening.
  const coreState: CoreState = health === "error" ? "error" : "idle";
  const hoveredDomain = domains.find((d) => d.slug === hoveredSlug) ?? null;

  return (
    <main className="home">
      <h1 className="sr-only">Jarvis</h1>

      {error && (
        <p className="error-banner" role="alert">
          {error}
        </p>
      )}

      {modelDegraded && !modelBannerDismissed && (
        <ModelLinkBanner
          onRetry={handleRetryModel}
          retrying={retryingModel}
          onDismiss={() => setModelBannerDismissed(true)}
        />
      )}

      <div className="core-layout">
        <div className="orbit-path" aria-hidden="true" />
        <JarvisCore
          state={coreState}
          onActivate={handleActivateCore}
          activating={coreActivating}
          focusActive={currentMission?.status === "active"}
        />

        <ul className="domain-ring">
          {domains.map((domain, index) => {
            const angle = (index / domains.length) * 2 * Math.PI - Math.PI / 2;
            const x = 50 + RADIUS_PERCENT * Math.cos(angle);
            const y = 50 + RADIUS_PERCENT * Math.sin(angle);
            const angleDeg = (angle * 180) / Math.PI;

            return (
              <DomainNode
                key={domain.id}
                domain={domain}
                x={x}
                y={y}
                angleDeg={angleDeg}
                focusing={focusingSlug === domain.slug || commandFocusSlug === domain.slug}
                onSelect={handleSelect}
                onPointerEnter={handlePointerEnter}
                onPointerLeave={handlePointerLeave}
                onFocus={handleFocus}
                onBlur={() => setHoveredSlug(null)}
              />
            );
          })}
        </ul>
      </div>

      <DomainInfoPanel domain={hoveredDomain} />

      <BriefingStrip
        briefing={briefing}
        loading={briefingLoading}
        error={briefingError}
        onSelectItem={handleSelectBriefingItem}
        onRefresh={handleRefreshBriefing}
        onDiscuss={handleDiscussBriefing}
        discussing={discussing}
        discussError={discussError}
        discussReply={discussReply}
        onReadAloud={handleReadBriefingAloud}
        reading={reading}
        onAcknowledge={handleAcknowledgeBriefingItem}
        onSnooze={handleSnoozeBriefingItem}
        onRestore={handleRestoreBriefingItem}
        busyKey={briefingActionBusyKey}
        actionError={briefingActionError}
      />

      <MissionControlStrip
        candidates={missionCandidates}
        candidatesLoading={missionCandidatesLoading}
        candidatesError={missionCandidatesError}
        currentMission={currentMission}
        currentMissionLoading={currentMissionLoading}
        currentMissionError={currentMissionError}
        onStartFromCandidate={handleStartMissionFromCandidate}
        onStartManual={handleStartManualMission}
        onPause={handlePauseMission}
        onResume={handleResumeMission}
        onComplete={handleCompleteMission}
        onAbandon={handleAbandonMission}
        busy={missionActionBusy}
        actionError={missionActionError}
      />

      <MissionFocusRail
        entries={briefing?.mission_focus ?? []}
        defaultVisible={MISSION_FOCUS_DEFAULT_VISIBLE}
        maxActivePins={MISSION_FOCUS_MAX_ACTIVE_PINS}
        loading={briefingLoading}
        error={missionFocusActionError}
        onViewSource={handleViewMissionFocusSource}
        onRemove={handleRemoveFromMissionFocus}
        onDiscuss={handleDiscussMissionFocus}
        discussing={missionFocusDiscussing}
        discussReply={missionFocusDiscussReply}
        discussError={missionFocusDiscussError}
        busyPinId={missionFocusBusyPinId}
      />
    </main>
  );
}

export default Home;
