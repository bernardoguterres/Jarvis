import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import {
  fetchAgentStatus,
  fetchHealth,
  fetchDomains,
  fetchGeneralConversations,
  createGeneralConversation,
  sendTurn,
  syncGoogleCalendar,
  syncGoogleHealth,
  runRoutineNow,
  disconnectIntegration,
  createExport,
  fetchMissionCandidates,
  fetchCurrentMission,
  startMission,
  pauseMission,
  resumeMission,
  completeMission,
  abandonMission,
  fetchMissionHistory,
  MISSION_CONTROL_REFRESH_EVENT,
  type AgentStatus,
  type Domain,
  type Message,
} from "./api";
import Home from "./views/Home";
import DomainView from "./views/DomainView";
import GeneralConversation from "./views/GeneralConversation";
import DataManagement from "./views/DataManagement";
import MemoryCentre from "./views/MemoryCentre";
import ActionsCentre from "./views/ActionsCentre";
import SkillsCentre from "./views/SkillsCentre";
import IntegrationsCentre from "./views/IntegrationsCentre";
import RoutineCentre from "./views/RoutineCentre";
import RecallCentre from "./views/RecallCentre";
import ResearchCentre from "./views/ResearchCentre";
import DecisionCentre from "./views/DecisionCentre";
import CommandPalette, { type PaletteAction } from "./components/CommandPalette";
import SystemsMenu, { type SystemsMenuItem } from "./components/SystemsMenu";
import NotFoundDiagnostic from "./components/diagnostic/NotFoundDiagnostic";
import ControllerOfflineDiagnostic from "./components/diagnostic/ControllerOfflineDiagnostic";
import ConfirmDialog from "./components/ConfirmDialog";
import VoiceCaptureOverlay from "./components/voice/VoiceCaptureOverlay";
import { useVoiceCapture } from "./hooks/useVoiceCapture";
import { runDomainViewTransition } from "./transitions/domainViewTransition";
import { domainSlugForNumber } from "./domainOrder";
import {
  parseCommand,
  type CentreTarget,
  type NavigateTarget,
  type ParsedCommand,
  type SafeAction,
} from "./commands/registry";
import { requestHighlight } from "./commands/highlight";

// A single, real, persistent general conversation reused for every voice
// question asked from Home or a Centre page (no conversation is "selected"
// there the way GeneralConversation.tsx lets you pick one) — it appears in
// GeneralConversation's own conversation list like any other, is
// global-profile-only, and never auto-includes a domain (see
// docs/DECISIONS.md D79).
const AMBIENT_CONVERSATION_TITLE = "Quick questions (voice)";

// This app has exactly one real frontend route ("/"). Every other path
// reaching the client means the backend's SPA fallback (app/main.py)
// served index.html for something this interface doesn't recognize —
// see NotFoundDiagnostic.tsx. A `?open=` query param on the root path is
// a deep link (e.g. from the OAuth callback page's "Return to
// Integrations Centre" link), not an unknown route.
const KNOWN_PATHS = new Set(["/", "/index.html"]);

const DEEP_LINK_CENTRES: Record<string, CentreTarget> = {
  memory: "memory_centre",
  actions: "actions_centre",
  skills: "skills_centre",
  integrations: "integrations_centre",
  routines: "routine_centre",
  data: "data_management",
  research: "research_centre",
  decisions: "decision_centre",
};

export type HealthStatus = "checking" | "ok" | "error";

// Dev-only diagnostic fault injection (`?diag=offline|degraded|crash`),
// active only when `import.meta.env.DEV` — never compiled into a
// production build. Lets every diagnostic state be inspected safely from
// the running preview without stopping the real backend, disconnecting a
// real integration, or making a real model call. See the Phase 6
// diagnostic-system pass in docs/DECISIONS.md.
const DIAG_QA_PARAM = import.meta.env.DEV ? new URLSearchParams(window.location.search).get("diag") : null;

const FAKE_DEGRADED_AGENT_STATUS: AgentStatus = {
  hermes_available: false,
  model_configured: false,
  model: null,
  provider: "hermes",
};

function isTypingTarget(target: EventTarget | null): boolean {
  const el = target as HTMLElement | null;
  if (!el) return false;
  const tag = el.tagName;
  return tag === "INPUT" || tag === "TEXTAREA" || tag === "SELECT" || el.isContentEditable;
}

