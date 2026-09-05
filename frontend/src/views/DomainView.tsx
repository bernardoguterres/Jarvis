import { useEffect, useState, type FormEvent } from "react";
import {
  archiveStructuredRecord,
  createConversation,
  createMemory,
  createMessage,
  createStructuredRecord,
  fetchConversations,
  fetchDomains,
  fetchMessages,
  fetchMissionFocus,
  getContextSnapshot,
  getDomainSummary,
  listMemories,
  listStructuredRecords,
  sendTurn,
  setDomainSummary,
  type Conversation,
  type ContextSnapshot,
  type Domain,
  type DomainSummary,
  type MemoryItem,
  type Message,
  type MissionFocusPin,
  type RecordType,
  type StructuredRecord,
} from "../api";
import AddToMissionFocusButton from "../components/AddToMissionFocusButton";
import FocusOnThisButton from "../components/FocusOnThisButton";
import DomainEmblem from "../components/DomainEmblem";
import MemoryItemCard from "../components/MemoryItemCard";
import VoiceStateIndicator from "../components/VoiceStateIndicator";
import VoiceCaptureOverlay from "../components/voice/VoiceCaptureOverlay";
import { useVoiceCapture } from "../hooks/useVoiceCapture";
import type { ParsedCommand } from "../commands/registry";
import { SENSITIVE_SLUGS } from "../sensitiveDomains";
import { MiniCoreIndicator, ConsoleModule, ContextRail, TechnicalDetails } from "../components/console/Console";
import { formatDateTime } from "../formatDateTime";

interface DomainViewProps {
  slug: string;
  onBack: () => void;
  /** Opens Recall Centre pre-scoped to just this one domain (Phase 12D) —
   * optional so existing tests that render DomainView standalone don't
   * need to supply it; App.tsx always passes it in the real app. */
  onSearchThisDomain?: () => void;
  /** Executes a recognized navigate/focus_control/safe_action/confirm_required
   * command (see commands/registry.ts) against App's real navigation and
   * action-execution state — DomainView itself owns none of that, only App
   * does. Optional so existing tests that render DomainView standalone
   * don't need to supply a navigation harness just to exercise unrelated
   * behavior. */
  onSystemCommand?: (
    parsed: Extract<ParsedCommand, { kind: "navigate" } | { kind: "focus_control" } | { kind: "safe_action" } | { kind: "confirm_required" }>,
  ) => void;
}

const RECORD_TYPES_BY_SLUG: Record<string, RecordType[]> = {
  body: ["body_weight", "body_symptom"],
  mind: ["mind_checkin"],
  people: ["people_interaction"],
  path: ["path_deadline"],
  build: ["build_checkpoint"],
  life: ["life_task"],
};

// Phase 12C: only these record types are eligible Mission Focus sources —
// BODY/MIND/PEOPLE record types are deliberately never offered the
// "Add to Mission Focus" control at all (see app/models_mission_focus.py's
// MISSION_FOCUS_SOURCE_TYPES, the real server-side boundary).
const MISSION_FOCUS_ELIGIBLE_RECORD_TYPES: RecordType[] = ["life_task", "path_deadline", "build_checkpoint"];

