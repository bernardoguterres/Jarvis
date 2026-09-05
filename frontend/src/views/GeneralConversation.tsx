import { useEffect, useState, type FormEvent } from "react";
import {
  createGeneralConversation,
  createMemory,
  createMessage,
  fetchDomains,
  fetchGeneralConversations,
  fetchMessages,
  getContextSnapshot,
  sendTurn,
  type Conversation,
  type ContextSnapshot,
  type Domain,
  type MemoryItem,
  type Message,
} from "../api";
import { MiniCoreIndicator, ConsoleModule, ConsoleSectionLabel } from "../components/console/Console";
import VoiceStateIndicator from "../components/VoiceStateIndicator";
import VoiceCaptureOverlay from "../components/voice/VoiceCaptureOverlay";
import { useVoiceCapture } from "../hooks/useVoiceCapture";
import type { ParsedCommand } from "../commands/registry";
import { SENSITIVE_SLUGS } from "../sensitiveDomains";

interface GeneralConversationProps {
  onBack: () => void;
  onSystemCommand?: (
    parsed: Extract<ParsedCommand, { kind: "navigate" } | { kind: "focus_control" } | { kind: "safe_action" } | { kind: "confirm_required" }>,
  ) => void;
}

/** The general Jarvis conversation opened from the core itself (Phase 6).
 * This is deliberately NOT a domain view with a domain stripped out: there
 * is no domain summary/memories/records rail, because a general turn never
 * auto-retrieves any domain-scoped material by default — see
 * docs/ARCHITECTURE.md and backend/app/context_builder.py. The only way
 * domain context enters a general turn is the explicit per-turn chip
 * selection below, which is the exact same `additional_domain_ids`
 * mechanism DomainView uses for cross-domain inclusion — general
 * conversation is that same mechanism with no "home" domain of its own. */
