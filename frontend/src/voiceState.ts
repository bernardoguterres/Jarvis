// Shared across every push-to-talk surface (DomainView, GeneralConversation,
// and the global capture overlay) — CLAUDE.md §8's voice states, with
// "routing"/"retrieving context" collapsed into "thinking" since the turn
// endpoint doesn't expose those sub-stages separately.
export type VoiceState = "idle" | "listening" | "transcribing" | "thinking" | "speaking" | "error";
