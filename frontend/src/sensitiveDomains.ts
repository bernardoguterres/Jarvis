/** Domains whose content triggers an explicit acknowledgement before being
 * included as extra per-turn context — from a domain conversation
 * (DomainView) or from the general Jarvis conversation
 * (GeneralConversation). Shared in one place so the two views can never
 * drift apart on which domains count as sensitive. */
export const SENSITIVE_SLUGS = new Set(["body", "mind", "people"]);