function GeneralConversation({ onBack, onSystemCommand }: GeneralConversationProps) {
  const [conversations, setConversations] = useState<Conversation[]>([]);
  const [domains, setDomains] = useState<Domain[]>([]);
  const [selectedConversationId, setSelectedConversationId] = useState<string | null>(null);
  const [messages, setMessages] = useState<Message[]>([]);
  const [newTitle, setNewTitle] = useState("");
  const [draftMessage, setDraftMessage] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);
  const [sendingToJarvis, setSendingToJarvis] = useState(false);
  const [lastTurnMeta, setLastTurnMeta] = useState<{ provider: string; model: string } | null>(null);
  const [runIdByMessageId, setRunIdByMessageId] = useState<Record<string, string>>({});
  const [openContextFor, setOpenContextFor] = useState<string | null>(null);
  const [contextSnapshots, setContextSnapshots] = useState<Record<string, ContextSnapshot>>({});
  const [rememberDraft, setRememberDraft] = useState<{ messageId: string; content: string } | null>(null);

  const [selectedExtraDomains, setSelectedExtraDomains] = useState<string[]>([]);
  const [sensitiveWarningAcknowledged, setSensitiveWarningAcknowledged] = useState(false);

  useEffect(() => {
    let cancelled = false;
    setError(null);
    Promise.all([fetchGeneralConversations(), fetchDomains()])
      .then(([convos, domainList]) => {
        if (cancelled) return;
        setConversations(convos);
        setDomains(domainList);
      })
      .catch(() => {
        if (!cancelled) setError("Could not load general conversations from the backend.");
      });
    return () => {
      cancelled = true;
    };
  }, []);

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
      const conversation = await createGeneralConversation(newTitle.trim() || undefined);
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

  const selectedExtraSlugs = domains.filter((d) => selectedExtraDomains.includes(d.id)).map((d) => d.slug);
  const needsSensitiveWarning = selectedExtraSlugs.some((s) => SENSITIVE_SLUGS.has(s));

  async function submitTurn(content: string): Promise<{ ok: boolean; assistantMessage: Message | null }> {
    if (!selectedConversationId) return { ok: false, assistantMessage: null };
    const idempotencyKey =
      typeof crypto.randomUUID === "function" ? crypto.randomUUID() : `${Date.now()}-${Math.random()}`;

    setSendingToJarvis(true);
    setError(null);
    try {
      const result = await sendTurn(selectedConversationId, content, idempotencyKey, selectedExtraDomains);
      setMessages((prev) => [...prev, result.user_message, ...(result.assistant_message ? [result.assistant_message] : [])]);
      if (result.context_snapshot_id && result.assistant_message) {
        setRunIdByMessageId((prev) => ({ ...prev, [result.assistant_message!.id]: result.run_id }));
      }
      if (result.status === "succeeded") {
        setLastTurnMeta({ provider: result.provider, model: result.model });
      } else if (result.error) {
        setError(`Jarvis could not respond: ${result.error.summary}`);
      }
      // Per-turn domain inclusion never persists to the next turn.
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
        // Must clear a stuck "error" state (e.g. a failed microphone
        // permission check) back to idle, not just "listening" —
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
    if (!rememberDraft) return;
    try {
      // scope: "global" — a general conversation's Remember action creates
      // a global-profile memory, never a domain-assigned one, since there
      // is no domain here to assign it to.
      await createMemory({
        scope: "global",
        kind,
        title,
        content: rememberDraft.content,
        source_message_id: rememberDraft.messageId,
      });
      setRememberDraft(null);
    } catch {
      setError("Could not save this memory.");
    }
  }

  const isBusy = saving || sendingToJarvis;
  const voiceIndicatorActive = voiceState !== "idle" && voiceState !== "error";

  return (
    <div className="domain-view general-conversation">
      <VoiceCaptureOverlay
        voiceState={voiceState}
        scope="GENERAL"
        micStream={micStream}
        ttsAudioElement={ttsAudioEl}
        errorMessage={voiceError}
        onDismiss={cancelPushToTalk}
      />
      <button type="button" className="back-button" onClick={onBack}>
        ← Back to Jarvis
      </button>

      <header className="console-header general-header">
        <MiniCoreIndicator active={voiceIndicatorActive} tone={voiceState === "error" ? "cyan" : "violet"} />
        <div className="console-header-text">
          <span className="console-eyebrow">General</span>
          <h1>Ask Jarvis anything</h1>
          <p className="console-subtitle">
            Not a domain — this conversation uses your global profile only, unless you explicitly add a domain
            below for this turn.
          </p>
        </div>
      </header>

      {error && (
        <p className="error-banner" role="alert">
          {error}
        </p>
      )}

      <div className="cockpit-layout">
        <section className="cockpit-main conversation-panel" aria-label="General conversation">
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
              {conversations.length === 0 && <li className="empty-hint">No general conversations yet.</li>}
            </ul>

            <form className="new-conversation-form" onSubmit={handleCreateConversation}>
              <label htmlFor="new-general-title" className="sr-only">
                New conversation title
              </label>
              <input
                id="new-general-title"
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

          {selectedConversationId ? (
            <section className="conversation-detail" aria-label="Messages">
              <ul className="message-list">
                {messages.map((message) => (
                  <li key={message.id} className="message-item">
                    <div className="message-role">
                      {message.role}
                      {message.model_used && <span className="message-model"> · {message.model_used}</span>}
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
                  <p>Save this as a global memory:</p>
                  <p className="message-content">{rememberDraft.content}</p>
                  <RememberForm onConfirm={handleConfirmRemember} onCancel={() => setRememberDraft(null)} />
                </div>
              )}

              <section aria-label="Push-to-talk voice" className="push-to-talk">
                <button
                  type="button"
                  className={`push-to-talk-button${voice.pushToTalkStatus === "recording" ? " recording" : ""}`}
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
                <label htmlFor="general-draft-message" className="sr-only">
                  Write a message
                </label>
                <textarea
                  id="general-draft-message"
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
                    disabled={isBusy || !draftMessage.trim() || (needsSensitiveWarning && !sensitiveWarningAcknowledged)}
                  >
                    {sendingToJarvis ? "Sending…" : "Send to Jarvis"}
                  </button>
                </div>
              </form>
            </section>
          ) : (
            <div className="empty-console-state">
              <p>Start a conversation, or open one from the list, to ask Jarvis anything.</p>
            </div>
          )}
        </section>

        <ConsoleModule title="Include a domain (this turn only)" className="cockpit-rail" ariaLabel="Include another domain">
          <p className="notice">
            By default this conversation only uses your global profile — no domain memories, records, or summaries.
            Add one below to include it for your very next turn only.
          </p>
          <div className="extra-domain-selector">
            {domains.map((d) => (
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
                You're including a sensitive domain (BODY, MIND, or PEOPLE) in this turn's context. Its memories
                will be sent to the model for this turn only.
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
          <ConsoleSectionLabel>Global memory</ConsoleSectionLabel>
          <p className="notice">Manage saved global memories in the Memory Centre.</p>
        </ConsoleModule>
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
      <input type="text" placeholder="Memory title" value={title} onChange={(e) => setTitle(e.target.value)} />
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

export default GeneralConversation;