function DomainView({ slug, onBack, onSystemCommand, onSearchThisDomain }: DomainViewProps) {
  const [domain, setDomain] = useState<Domain | null>(null);
  const [allDomains, setAllDomains] = useState<Domain[]>([]);
  const [conversations, setConversations] = useState<Conversation[]>([]);
  const [selectedConversationId, setSelectedConversationId] = useState<string | null>(null);
  const [messages, setMessages] = useState<Message[]>([]);
  const [newTitle, setNewTitle] = useState("");
  const [draftMessage, setDraftMessage] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);
  const [sendingToJarvis, setSendingToJarvis] = useState(false);
  const [lastTurnMeta, setLastTurnMeta] = useState<{ provider: string; model: string } | null>(
    null,
  );
  const [runIdByMessageId, setRunIdByMessageId] = useState<Record<string, string>>({});
  const [openContextFor, setOpenContextFor] = useState<string | null>(null);
  const [contextSnapshots, setContextSnapshots] = useState<Record<string, ContextSnapshot>>({});

  // Memory / summary / records
  const [summary, setSummaryState] = useState<DomainSummary | null>(null);
  const [summaryDraft, setSummaryDraft] = useState("");
  const [editingSummary, setEditingSummary] = useState(false);
  const [domainMemories, setDomainMemories] = useState<MemoryItem[]>([]);
  const [records, setRecords] = useState<StructuredRecord[]>([]);
  const [missionFocusPins, setMissionFocusPins] = useState<MissionFocusPin[]>([]);
  const [rememberDraft, setRememberDraft] = useState<{ messageId: string; content: string } | null>(
    null,
  );
  const [recordType, setRecordType] = useState<RecordType | "">("");
  const [recordPayloadText, setRecordPayloadText] = useState("");

  // Additional-domain selection for the next turn only.
  const [selectedExtraDomains, setSelectedExtraDomains] = useState<string[]>([]);
  const [sensitiveWarningAcknowledged, setSensitiveWarningAcknowledged] = useState(false);

  async function refreshMemoryData(domainId: string) {
    try {
      const [summaryData, memories, recordList] = await Promise.all([
        getDomainSummary(slug),
        listMemories({ scope: "domain", domain_id: domainId }),
        listStructuredRecords(slug),
      ]);
      setSummaryState(summaryData);
      setDomainMemories(memories);
      setRecords(recordList);
    } catch {
      setError("Could not load domain memory data.");
    }
    // A separate, isolated try/catch: Mission Focus being unavailable must
    // never block the rest of the domain view from loading.
    try {
      const state = await fetchMissionFocus();
      setMissionFocusPins(state.active_pins ?? []);
    } catch {
      setMissionFocusPins([]);
    }
  }

  useEffect(() => {
    let cancelled = false;
    setError(null);

    Promise.all([fetchDomains(), fetchConversations(slug)])
      .then(([domains, convos]) => {
        if (cancelled) return;
        const found = domains.find((d) => d.slug === slug) ?? null;
        setDomain(found);
        setAllDomains(domains);
        setConversations(convos);
        if (found) refreshMemoryData(found.id);
      })
      .catch(() => {
        if (!cancelled) setError("Could not load this domain from the backend.");
      });

    return () => {
      cancelled = true;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [slug]);

  useEffect(() => {
    if (!selectedConversationId) {
      setMessages([]);
      return;
    }

    let cancelled = false;
    fetchMessages(selectedConversationId)
      .then((data) => {
        if (!cancelled) setMessages(data);
      })
      .catch(() => {
        if (!cancelled) setError("Could not load messages for this conversation.");
      });

    return () => {
      cancelled = true;
    };
  }, [selectedConversationId]);

  async function handleCreateConversation(event: FormEvent) {
    event.preventDefault();
    try {
      const conversation = await createConversation(slug, newTitle.trim() || undefined);
      setConversations((prev) => [conversation, ...prev]);
      setSelectedConversationId(conversation.id);
      setNewTitle("");
    } catch {
      setError("Could not create a new conversation.");
    }
  }

  async function handleSaveNote(event: FormEvent) {
    event.preventDefault();
    if (!selectedConversationId || !draftMessage.trim()) return;

    setSaving(true);
    setError(null);
    try {
      const message = await createMessage(selectedConversationId, draftMessage.trim());
      setMessages((prev) => [...prev, message]);
      setDraftMessage("");
    } catch {
      setError("Could not save this note.");
    } finally {
      setSaving(false);
    }
  }

  function toggleExtraDomain(domainId: string) {
    setSensitiveWarningAcknowledged(false);
    setSelectedExtraDomains((prev) =>
      prev.includes(domainId) ? prev.filter((id) => id !== domainId) : [...prev, domainId],
    );
  }

  const selectedExtraSlugs = allDomains
    .filter((d) => selectedExtraDomains.includes(d.id))
    .map((d) => d.slug);
  const needsSensitiveWarning = selectedExtraSlugs.some((s) => SENSITIVE_SLUGS.has(s));

  async function submitTurn(content: string): Promise<{ ok: boolean; assistantMessage: Message | null }> {
    if (!selectedConversationId) return { ok: false, assistantMessage: null };

    const idempotencyKey =
      typeof crypto.randomUUID === "function"
        ? crypto.randomUUID()
        : `${Date.now()}-${Math.random()}`;

    setSendingToJarvis(true);
    setError(null);
    try {
      const result = await sendTurn(selectedConversationId, content, idempotencyKey, selectedExtraDomains);
      setMessages((prev) => [
        ...prev,
        result.user_message,
        ...(result.assistant_message ? [result.assistant_message] : []),
      ]);
      if (result.context_snapshot_id && result.assistant_message) {
        setRunIdByMessageId((prev) => ({ ...prev, [result.assistant_message!.id]: result.run_id }));
      }
      if (result.status === "succeeded") {
        setLastTurnMeta({ provider: result.provider, model: result.model });
      } else if (result.error) {
        setError(`Jarvis could not respond: ${result.error.summary}`);
      }
      // Cross-domain selection applies only to this single turn.
      setSelectedExtraDomains([]);
      setSensitiveWarningAcknowledged(false);
      return { ok: true, assistantMessage: result.assistant_message };
    } catch {
      setError("Could not reach Jarvis. Your message was not sent.");
      return { ok: false, assistantMessage: null };
    } finally {
      setSendingToJarvis(false);
    }
  }

  async function handleSendToJarvis() {
    if (!selectedConversationId || !draftMessage.trim() || sendingToJarvis) return;
    if (needsSensitiveWarning && !sensitiveWarningAcknowledged) return;

    const content = draftMessage.trim();
    const { ok } = await submitTurn(content);
    if (ok) setDraftMessage("");
  }

  // --- push-to-talk voice (shared machine — see hooks/useVoiceCapture.ts) -

  const voice = useVoiceCapture({
    guard: () => {
      if (!selectedConversationId) return false;
      if (needsSensitiveWarning && !sensitiveWarningAcknowledged) {
        return "Acknowledge the sensitive-domain warning before using voice.";
      }
      return true;
    },
    onSystemCommand,
    submitTurn,
  });
  const { voiceState, voiceError, lastCommand, micStream, ttsAudioEl } = voice;

  const voiceBusy = voiceState !== "idle" && voiceState !== "error" && voiceState !== "cancelled";

  const startPushToTalk = () => {
    if (!selectedConversationId) return;
    voice.start();
  };

  const stopPushToTalk = () => voice.stop();
  const cancelPushToTalk = () => voice.cancel();

  useEffect(() => {
    function isTypingTarget(target: EventTarget | null): boolean {
      const el = target as HTMLElement | null;
      if (!el) return false;
      const tag = el.tagName;
      return tag === "INPUT" || tag === "TEXTAREA" || tag === "SELECT" || el.isContentEditable;
    }

    function onKeyDown(event: KeyboardEvent) {
      if (event.code === "Space" && !isTypingTarget(event.target)) {
        // preventDefault on every repeated keydown the OS fires while the
        // key stays held, not just the first — otherwise Space's native
        // "scroll the page down" kicks in once auto-repeat starts on a
        // long hold. startPushToTalk() itself still only fires once.
        event.preventDefault();
        if (!event.repeat) startPushToTalk();
      } else if (event.code === "Escape" && !isTypingTarget(event.target)) {
        // CLAUDE.md §8: Escape cancels voice activity, or otherwise returns
        // to the central HUD. Must also clear a stuck "error" state (e.g.
        // a failed microphone permission check), not just "listening" —
        // otherwise there is no way to dismiss a displayed voice error
        // short of quitting the app.
        if (voiceState === "listening" || voiceState === "error") {
          cancelPushToTalk();
        } else {
          onBack();
        }
      }
    }

    function onKeyUp(event: KeyboardEvent) {
      if (event.code === "Space" && !isTypingTarget(event.target)) {
        event.preventDefault();
        stopPushToTalk();
      }
    }

    window.addEventListener("keydown", onKeyDown);
    window.addEventListener("keyup", onKeyUp);
    return () => {
      window.removeEventListener("keydown", onKeyDown);
      window.removeEventListener("keyup", onKeyUp);
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [voice.start, voice.stop, voice.cancel, voiceState, onBack, selectedConversationId]);

  async function handleShowContext(messageId: string) {
    if (openContextFor === messageId) {
      setOpenContextFor(null);
      return;
    }
    const runId = runIdByMessageId[messageId];
    if (!runId) return;
    if (!contextSnapshots[runId]) {
      try {
        const snapshot = await getContextSnapshot(runId);
        setContextSnapshots((prev) => ({ ...prev, [runId]: snapshot }));
      } catch {
        setError("Could not load context details for this response.");
        return;
      }
    }
    setOpenContextFor(messageId);
  }

  function handleRememberFromMessage(message: Message) {
    setRememberDraft({ messageId: message.id, content: message.content });
  }

  async function handleConfirmRemember(title: string, kind: MemoryItem["kind"]) {
    if (!rememberDraft || !domain) return;
    try {
      await createMemory({
        scope: "domain",
        domain_id: domain.id,
        kind,
        title,
        content: rememberDraft.content,
        source_message_id: rememberDraft.messageId,
      });
      setRememberDraft(null);
      await refreshMemoryData(domain.id);
    } catch {
      setError("Could not save this memory.");
    }
  }

  async function handleSaveSummary() {
    try {
      const updated = await setDomainSummary(slug, summaryDraft);
      setSummaryState(updated);
      setEditingSummary(false);
    } catch {
      setError("Could not save the domain summary.");
    }
  }

  async function handleCreateRecord(event: FormEvent) {
    event.preventDefault();
    if (!recordType || !recordPayloadText.trim()) return;
    try {
      const payload = JSON.parse(recordPayloadText);
      await createStructuredRecord(slug, {
        record_type: recordType,
        occurred_at: new Date().toISOString(),
        payload,
      });
      setRecordPayloadText("");
      if (domain) await refreshMemoryData(domain.id);
    } catch {
      setError("Could not save this record — check the payload is valid JSON matching the record type.");
    }
  }

  async function handleArchiveRecord(recordId: string) {
    try {
      await archiveStructuredRecord(recordId);
      if (domain) await refreshMemoryData(domain.id);
    } catch {
      setError("Could not archive this record.");
    }
  }

  const isBusy = saving || sendingToJarvis;
  const recordTypesForDomain = RECORD_TYPES_BY_SLUG[slug] ?? [];

  return (
    <div className="domain-view">
      <VoiceCaptureOverlay
        voiceState={voiceState}
        scope={(domain?.name ?? slug.toUpperCase())}
        micStream={micStream}
        ttsAudioElement={ttsAudioEl}
        errorMessage={voiceError}
        onDismiss={cancelPushToTalk}
      />
      <button type="button" className="back-button" onClick={onBack}>
        ← Back to Jarvis
      </button>

      <header className="console-header">
        <DomainEmblem slug={slug} name={domain?.name ?? slug.toUpperCase()} />
        {/* Phase 6, D91: only mounted while genuinely active — with a real
            bespoke domain glyph now the one focal identity in this header,
            a dormant/idle violet arc+dot next to it had no informational
            value and read as a second, competing icon. It still exists for
            its one real job (a live "Jarvis is processing/listening"
            signal), just never rendered when there's nothing to signal. */}
        {(sendingToJarvis || voiceState !== "idle") && (
          <MiniCoreIndicator active size="sm" />
        )}
        <div className="console-header-text">
          <span className="console-eyebrow">Domain</span>
          <h1>{domain?.name ?? slug.toUpperCase()}</h1>
          <p className="console-description">{domain?.description}</p>
          {(domainMemories.length > 0 || conversations.length > 0) && (
            <div className="console-header-meta">
              <span>{conversations.length} conversation{conversations.length === 1 ? "" : "s"}</span>
              <span>{domainMemories.length} memor{domainMemories.length === 1 ? "y" : "ies"}</span>
            </div>
          )}
        </div>
        {onSearchThisDomain && (
          <div className="console-header-actions">
            <button type="button" className="action-note" onClick={onSearchThisDomain}>
              Search this domain
            </button>
          </div>
        )}
      </header>

      <TechnicalDetails summary="Save as note vs. Send to Jarvis — what's the difference?">
        <p>
          "Save as note" stores what you type without asking Jarvis anything. "Send to Jarvis"
          asks the configured model for a real response — only that action generates one.
        </p>
      </TechnicalDetails>

      {error && (
        <p className="error-banner" role="alert">
          {error}
        </p>
      )}

      <div className="cockpit-layout">
      <div className="cockpit-main conversation-panel">
        <section className="conversation-list" aria-label="Conversations">
          <h2>Conversations</h2>
          <ul>
            {conversations.map((conversation) => (
              <li key={conversation.id}>
                <button
                  type="button"
                  aria-current={selectedConversationId === conversation.id}
                  onClick={() => setSelectedConversationId(conversation.id)}
                >
                  {conversation.title || "Untitled conversation"}
                </button>
              </li>
            ))}
            {conversations.length === 0 && <li className="empty-hint">No conversations yet.</li>}
          </ul>

          <form className="new-conversation-form" onSubmit={handleCreateConversation}>
            <label htmlFor="new-conversation-title" className="sr-only">
              New conversation title
            </label>
            <input
              id="new-conversation-title"
              type="text"
              placeholder="New conversation title (optional)"
              value={newTitle}
              onChange={(event) => setNewTitle(event.target.value)}
            />
            <button type="submit" className="primary">
              New
            </button>
          </form>
        </section>

        {!selectedConversationId && (
          <div className="empty-console-state">
            <p>Start a conversation, or open one from the list above.</p>
          </div>
        )}

        {selectedConversationId && (
          <section className="conversation-detail" aria-label="Messages">
            <ul className="message-list">
              {messages.map((message) => (
                <li key={message.id} className="message-item">
                  <div className="message-role">
                    {message.role}
                    {message.model_used && (
                      <span className="message-model"> · {message.model_used}</span>
                    )}
                  </div>
                  <p className="message-content">{message.content}</p>
                  <div className="message-actions">
                    {message.role === "user" && (
                      <button type="button" onClick={() => handleRememberFromMessage(message)}>
                        Remember
                      </button>
                    )}
                    {message.role === "assistant" && runIdByMessageId[message.id] && (
                      <button type="button" onClick={() => handleShowContext(message.id)}>
                        {openContextFor === message.id ? "Hide context used" : "Context used"}
                      </button>
                    )}
                  </div>
                  {openContextFor === message.id &&
                    runIdByMessageId[message.id] &&
                    contextSnapshots[runIdByMessageId[message.id]] && (
                      <div className="context-used-panel">
                        {(() => {
                          const snap = contextSnapshots[runIdByMessageId[message.id]];
                          return (
                            <ul>
                              <li>Query: {snap.retrieval_query}</li>
                              <li>Global memory versions used: {snap.global_memory_version_ids.length}</li>
                              <li>Domain memory versions used: {snap.domain_memory_version_ids.length}</li>
                              <li>Domain summary versions used: {snap.domain_summary_version_ids.length}</li>
                              <li>Structured records used: {snap.structured_record_ids.length}</li>
                              <li>Additional domains: {snap.additional_domain_ids.length}</li>
                              <li>Recent messages included: {snap.recent_message_ids.length}</li>
                              <li>Estimated context size: {snap.estimated_context_chars} chars</li>
                              {snap.retrieval_reasons.map((r, i) => (
                                <li key={i}>
                                  {r.memory_item_id}: {r.reason}
                                </li>
                              ))}
                            </ul>
                          );
                        })()}
                      </div>
                    )}
                </li>
              ))}
              {messages.length === 0 && <li>No notes yet in this conversation.</li>}
              {sendingToJarvis && (
                <li className="message-item message-pending" aria-live="polite">
                  <div className="message-role">jarvis</div>
                  <p className="message-content">Thinking…</p>
                </li>
              )}
            </ul>

            {lastTurnMeta && (
              <p className="turn-meta">
                Last response from {lastTurnMeta.provider} · {lastTurnMeta.model}
              </p>
            )}

            {rememberDraft && (
              <div className="remember-form">
                <p>Save this as a {domain?.name} memory:</p>
                <p className="message-content">{rememberDraft.content}</p>
                <RememberForm onConfirm={handleConfirmRemember} onCancel={() => setRememberDraft(null)} />
              </div>
            )}

            <section aria-label="Push-to-talk voice" className="push-to-talk">
              <button
                type="button"
                className={`push-to-talk-button${voice.pushToTalkStatus === "recording" ? " recording" : ""}`}
                // Must stay enabled throughout "listening" (even before the
                // hook's internal status reaches "recording", i.e. while a
                // getUserMedia permission prompt is still pending) — this
                // button is also how the user releases/stops. A disabled
                // element does not receive mouseup/mouseleave at all, so
                // disabling it mid-listening would strand the recording
                // with no way to release it via mouse or touch.
                disabled={!selectedConversationId || (voiceBusy && voiceState !== "listening")}
                onMouseDown={startPushToTalk}
                onMouseUp={stopPushToTalk}
                onMouseLeave={cancelPushToTalk}
                onTouchStart={(e) => {
                  e.preventDefault();
                  startPushToTalk();
                }}
                onTouchEnd={(e) => {
                  e.preventDefault();
                  stopPushToTalk();
                }}
              >
                Hold to talk (or hold Space)
              </button>
              <VoiceStateIndicator state={voiceState} />
              {voiceError && (
                <p className="error-banner" role="alert">
                  {voiceError}
                </p>
              )}
              {lastCommand && (
                <p className={`voice-command-feedback${lastCommand.sensitive ? " is-sensitive" : ""}`} aria-live="polite">
                  Heard: "{lastCommand.heard}" — {lastCommand.interpreted}
                </p>
              )}
            </section>

            <form className="message-form" onSubmit={handleSaveNote}>
              <label htmlFor="draft-message" className="sr-only">
                Write a message
              </label>
              <textarea
                id="draft-message"
                placeholder="Write a note, or send it to Jarvis…"
                value={draftMessage}
                onChange={(event) => setDraftMessage(event.target.value)}
                disabled={isBusy}
              />
              <div className="message-form-actions">
                <button type="submit" className="action-note" disabled={isBusy || !draftMessage.trim()}>
                  {saving ? "Saving…" : "Save as note"}
                </button>
                <button
                  type="button"
                  className="primary"
                  onClick={handleSendToJarvis}
                  disabled={
                    isBusy ||
                    !draftMessage.trim() ||
                    (needsSensitiveWarning && !sensitiveWarningAcknowledged)
                  }
                >
                  {sendingToJarvis ? "Sending…" : "Send to Jarvis"}
                </button>
              </div>
            </form>
          </section>
        )}
      </div>

      <ContextRail className="cockpit-rail">
        <ConsoleModule title={`${domain?.name ?? ""} summary`.trim()} ariaLabel="Domain summary">
          {editingSummary ? (
            <div>
              <textarea value={summaryDraft} onChange={(e) => setSummaryDraft(e.target.value)} />
              <div className="message-form-actions">
                <button type="button" className="primary" onClick={handleSaveSummary}>
                  Save summary
                </button>
                <button type="button" onClick={() => setEditingSummary(false)}>
                  Cancel
                </button>
              </div>
            </div>
          ) : (
            <div>
              <p>{summary?.current_content ?? "No summary yet."}</p>
              <button
                type="button"
                onClick={() => {
                  setSummaryDraft(summary?.current_content ?? "");
                  setEditingSummary(true);
                }}
              >
                Edit summary
              </button>
            </div>
          )}
        </ConsoleModule>

        <ConsoleModule title={`${domain?.name ?? ""} memories`.trim()} ariaLabel="Domain memories">
          <ul className="memory-list">
            {domainMemories.map((memory) => (
              <MemoryItemCard key={memory.id} memory={memory} onChanged={() => domain && refreshMemoryData(domain.id)} />
            ))}
            {domainMemories.length === 0 && <li className="empty-hint">No memories yet in this domain.</li>}
          </ul>
        </ConsoleModule>

        <ConsoleModule title={`${domain?.name ?? ""} records`.trim()} ariaLabel="Structured records">
          <ul>
            {records.map((record) => (
              <li key={record.id}>
                [{record.record_type}] {formatDateTime(record.occurred_at, record.occurred_at)}: {JSON.stringify(record.payload)}{" "}
                <button type="button" onClick={() => handleArchiveRecord(record.id)}>
                  Archive
                </button>{" "}
                {MISSION_FOCUS_ELIGIBLE_RECORD_TYPES.includes(record.record_type) && (
                  <>
                    <AddToMissionFocusButton
                      sourceType={record.record_type as "life_task" | "path_deadline" | "build_checkpoint"}
                      sourceId={record.id}
                      existingPin={missionFocusPins.find(
                        (p) => p.source_type === record.record_type && p.source_id === record.id,
                      )}
                      onChanged={() => domain && refreshMemoryData(domain.id)}
                    />{" "}
                    <FocusOnThisButton
                      sourceType={record.record_type as "life_task" | "path_deadline" | "build_checkpoint"}
                      sourceId={record.id}
                    />
                  </>
                )}
              </li>
            ))}
            {records.length === 0 && <li className="empty-hint">No records yet.</li>}
          </ul>
          {recordTypesForDomain.length > 0 && (
            <form onSubmit={handleCreateRecord} className="memory-create-form">
              <select aria-label="Record type" value={recordType} onChange={(e) => setRecordType(e.target.value as RecordType)}>
                <option value="">Choose record type…</option>
                {recordTypesForDomain.map((rt) => (
                  <option key={rt} value={rt}>
                    {rt}
                  </option>
                ))}
              </select>
              <textarea
                placeholder='Payload JSON, e.g. {"kilograms": 78.5}'
                value={recordPayloadText}
                onChange={(e) => setRecordPayloadText(e.target.value)}
              />
              <button type="submit" className="primary">
                Track
              </button>
            </form>
          )}
        </ConsoleModule>

        <ConsoleModule title="Include another domain (this turn only)" ariaLabel="Include another domain">
          <div className="extra-domain-selector">
            {allDomains
              .filter((d) => d.slug !== slug)
              .map((d) => (
                <label key={d.id}>
                  <input
                    type="checkbox"
                    checked={selectedExtraDomains.includes(d.id)}
                    onChange={() => toggleExtraDomain(d.id)}
                  />
                  {d.name}
                </label>
              ))}
          </div>
          {needsSensitiveWarning && (
            <div className="sensitive-warning">
              <p>
                You're including a sensitive domain (BODY, MIND, or PEOPLE) in this turn's
                context. Its memories will be sent to the model for this turn only.
              </p>
              <label>
                <input
                  type="checkbox"
                  checked={sensitiveWarningAcknowledged}
                  onChange={(e) => setSensitiveWarningAcknowledged(e.target.checked)}
                />
                I understand, include it anyway
              </label>
            </div>
          )}
        </ConsoleModule>
      </ContextRail>
      </div>
    </div>
  );
}

function RememberForm({
  onConfirm,
  onCancel,
}: {
  onConfirm: (title: string, kind: MemoryItem["kind"]) => void;
  onCancel: () => void;
}) {
  const [title, setTitle] = useState("");
  const [kind, setKind] = useState<MemoryItem["kind"]>("fact");

  return (
    <div className="message-form-actions">
      <input
        type="text"
        placeholder="Memory title"
        value={title}
        onChange={(e) => setTitle(e.target.value)}
      />
      <select aria-label="Memory kind" value={kind} onChange={(e) => setKind(e.target.value as MemoryItem["kind"])}>
        <option value="fact">fact</option>
        <option value="health_context">health_context</option>
        <option value="relationship_context">relationship_context</option>
        <option value="goal">goal</option>
        <option value="decision">decision</option>
      </select>
      <button type="button" className="primary" onClick={() => title.trim() && onConfirm(title.trim(), kind)}>
        Confirm remember
      </button>
      <button type="button" onClick={onCancel}>
        Cancel
      </button>
    </div>
  );
}

export default DomainView;