function App() {
  const [selectedSlug, setSelectedSlug] = useState<string | null>(null);
  // The general Jarvis conversation opened from the core itself — a scope,
  // not a seventh domain (see GeneralConversation.tsx / docs/DECISIONS.md).
  const [showGeneral, setShowGeneral] = useState(false);
  const [showDataManagement, setShowDataManagement] = useState(false);
  const [showMemoryCentre, setShowMemoryCentre] = useState(false);
  const [showActionsCentre, setShowActionsCentre] = useState(false);
  const [showSkillsCentre, setShowSkillsCentre] = useState(false);
  const [showIntegrationsCentre, setShowIntegrationsCentre] = useState(false);
  const [showRoutineCentre, setShowRoutineCentre] = useState(false);
  const [showRecallCentre, setShowRecallCentre] = useState(false);
  const [showResearchCentre, setShowResearchCentre] = useState(false);
  const [showDecisionCentre, setShowDecisionCentre] = useState(false);
  // Set only by a voice/palette `open_recall` command (App.tsx's
  // `executeSafeAction`) so Recall Centre opens pre-seeded with that
  // query/domain — `token` changes on every command so RecallCentre's own
  // effect re-applies it even if the same query is searched twice in a
  // row, and it's `null` for every other way of opening Recall (Systems
  // menu, palette's static action, the keyboard shortcut), which starts
  // Recall with its own ordinary empty-query defaults instead.
  const [recallSeed, setRecallSeed] = useState<{ query: string; domainHint: string | null; token: number } | null>(null);
  const [showPalette, setShowPalette] = useState(false);
  const [domains, setDomains] = useState<Domain[]>([]);
  const [health, setHealth] = useState<HealthStatus>("checking");
  const [agentStatus, setAgentStatus] = useState<AgentStatus | null>(null);
  const [diagForceOffline, setDiagForceOffline] = useState(DIAG_QA_PARAM === "offline");
  const [diagForceDegraded, setDiagForceDegraded] = useState(DIAG_QA_PARAM === "degraded");
  const topBarRef = useRef<HTMLDivElement | null>(null);
  const [topBarScrollable, setTopBarScrollable] = useState(false);
  const [commandFocusSlug, setCommandFocusSlug] = useState<string | null>(null);
  const [isKnownRoute, setIsKnownRoute] = useState(() => KNOWN_PATHS.has(window.location.pathname));

  // A real, visible confirm dialog for a `confirm_required` command
  // (CLAUDE.md §12's "Confirm" tier) — set by runParsedCommand, never
  // executed until a person explicitly accepts it here.
  const [pendingConfirm, setPendingConfirm] = useState<Extract<ParsedCommand, { kind: "confirm_required" }> | null>(null);
  const [confirmBusy, setConfirmBusy] = useState(false);

  // A brief, truthful status line for a command's real outcome (a safe
  // action's result, a confirmed action's result, or an ambient voice
  // question's answer) — never decorative, always the actual result of a
  // real request. See §9's "no fake activity" rule.
  const [commandFeedback, setCommandFeedback] = useState<{ text: string; tone: "ok" | "error" } | null>(null);
  const commandFeedbackTimeoutRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const showCommandFeedback = useCallback((text: string, tone: "ok" | "error") => {
    setCommandFeedback({ text, tone });
    if (commandFeedbackTimeoutRef.current) clearTimeout(commandFeedbackTimeoutRef.current);
    commandFeedbackTimeoutRef.current = setTimeout(() => setCommandFeedback(null), 6000);
  }, []);

  // The ambient general conversation used for voice questions asked from
  // Home or a Centre page — created (or reused) lazily on first use, never
  // eagerly, so opening Jarvis doesn't silently create a conversation
  // nobody asked for.
  const [ambientConversationId, setAmbientConversationId] = useState<string | null>(null);
  const ambientConversationPromiseRef = useRef<Promise<string> | null>(null);

  useEffect(() => {
    return () => {
      if (commandFeedbackTimeoutRef.current) clearTimeout(commandFeedbackTimeoutRef.current);
    };
  }, []);

  const goHome = useCallback(() => {
    setSelectedSlug(null);
    setShowGeneral(false);
    setShowDataManagement(false);
    setShowMemoryCentre(false);
    setShowActionsCentre(false);
    setShowSkillsCentre(false);
    setShowIntegrationsCentre(false);
    setShowRoutineCentre(false);
    setShowRecallCentre(false);
    setShowResearchCentre(false);
    setShowDecisionCentre(false);
    setCommandFocusSlug(null);
  }, []);

  useEffect(() => {
    fetchDomains()
      .then(setDomains)
      .catch(() => {
        /* Home already surfaces a load error; the shortcut/palette lists
         * just stay empty until domains are reachable. */
      });
  }, []);

  const checkHealth = useCallback(async (): Promise<boolean> => {
    try {
      await fetchHealth();
      setHealth("ok");
      return true;
    } catch {
      setHealth("error");
      return false;
    }
  }, []);

  const checkAgentStatus = useCallback(async () => {
    try {
      const status = await fetchAgentStatus();
      setAgentStatus(status);
    } catch {
      setAgentStatus(null);
    }
  }, []);

  useEffect(() => {
    checkHealth();
  }, [checkHealth]);

  // While the controller is unavailable, ControllerOfflineDiagnostic owns
  // retry scheduling (bounded 5/10/20/30s) — this recurring check pauses
  // itself rather than racing it, so the backend is never polled by two
  // independent loops at once.
  useEffect(() => {
    if (health === "error") return;
    const interval = setInterval(checkHealth, 10_000);
    return () => clearInterval(interval);
  }, [health, checkHealth]);

  const handleControllerRecovered = useCallback(() => {
    setDiagForceOffline(false);
    fetchDomains()
      .then(setDomains)
      .catch(() => {});
    checkAgentStatus();
  }, [checkAgentStatus]);

  const handleRetryModel = useCallback(async () => {
    await checkAgentStatus();
    setDiagForceDegraded(false);
  }, [checkAgentStatus]);

  // Deliberately unconditional (not a one-shot flag): React may attempt
  // this render more than once internally before an ErrorBoundary commits
  // the failure, and a mutable "already crashed" guard would let the
  // second internal attempt render clean, silently swallowing the
  // simulated fault. "Try again" only truly escapes this by navigating
  // away (Return to Jarvis / Reload), which drops the `?diag=crash` param
  // — an accurate simulation of "a still-present bug isn't fixed by
  // simply re-rendering."
  if (DIAG_QA_PARAM === "crash") {
    throw new Error("Diagnostics QA: simulated interface fault (?diag=crash)");
  }

  // A deep link into a specific centre (e.g. from the OAuth callback
  // page's "Return to Integrations Centre" link, `/?open=integrations`) —
  // consumed once on mount and then stripped from the URL so a refresh
  // doesn't repeat it.
  useEffect(() => {
    if (!isKnownRoute) return;
    const params = new URLSearchParams(window.location.search);
    const open = params.get("open");
    if (!open) return;
    window.history.replaceState(null, "", window.location.pathname);
    const centreTarget = DEEP_LINK_CENTRES[open];
    if (centreTarget) {
      const setters: Record<CentreTarget, (v: boolean) => void> = {
        memory_centre: setShowMemoryCentre,
        actions_centre: setShowActionsCentre,
        skills_centre: setShowSkillsCentre,
        integrations_centre: setShowIntegrationsCentre,
        routine_centre: setShowRoutineCentre,
        data_management: setShowDataManagement,
        recall_centre: setShowRecallCentre,
        research_centre: setShowResearchCentre,
        decision_centre: setShowDecisionCentre,
      };
      setters[centreTarget](true);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [isKnownRoute]);

  useEffect(() => {
    checkAgentStatus();
    const interval = setInterval(checkAgentStatus, 15_000);
    return () => clearInterval(interval);
  }, [checkAgentStatus]);

  useEffect(() => {
    const el = topBarRef.current;
    if (!el) return;
    const update = () => setTopBarScrollable(el.scrollWidth > el.clientWidth + 1);
    update();
    if (typeof ResizeObserver === "undefined") return; // not available in the test environment
    const observer = new ResizeObserver(update);
    observer.observe(el);
    return () => observer.disconnect();
  });

  const closeAllOverlays = useCallback(() => {
    setShowGeneral(false);
    setShowDataManagement(false);
    setShowMemoryCentre(false);
    setShowActionsCentre(false);
    setShowSkillsCentre(false);
    setShowIntegrationsCentre(false);
    setShowRoutineCentre(false);
    setShowRecallCentre(false);
    setShowResearchCentre(false);
    setShowDecisionCentre(false);
  }, []);

  // The one shared entry point for every Home→domain navigation path
  // (pointer click, keyboard activation, number shortcuts, and a typed/
  // spoken command that names a domain) — each just calls this instead of
  // setting `selectedSlug` directly, so they all get the same real browser
  // View Transition (a continuous morph when Home's node for `slug` is on
  // screen, or a plain crossfade when it isn't — e.g. from a Centre page)
  // rather than each path growing its own bespoke delay/animation.
  const selectDomainWithTransition = useCallback((slug: string) => {
    runDomainViewTransition(slug, () => {
      closeAllOverlays();
      setSelectedSlug(slug);
    });
  }, [closeAllOverlays]);

  // The mirror of the above for DomainView's own "Back to Jarvis" — reuses
  // the exact same shared-element mechanism in reverse, so leaving a
  // domain morphs its header emblem back into its orbital position instead
  // of an instant cut. Other ways of returning home (Escape from a Centre,
  // the 404/offline diagnostics recovering, etc.) intentionally keep their
  // existing plain `goHome()` — this is specifically the domain↔Home path.
  const goHomeFromDomainWithTransition = useCallback(() => {
    if (selectedSlug === null) {
      goHome();
      return;
    }
    setCommandFocusSlug(null);
    runDomainViewTransition(selectedSlug, () => setSelectedSlug(null));
  }, [selectedSlug, goHome]);

  const navigateToTarget = useCallback(
    (target: NavigateTarget) => {
      if (target === "home") {
        goHome();
        return;
      }
      if (target === "back") {
        goHome();
        return;
      }
      if (target === "command_palette") {
        setShowPalette(true);
        return;
      }
      if (target === "general") {
        closeAllOverlays();
        setSelectedSlug(null);
        setShowGeneral(true);
        return;
      }
      if (target.startsWith("domain:")) {
        const slug = target.slice("domain:".length);
        const onHomeNow =
          !showDataManagement &&
          !showMemoryCentre &&
          !showActionsCentre &&
          !showSkillsCentre &&
          !showIntegrationsCentre &&
          !showRoutineCentre &&
          !showRecallCentre &&
          !showResearchCentre &&
          !showDecisionCentre &&
          !showGeneral &&
          selectedSlug === null;
        if (onHomeNow) {
          // A command targeting a domain while Home is actually visible
          // gets the same brief cyan activation highlight a manual click
          // gets, so the node's ring is genuinely seen — but, like a click,
          // it no longer gates navigation behind a fixed wait: the
          // highlight and the shared View Transition both start on this
          // same synchronous call.
          setCommandFocusSlug(slug);
        }
        selectDomainWithTransition(slug);
        return;
      }
      closeAllOverlays();
      setSelectedSlug(null);
      const setters: Record<CentreTarget, (v: boolean) => void> = {
        memory_centre: setShowMemoryCentre,
        actions_centre: setShowActionsCentre,
        skills_centre: setShowSkillsCentre,
        integrations_centre: setShowIntegrationsCentre,
        routine_centre: setShowRoutineCentre,
        data_management: setShowDataManagement,
        recall_centre: setShowRecallCentre,
        research_centre: setShowResearchCentre,
        decision_centre: setShowDecisionCentre,
      };
      setters[target as CentreTarget]?.(true);
    },
    [
      goHome,
      closeAllOverlays,
      showDataManagement,
      showMemoryCentre,
      showActionsCentre,
      showSkillsCentre,
      showIntegrationsCentre,
      showRoutineCentre,
      showRecallCentre,
      showResearchCentre,
      showDecisionCentre,
      showGeneral,
      selectedSlug,
      selectDomainWithTransition,
    ],
  );

  // Safe direct actions (CLAUDE.md §12 "Read" tier) — read-only or
  // trivially reversible, so the registry already identified exactly which
  // one; this just calls the real API and reports the real result. Never
  // guesses, never retries silently, never fabricates success.
  const executeSafeAction = useCallback(
    async (action: SafeAction) => {
      try {
        if (action.kind === "sync_provider") {
          await (action.provider === "google_calendar" ? syncGoogleCalendar() : syncGoogleHealth());
          showCommandFeedback(`Synced ${action.providerLabel}.`, "ok");
        } else if (action.kind === "retry_connection") {
          const ok = await checkHealth();
          showCommandFeedback(ok ? "Connection restored." : "Still unable to reach the controller.", ok ? "ok" : "error");
        } else if (action.kind === "run_routine") {
          await runRoutineNow(action.routineType);
          showCommandFeedback(`Ran ${action.routineLabel}.`, "ok");
        } else if (action.kind === "focus_start") {
          // No specific source is named by a bare voice/typed command
          // ("start a focus session") — reuse Home's own deterministic
          // candidate assembler (never a second ranking engine) so this
          // starts the same thing Home's Mission Control strip would
          // currently recommend; falls back to a manual, untitled-source
          // session only when there is genuinely no candidate, mirroring
          // the backend's own "no suitable candidates -> free-text entry"
          // rule.
          const minutes = action.durationMinutes ?? 25;
          const candidates = await fetchMissionCandidates();
          const session = candidates.recommended
            ? await startMission({
                source_type: candidates.recommended.source_type as Parameters<typeof startMission>[0]["source_type"],
                source_id: candidates.recommended.source_ids[0] ?? null,
                target_duration_minutes: minutes,
              })
            : await startMission({ source_type: "manual", title: "Focus session", target_duration_minutes: minutes });
          showCommandFeedback(`Started focus: ${session.title} (${minutes} min).`, "ok");
          window.dispatchEvent(new Event(MISSION_CONTROL_REFRESH_EVENT));
        } else if (action.kind === "focus_pause") {
          const current = await fetchCurrentMission();
          if (!current.session) {
            showCommandFeedback("No focus session is currently active.", "error");
          } else {
            await pauseMission(current.session.id);
            showCommandFeedback("Focus session paused.", "ok");
            window.dispatchEvent(new Event(MISSION_CONTROL_REFRESH_EVENT));
          }
        } else if (action.kind === "focus_resume") {
          const current = await fetchCurrentMission();
          if (!current.session) {
            showCommandFeedback("No focus session to resume.", "error");
          } else {
            await resumeMission(current.session.id);
            showCommandFeedback("Focus session resumed.", "ok");
            window.dispatchEvent(new Event(MISSION_CONTROL_REFRESH_EVENT));
          }
        } else if (action.kind === "focus_complete") {
          const current = await fetchCurrentMission();
          if (!current.session) {
            showCommandFeedback("No focus session is currently active.", "error");
          } else {
            await completeMission(current.session.id);
            showCommandFeedback(`Completed: ${current.session.title}.`, "ok");
            window.dispatchEvent(new Event(MISSION_CONTROL_REFRESH_EVENT));
          }
        } else if (action.kind === "focus_abandon") {
          const current = await fetchCurrentMission();
          if (!current.session) {
            showCommandFeedback("No focus session is currently active.", "error");
          } else {
            await abandonMission(current.session.id);
            showCommandFeedback(`Abandoned: ${current.session.title}.`, "ok");
            window.dispatchEvent(new Event(MISSION_CONTROL_REFRESH_EVENT));
          }
        } else if (action.kind === "focus_show_current") {
          const current = await fetchCurrentMission();
          showCommandFeedback(
            current.session ? `Current mission: ${current.session.title} (${current.session.status}).` : "No focus session is currently active.",
            "ok",
          );
        } else if (action.kind === "focus_show_history") {
          const history = await fetchMissionHistory(5);
          showCommandFeedback(
            history.length > 0
              ? `Recent sessions: ${history.map((s) => s.title).join(", ")}.`
              : "No completed focus sessions yet.",
            "ok",
          );
        } else if (action.kind === "open_recall") {
          // Purely local navigation — Recall Centre itself performs the
          // real search once mounted with this seed; nothing here ever
          // calls the backend directly.
          closeAllOverlays();
          setSelectedSlug(null);
          setRecallSeed({ query: action.query, domainHint: action.domainHint, token: Date.now() });
          setShowRecallCentre(true);
          showCommandFeedback(`Searching for "${action.query}"…`, "ok");
        }
      } catch {
        showCommandFeedback("That action could not be completed.", "error");
      }
    },
    [checkHealth, showCommandFeedback, closeAllOverlays],
  );

  // Confirmation-required actions (CLAUDE.md §12 "Confirm" tier) only ever
  // reach here — the real disconnect/export call happens only once a
  // person explicitly accepts the ConfirmDialog rendered below.
  const handleConfirmAction = useCallback(async () => {
    if (!pendingConfirm) return;
    const action = pendingConfirm.action;
    setConfirmBusy(true);
    try {
      if (action.kind === "disconnect_integration") {
        await disconnectIntegration(action.provider);
        showCommandFeedback(`Disconnected ${action.providerLabel}.`, "ok");
      } else if (action.kind === "export_data") {
        await createExport();
        showCommandFeedback("Export created.", "ok");
      }
    } catch {
      showCommandFeedback("That action could not be completed.", "error");
    } finally {
      setConfirmBusy(false);
      setPendingConfirm(null);
    }
  }, [pendingConfirm, showCommandFeedback]);

  // The single execution path shared by the Command Palette (typed input)
  // and every surface's voice transcript handling (spoken input, via
  // useVoiceCapture) — see commands/registry.ts. Parsing is deterministic
  // and identical everywhere; this is just where the resulting
  // target/action gets wired to App's real state, since only App owns
  // navigation, the confirm dialog, and the real API calls. A safe_action
  // executes immediately; a confirm_required action never executes here —
  // it only opens the confirm dialog, which calls the real action itself.
  const runParsedCommand = useCallback(
    (parsed: ParsedCommand): void => {
      if (parsed.kind === "navigate") {
        navigateToTarget(parsed.target);
      } else if (parsed.kind === "focus_control") {
        navigateToTarget(parsed.control.navigateTo);
        requestHighlight(parsed.control.controlId);
      } else if (parsed.kind === "safe_action") {
        executeSafeAction(parsed.action);
      } else if (parsed.kind === "confirm_required") {
        setPendingConfirm(parsed);
      }
      // "blocked" and "none" never navigate, execute, or confirm anything —
      // the caller (CommandPalette / a conversation surface) is responsible
      // for displaying the heard/interpreted/explanation text to the user.
    },
    [navigateToTarget, executeSafeAction],
  );

  // Lazily creates (once) or reuses the single ambient general conversation
  // behind Home/Centre voice questions — see AMBIENT_CONVERSATION_TITLE.
  const ensureAmbientConversation = useCallback(async (): Promise<string> => {
    if (ambientConversationId) return ambientConversationId;
    if (!ambientConversationPromiseRef.current) {
      ambientConversationPromiseRef.current = (async () => {
        const existing = await fetchGeneralConversations();
        const found = existing.find((c) => c.title === AMBIENT_CONVERSATION_TITLE);
        const conversation = found ?? (await createGeneralConversation(AMBIENT_CONVERSATION_TITLE));
        setAmbientConversationId(conversation.id);
        return conversation.id;
      })();
    }
    return ambientConversationPromiseRef.current;
  }, [ambientConversationId]);

  // An ordinary question asked by voice from Home or a Centre page — the
  // exact same sendTurn mechanism GeneralConversation.tsx uses, with an
  // explicitly empty domain array so a general turn never mixes in a
  // domain automatically, from any surface.
  const ambientSubmitTurn = useCallback(
    async (transcript: string): Promise<{ ok: boolean; assistantMessage: Message | null }> => {
      try {
        const conversationId = await ensureAmbientConversation();
        const idempotencyKey =
          typeof crypto.randomUUID === "function" ? crypto.randomUUID() : `${Date.now()}-${Math.random()}`;
        const result = await sendTurn(conversationId, transcript, idempotencyKey, []);
        if (result.status === "succeeded" && result.assistant_message) {
          showCommandFeedback(result.assistant_message.content, "ok");
          return { ok: true, assistantMessage: result.assistant_message };
        }
        showCommandFeedback(result.error ? `Jarvis could not respond: ${result.error.summary}` : "Jarvis could not respond.", "error");
        return { ok: false, assistantMessage: null };
      } catch {
        showCommandFeedback("Could not reach Jarvis. Your question was not sent.", "error");
        return { ok: false, assistantMessage: null };
      }
    },
    [ensureAmbientConversation, showCommandFeedback],
  );

  // The one shared voice state machine (useVoiceCapture) for every surface
  // that doesn't already own its own instance (DomainView and
  // GeneralConversation each instantiate their own) — Home and every
  // Centre page. Only ever started while `ambientVoiceEligible` (below) is
  // true, so there is never more than one active microphone session.
  const ambientVoice = useVoiceCapture({
    onSystemCommand: runParsedCommand,
    submitTurn: ambientSubmitTurn,
  });

  const resolveCommand = useCallback(
    (text: string): PaletteAction | null => {
      const parsed = parseCommand(text);
      if (parsed.kind === "navigate") {
        return { id: `cmd-nav-${parsed.target}`, label: parsed.interpreted, run: () => runParsedCommand(parsed) };
      }
      if (parsed.kind === "focus_control") {
        return { id: `cmd-focus-${parsed.control.controlId}`, label: `${parsed.interpreted} (shows, does not activate)`, run: () => runParsedCommand(parsed) };
      }
      if (parsed.kind === "safe_action") {
        // Pre-existing gap fixed here as part of wiring Mission Control's
        // seven safe actions into the typed Command Palette: safe_action
        // never had a palette dispatch path at all before this — only
        // voice transcripts reached executeSafeAction via runParsedCommand.
        // This one addition also makes "sync calendar"/"run morning
        // briefing" etc. work when typed, not just spoken.
        return { id: `cmd-safe-${parsed.action.kind}`, label: parsed.interpreted, run: () => runParsedCommand(parsed) };
      }
      if (parsed.kind === "blocked") {
        return { id: "cmd-blocked", label: `Not automatic: ${parsed.explanation}`, run: () => {} };
      }
      return null;
    },
    [runParsedCommand],
  );

  const systemsMenuItems: SystemsMenuItem[] = useMemo(
    () => [
      { id: "memory", label: "Memory Centre", onSelect: () => setShowMemoryCentre(true) },
      { id: "actions", label: "Actions Centre", onSelect: () => setShowActionsCentre(true) },
      { id: "skills", label: "Skills Centre", onSelect: () => setShowSkillsCentre(true) },
      { id: "integrations", label: "Integrations Centre", onSelect: () => setShowIntegrationsCentre(true) },
      { id: "routines", label: "Routine Centre", onSelect: () => setShowRoutineCentre(true) },
      { id: "recall", label: "Recall", onSelect: () => setShowRecallCentre(true) },
      { id: "research", label: "Research", onSelect: () => setShowResearchCentre(true) },
      { id: "decisions", label: "Decision Room", onSelect: () => setShowDecisionCentre(true) },
      { id: "data", label: "Data Management", onSelect: () => setShowDataManagement(true) },
    ],
    [],
  );

  const paletteActions: PaletteAction[] = useMemo(() => {
    const domainActions = domains.map((domain) => ({
      id: `goto-${domain.slug}`,
      label: `Go to ${domain.name}`,
      run: () => {
        closeAllOverlays();
        setSelectedSlug(domain.slug);
      },
    }));
    return [
      ...domainActions,
      {
        id: "goto-home",
        label: "Go to Jarvis home",
        run: goHome,
      },
      {
        id: "open-memory-centre",
        label: "Open Memory Centre",
        run: () => {
          setSelectedSlug(null);
          closeAllOverlays();
          setShowMemoryCentre(true);
        },
      },
      {
        id: "open-export",
        label: "Open Data Management (export)",
        run: () => {
          setSelectedSlug(null);
          closeAllOverlays();
          setShowDataManagement(true);
        },
      },
      {
        id: "open-actions-centre",
        label: "Open Actions Centre",
        run: () => {
          setSelectedSlug(null);
          closeAllOverlays();
          setShowActionsCentre(true);
        },
      },
      {
        id: "open-skills-centre",
        label: "Open Skills Centre",
        run: () => {
          setSelectedSlug(null);
          closeAllOverlays();
          setShowSkillsCentre(true);
        },
      },
      {
        id: "open-integrations-centre",
        label: "Open Integrations Centre",
        run: () => {
          setSelectedSlug(null);
          closeAllOverlays();
          setShowIntegrationsCentre(true);
        },
      },
      {
        id: "open-routine-centre",
        label: "Open Routine Centre",
        run: () => {
          setSelectedSlug(null);
          closeAllOverlays();
          setShowRoutineCentre(true);
        },
      },
      {
        id: "open-recall-centre",
        label: "Open Recall",
        run: () => {
          setSelectedSlug(null);
          closeAllOverlays();
          setRecallSeed(null);
          setShowRecallCentre(true);
        },
      },
      {
        id: "open-research-centre",
        label: "Open Research",
        run: () => {
          setSelectedSlug(null);
          closeAllOverlays();
          setShowResearchCentre(true);
        },
      },
      {
        id: "open-decision-centre",
        label: "Open Decision Room",
        run: () => {
          setSelectedSlug(null);
          closeAllOverlays();
          setShowDecisionCentre(true);
        },
      },
    ];
  }, [domains, goHome, closeAllOverlays]);

  // Home and every Centre page (never a domain conversation or the general
  // conversation — those each own their own push-to-talk instance via the
  // same useVoiceCapture hook) and never a diagnostic page (404 / offline),
  // where there is no live controller to send a question to.
  const ambientVoiceEligible =
    isKnownRoute && !diagForceOffline && health !== "error" && selectedSlug === null && !showGeneral;

  // Navigating away from Home/a Centre (into a domain or the general
  // conversation, each with their own separate voice instance) only ever
  // masked the overlay's display here — `ambientVoice`'s own internal state
  // kept whatever it was, "error" included. Returning to Home later made a
  // stale error reappear with no new failure behind it at all: the real
  // bug behind "the error persists no matter what I press." Clearing it the
  // moment this surface stops being eligible means Home always starts
  // clean the next time it becomes eligible again.
  useEffect(() => {
    if (!ambientVoiceEligible) ambientVoice.cancel();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [ambientVoiceEligible]);

  useEffect(() => {
    function onKeyDown(event: KeyboardEvent) {
      if (isTypingTarget(event.target)) return;

      const mod = event.metaKey || event.ctrlKey;

      if (mod && !event.shiftKey && event.key.toLowerCase() === "k") {
        event.preventDefault();
        setShowPalette((prev) => !prev);
        return;
      }

      if (mod && event.shiftKey && event.key.toLowerCase() === "e") {
        event.preventDefault();
        setShowPalette(false);
        setSelectedSlug(null);
        closeAllOverlays();
        setShowDataManagement(true);
        return;
      }

      // Cmd/Ctrl+Shift+F ("Find") opens Recall — Shift-modified so it
      // never collides with the browser's own Cmd+F "find in page".
      if (mod && event.shiftKey && event.key.toLowerCase() === "f") {
        event.preventDefault();
        setShowPalette(false);
        setSelectedSlug(null);
        closeAllOverlays();
        setRecallSeed(null);
        setShowRecallCentre(true);
        return;
      }

      if (showPalette) return; // palette owns its own Escape/Enter/arrows

      if (!mod && !event.altKey && /^[1-6]$/.test(event.key)) {
        event.preventDefault();
        const slug = domainSlugForNumber(Number(event.key));
        if (slug) selectDomainWithTransition(slug);
        return;
      }

      // 0 is the mirror of 1-6: instead of going into a domain, it always
      // returns to the Jarvis core itself (home), from a domain or from
      // any centre.
      if (!mod && !event.altKey && event.key === "0") {
        event.preventDefault();
        goHome();
        return;
      }

      // Global push-to-talk for Home/Centre pages — DomainView and
      // GeneralConversation each own their own identical Space handling via
      // the same useVoiceCapture hook while they're mounted, so this never
      // double-starts a capture: ambientVoiceEligible is false whenever
      // either of those is showing.
      if (!mod && !event.altKey && event.code === "Space" && ambientVoiceEligible) {
        // preventDefault on every repeated keydown the OS fires while the
        // key stays held, not just the first — Space's native "scroll the
        // page down" action fires on those later auto-repeat events too, so
        // guarding this behind `!event.repeat` (as `start()` below still
        // must be, to avoid restarting capture) let a long hold scroll the
        // whole app once the OS's key-repeat kicked in.
        event.preventDefault();
        if (!event.repeat) ambientVoice.start();
        return;
      }

      if (event.key === "Escape") {
        // Must clear a stuck "error" state (e.g. a failed microphone
        // permission check) back to idle, not just "listening" — otherwise
        // there is no way to dismiss a displayed voice error short of
        // quitting the app.
        if (
          ambientVoiceEligible &&
          (ambientVoice.voiceState === "listening" || ambientVoice.voiceState === "error")
        ) {
          ambientVoice.cancel();
          return;
        }
        // Domain view and the general conversation each own their own
        // Escape (cancel voice, then return home) — see DomainView.tsx /
        // GeneralConversation.tsx. Here we only handle the other top-level
        // views.
        if (
          selectedSlug === null &&
          !showGeneral &&
          (showDataManagement ||
            showMemoryCentre ||
            showActionsCentre ||
            showSkillsCentre ||
            showIntegrationsCentre ||
            showRoutineCentre ||
            showResearchCentre ||
            showDecisionCentre)
        ) {
          goHome();
        }
      }
    }

    function onKeyUp(event: KeyboardEvent) {
      if (isTypingTarget(event.target)) return;
      if (event.code === "Space" && ambientVoiceEligible) {
        event.preventDefault();
        ambientVoice.stop();
      }
    }

    window.addEventListener("keydown", onKeyDown);
    window.addEventListener("keyup", onKeyUp);
    return () => {
      window.removeEventListener("keydown", onKeyDown);
      window.removeEventListener("keyup", onKeyUp);
    };
  }, [
    showPalette,
    selectedSlug,
    showGeneral,
    showDataManagement,
    showMemoryCentre,
    showActionsCentre,
    showSkillsCentre,
    showIntegrationsCentre,
    showRoutineCentre,
    showResearchCentre,
    showDecisionCentre,
    goHome,
    closeAllOverlays,
    selectDomainWithTransition,
    ambientVoiceEligible,
    ambientVoice.start,
    ambientVoice.stop,
    ambientVoice.cancel,
    ambientVoice.voiceState,
  ]);

  const displayHealth: HealthStatus = diagForceOffline ? "error" : health;
  const displayAgentStatus = diagForceDegraded ? FAKE_DEGRADED_AGENT_STATUS : agentStatus;

  const agentLabel = !displayAgentStatus
    ? "Jarvis: unknown"
    : !displayAgentStatus.hermes_available
      ? "Jarvis: unavailable"
      : !displayAgentStatus.model_configured
        ? "Jarvis: model not configured"
        : `Jarvis: ${displayAgentStatus.model}`;

  // Hermes/model unavailable while the backend controller stays up is a
  // degraded (amber) state, not a critical (red) one — the same "reduced
  // but usable" condition ModelLinkBanner already shows in amber. Red is
  // reserved for a genuinely unavailable/unrecoverable controller, which
  // ControllerOfflineDiagnostic owns separately.
  const agentStatusClass = !displayAgentStatus
    ? "checking"
    : displayAgentStatus.hermes_available && displayAgentStatus.model_configured
      ? "ok"
      : "degraded";

  const noOverlayActive =
    !showDataManagement &&
    !showMemoryCentre &&
    !showActionsCentre &&
    !showSkillsCentre &&
    !showIntegrationsCentre &&
    !showRoutineCentre &&
    !showRecallCentre &&
    !showResearchCentre &&
    !showDecisionCentre &&
    !showGeneral;
  // A diagnostic page (404 or controller offline) is never "Home" for
  // shell-chrome purposes — the bottom-bar shortcut hints and the top-bar
  // palette/systems controls don't apply while diagnosing a fault.
  const isDiagnosticPage = !isKnownRoute || displayHealth === "error";
  const onHome = noOverlayActive && selectedSlug === null && !isDiagnosticPage;

  const activeDomain = domains.find((d) => d.slug === selectedSlug);
  const currentLocation = showDataManagement
    ? "Data Management"
    : showMemoryCentre
      ? "Memory Centre"
      : showActionsCentre
        ? "Actions Centre"
        : showSkillsCentre
          ? "Skills Centre"
          : showIntegrationsCentre
            ? "Integrations Centre"
            : showRoutineCentre
              ? "Routine Centre"
              : showRecallCentre
                ? "Recall"
                : showResearchCentre
                  ? "Research"
                  : showDecisionCentre
                    ? "Decision Room"
                    : showGeneral
                      ? "Jarvis"
                      : activeDomain
                        ? activeDomain.name
                        : "Home";

  return (
    <div className="app">
      <VoiceCaptureOverlay
        voiceState={ambientVoiceEligible ? ambientVoice.voiceState : "idle"}
        scope={currentLocation.toUpperCase()}
        micStream={ambientVoice.micStream}
        ttsAudioElement={ambientVoice.ttsAudioEl}
        errorMessage={ambientVoice.voiceError}
        onDismiss={ambientVoice.cancel}
      />
      {commandFeedback && (
        <p className={`command-feedback-banner ${commandFeedback.tone}`} role="status" aria-live="polite">
          {commandFeedback.text}
        </p>
      )}
      {pendingConfirm && (
        <ConfirmDialog
          heading={`${pendingConfirm.interpreted}?`}
          warning={pendingConfirm.warning}
          busy={confirmBusy}
          tone={pendingConfirm.action.kind === "disconnect_integration" ? "danger" : "default"}
          onConfirm={handleConfirmAction}
          onCancel={() => setPendingConfirm(null)}
        />
      )}
      <div className={`top-bar${topBarScrollable ? " is-scrollable" : ""}`} ref={topBarRef}>
        <span className="top-bar-brand">
          <span className="top-bar-brand-dot" aria-hidden="true" />
          <span>JARVIS</span>
        </span>
        <span className="top-bar-location">{currentLocation}</span>
        <span className="top-bar-spacer" />
        <span className="top-bar-status-group">
          <span
            className={`health-dot ${displayHealth}`}
            role="status"
            aria-label={`Backend status: ${displayHealth}`}
            title={`Backend status: ${displayHealth}`}
          />
          <span>
            {displayHealth === "ok" && "Backend connected"}
            {displayHealth === "checking" && "Checking backend…"}
            {displayHealth === "error" && "Backend unavailable"}
          </span>
          <span
            className={`health-dot ${agentStatusClass}`}
            role="status"
            aria-label={agentLabel}
            title={agentLabel}
          />
          <span>{agentLabel}</span>
        </span>
        {noOverlayActive && selectedSlug === null && (
          <div className="top-bar-controls">
            <button
              type="button"
              className="palette-hint-button"
              onClick={() => setShowPalette(true)}
              aria-label="Open command palette"
              title="Command palette (⌘K)"
            >
              <kbd>⌘K</kbd>
            </button>
            <SystemsMenu items={systemsMenuItems} />
          </div>
        )}
      </div>

      <div className={`app-main${onHome ? "" : " console-canvas"}`}>
        {!isKnownRoute ? (
          <NotFoundDiagnostic
            onReturnHome={() => {
              window.history.replaceState(null, "", "/");
              setIsKnownRoute(true);
              goHome();
            }}
            onOpenPalette={() => setShowPalette(true)}
          />
        ) : displayHealth === "error" ? (
          <ControllerOfflineDiagnostic checkHealth={checkHealth} onRecovered={handleControllerRecovered} />
        ) : showDataManagement ? (
          <DataManagement onBack={() => setShowDataManagement(false)} />
        ) : showMemoryCentre ? (
          <MemoryCentre onBack={() => setShowMemoryCentre(false)} />
        ) : showActionsCentre ? (
          <ActionsCentre onBack={() => setShowActionsCentre(false)} />
        ) : showSkillsCentre ? (
          <SkillsCentre onBack={() => setShowSkillsCentre(false)} />
        ) : showIntegrationsCentre ? (
          <IntegrationsCentre onBack={() => setShowIntegrationsCentre(false)} />
        ) : showRoutineCentre ? (
          <RoutineCentre onBack={() => setShowRoutineCentre(false)} />
        ) : showRecallCentre ? (
          <RecallCentre
            onBack={() => setShowRecallCentre(false)}
            onNavigate={(target) => {
              setShowRecallCentre(false);
              navigateToTarget(target);
            }}
            seed={recallSeed}
          />
        ) : showResearchCentre ? (
          <ResearchCentre onBack={() => setShowResearchCentre(false)} onNavigate={navigateToTarget} />
        ) : showDecisionCentre ? (
          <DecisionCentre onBack={() => setShowDecisionCentre(false)} onNavigate={navigateToTarget} />
        ) : showGeneral ? (
          <GeneralConversation onBack={goHome} onSystemCommand={runParsedCommand} />
        ) : selectedSlug === null ? (
          <Home
            onSelectDomain={selectDomainWithTransition}
            onOpenGeneral={() => setShowGeneral(true)}
            onNavigate={navigateToTarget}
            health={displayHealth}
            commandFocusSlug={commandFocusSlug}
            modelDegraded={displayAgentStatus !== null && !displayAgentStatus.hermes_available}
            onRetryModel={handleRetryModel}
            voiceActive={ambientVoiceEligible && ambientVoice.voiceState !== "idle"}
          />
        ) : (
          <DomainView
            slug={selectedSlug}
            onBack={goHomeFromDomainWithTransition}
            onSystemCommand={runParsedCommand}
            onSearchThisDomain={() => {
              setRecallSeed({ query: "", domainHint: selectedSlug, token: Date.now() });
              setSelectedSlug(null);
              setShowRecallCentre(true);
            }}
          />
        )}
      </div>

      {onHome && (
        <div className="bottom-bar" aria-hidden="true">
          <span>
            <kbd>0</kbd> Jarvis home · <kbd>1</kbd>–<kbd>6</kbd> Select domain
          </span>
          <span>
            <kbd>⌘K</kbd> Command palette
          </span>
          <span>
            <kbd>⌘⇧E</kbd> Export
          </span>
          <span>
            <kbd>Space</kbd> Hold to talk
          </span>
        </div>
      )}

      {showPalette && (
        <CommandPalette actions={paletteActions} resolveCommand={resolveCommand} onClose={() => setShowPalette(false)} />
      )}
    </div>
  );
}

export default App;
