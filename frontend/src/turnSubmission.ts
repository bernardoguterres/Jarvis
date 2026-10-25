import type { Message } from "./api";

/**
 * Retry semantics for conversation turns, shared by the domain and general
 * conversation views. The backend treats a repeated idempotency key as
 * "the same turn": a succeeded turn is returned as saved, and a failed one
 * is retried using the user message it already saved. So a retry of the
 * same text in the same conversation must reuse the key, or the user's
 * message would be saved twice.
 */
export interface PendingTurn {
  conversationId: string;
  content: string;
  key: string;
}

export function newIdempotencyKey(): string {
  return typeof crypto.randomUUID === "function" ? crypto.randomUUID() : `${Date.now()}-${Math.random()}`;
}

/** Reuses the pending key when this is a retry of the same unfinished turn. */
export function turnForAttempt(pending: PendingTurn | null, conversationId: string, content: string): PendingTurn {
  if (pending && pending.conversationId === conversationId && pending.content === content) return pending;
  return { conversationId, content, key: newIdempotencyKey() };
}

/** Appends messages that are not already shown (a retry returns the same saved user message). */
export function mergeMessages(prev: Message[], incoming: Message[]): Message[] {
  const seen = new Set(prev.map((m) => m.id));
  return [...prev, ...incoming.filter((m) => !seen.has(m.id))];
}

export const TURN_LOST_CONTACT =
  "Lost contact with Jarvis before a reply arrived. Press Send again to retry; your message will not be saved twice.";
export const TURN_STILL_RUNNING = "Jarvis is still working on this message. Wait a moment before retrying.";

export function turnFailedMessage(summary: string): string {
  return `Jarvis could not respond: ${summary} Your message is saved; press Send again to retry.`;
}
