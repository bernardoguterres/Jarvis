# Jarvis — Product Specification

This document derives from and is subordinate to `CLAUDE.md` (the authoritative project profile). If anything here conflicts with `CLAUDE.md`, `CLAUDE.md` wins.

## 1. What Jarvis Is

Jarvis is a private, local-first, voice-controlled personal assistant for Bernardo — a genuinely used personal system, not a chatbot demo, Hermes wrapper, or portfolio piece.

One assistant, one personality, six context spaces (domains). Not six agents.

## 2. Who It's For

A single user: Bernardo. Runs primarily on his MacBook Pro M2 Pro (16 GB RAM). No multi-tenant, no accounts system, no sharing model.

## 3. The Six Domains

| # | Domain | Icon (`lucide-react`) | Covers |
|---|---|---|---|
| 1 | BODY | `Activity` | Fitness, weight, strength, training, knee symptoms, sleep, nutrition, recovery, wearables, medical prep |
| 2 | BUILD | `Boxes` | Software projects, Alpha projects, transaction foundation-model work, business ideas, coding, research, decisions |
| 3 | LIFE | `CalendarDays` | Calendar, reminders, finances, housing, travel, purchases, admin, general planning |
| 4 | MIND | `Brain` | Mood, anxiety, habits, confidence, motivation, journaling, emotional check-ins, reflection, patterns |
| 5 | PATH | `Compass` | UCL, education, career, employment, applications, interviews, skills, deadlines, long-term goals |
| 6 | PEOPLE | `UsersRound` | Romantic relationship, family, friendships, social plans, important interactions, boundaries |

The `#` column is the canonical shortcut/display number (`frontend/src/domainOrder.ts`) — identical on Home's orbital badges, a domain's own header badge, and the `1`-`6` keyboard shortcut. Each domain's icon appears as the dominant visual inside its Home node and again (same component, same icon) in that domain's own header — see `docs/DECISIONS.md` D91/D94.

Aliases route naturally (e.g. "knee" → BODY, "UCL" → PATH, "Alpha" → BUILD). Cross-domain retrieval must be explicit or clearly justified — sensitive PEOPLE/MIND content must never leak into unrelated BUILD conversations.

## 4. Core User-Facing Capabilities (V1 Definition of Done)

Jarvis is complete as an initial usable product when Bernardo can:

1. Open Jarvis locally from his Mac.
2. See the six circular domains in the HUD.
3. Select a domain via interface or speech.
4. Hold a key to talk (push-to-talk).
5. Receive a spoken and visible response.
6. Continue a domain-specific conversation across restarts.
7. Explicitly log or remember something.
8. Review, edit, archive, or delete saved information.
9. See what context and tools affected an answer.
10. Export Jarvis.
11. Restore the export into a clean installation without losing meaningful data.

Everything else (Telegram, email, external memory providers, sub-agents, always-on hosting) is a later capability — explicitly out of scope for V1. Google Calendar/Health read (plus limited, approval-gated Calendar write), the animated HUD (Phase 6, cinematic core and orbital motion — see `ARCHITECTURE.md` §9f), the general Jarvis conversation entry point, the shared internal-console design system (§9h, D75), a truthful diagnostic-fault system for 404/controller-offline/Hermes-degraded/interface-crash/module-level failures (§9i, D77), a real audio-reactive voice waveform for listening and speaking (§9i, D78), global push-to-talk with a deterministic three-tier command hierarchy reachable from Home, every Centre page, and every conversation (§9j, D79), a concise, deterministic, source-backed situational briefing on Home (Phase 12A, §15, D86), that briefing's continuity — deterministic new/changed/ongoing/resolved/reopened tracking plus local acknowledge/snooze (Phase 12B, §16, D87) — a small, user-owned Mission Focus watchlist referencing existing sources (Phase 12C, §17, D88), Mission Control's single, persisted, timed Current Mission focus session built on that same shared machinery (§18, D95), a Recall Centre for deterministic local search across every domain (Phase 12D, §19, D98), a Research Centre for evidence collection and cited briefs built on that same Recall search (Phase 12E, §20, D99), and a Decision Room for transparent, evidence-grounded decisions built on Recall and Research (Phase 12F, §21, D101) are implemented; real-Mac voice hardware acceptance is complete (Bernardo personally performed a real push-to-talk question and a real confirm-required voice command — D103), a full VoiceOver pass is deliberately deferred to installed-app acceptance after native macOS packaging, and genuine 1280×800/1024×768/820×900 viewport inspection remains outstanding (see `ROADMAP.md`'s consolidated real-Mac checklist).

## 5. Interaction Model

* **Voice**: explicit push-to-talk only, never continuous listening by default. Hold Space to record, release to transcribe and submit.
* **Keyboard**: Control+Option+J opens/focuses Jarvis; keys 1–6 select domains; Command+K opens command palette; Command+Shift+E exports; Escape cancels/returns to HUD.
* **HUD**: central Jarvis core with six circular domains around it. Selecting a domain zooms/focuses it, surfaces its conversation and real data, and the central element reflects voice/processing state (idle, listening, transcribing, routing, retrieving context, thinking, speaking, error). The core itself is also a real interactive control — click, or Enter/Space while it's keyboard-focused, opens a **general Jarvis conversation** (accessible name "Talk to Jarvis"): a genuine, persisted conversation scope with no domain assigned, not a seventh domain (see `ARCHITECTURE.md` §9h, D75). It uses only the global profile by default — no domain memories, records, or summaries are auto-retrieved — with the same six domain-checkbox context selector (and BODY/MIND/PEOPLE sensitivity warning) domain conversations use, for explicit single-turn inclusion only.
* Each domain supports three interaction modes: **TALK**, **TRACK**, **PLAN**.
* **Interface commands** (typed via the command palette, or spoken): a fixed, deterministic, model-independent set of navigation phrases (domain/centre names and their natural aliases, "go home," "go back") execute immediately without involving Hermes or any model. A command naming a specific sensitive control (e.g. an integration's connect/disconnect/automatic-sync control) only navigates to it and highlights it — Jarvis never activates a mutating or externally-reaching control from a spoken or typed instruction alone; that always requires the user's own explicit click.

No decorative or fake activity indicators — every HUD status must reflect real application state. The HUD must be usable without animation and respect reduced-motion preferences.

Home also shows a concise, deterministic **situational briefing** (Phase 12A) below the orbit: up to five NOW/NEXT/WATCH items assembled locally from Calendar, LIFE/PATH/BUILD records, pending/failed actions, and integration/routine health — BODY (Google Health) only when explicitly opted in, MIND and PEOPLE never. It is never generated, ranked, or summarized by a model; every item carries a real source reference, and a genuinely empty result says "No immediate items" rather than inventing advice. Clicking an item navigates to its domain or Centre; "Discuss with Jarvis" is the only way this feature can reach a model.

The briefing has memory of its own state across visits (Phase 12B): each item also shows a real NEW/CHANGED/ONGOING/RESOLVED/REOPENED status, computed deterministically against what was shown before — never repeating the exact same picture forever, and never inventing a change that didn't happen. Bernardo can **Acknowledge** an item (hide this exact version from the briefing — never marks the underlying task/event/action/sync as done) or **Snooze** it for a fixed duration (1 hour, 4 hours, until tomorrow morning, or 1 week); either is automatically undone the moment the item's underlying facts genuinely change, and both are visible and reversible in a compact "Acknowledged & snoozed" history.

Below the briefing, Home also shows a small **Mission Focus** watchlist (Phase 12C) — at most five things Bernardo has explicitly chosen to prioritize, each a typed reference to a real existing LIFE task, PATH deadline, BUILD checkpoint, selected Calendar event, or unresolved action proposal (never a copy of it, never a free-form note, never something Jarvis picks on its own). Each pin shows its rank, a concise source label, domain, Bernardo's own written next action, an optional target date and blocker, and a truthful availability/resolution note if the source has changed or disappeared. "Add to Mission Focus" appears on each eligible source's own screen (LIFE/PATH/BUILD records, Actions Centre, Integrations Centre's Calendar events); "Remove from focus" never deletes, completes, or archives the underlying item. "Discuss Mission Focus with Jarvis" is the only way this feature can reach a model.

Home also offers **Mission Control** — one persisted, timed "Current Mission" at a time, answering "what should I do now?" With no mission active, it shows a suggested candidate (drawn from the exact same briefing data as above, with the same "Suggested from current information" phrasing — never a claim about what actually matters most) plus up to two alternatives and Start controls, or a free-text entry with an explicit domain choice and a 25/45/60-minute preset (or a bounded 5-180 minute custom duration). Once started, Home shows the mission's title, domain, elapsed and target time, and its source, with Pause/Resume/Complete/Abandon controls; completing offers an optional short completion note and an optional "what changed?" note. The timer is always derived from real timestamps, not a countdown that could drift, and survives an ordinary restart accurately. Ending a mission never marks its underlying Calendar event, task, or record as done — those remain separate, and any such change still goes through their own existing path. The same seven controls (start/pause/resume/complete/abandon, plus showing the current mission or its history) are reachable by voice or the command palette as safe, immediate, local actions — never requiring confirmation, since none of them ever reach Calendar, memory, Health, or Hermes. "Discuss with Jarvis" remains the only way Mission Control itself can reach a model.

A **Recall Centre**, reachable from the Systems menu, the command palette, or a keyboard shortcut, gives Bernardo one fast, local place to search everything Jarvis has stored — conversations, memories, structured records, domain summaries, imported documents, cached Calendar events, action proposals, routine history, and Mission Control sessions — and open the exact underlying item. This is deterministic local search, never a model feature: it never calls Hermes, never summarizes or infers anything, and never treats retrieved text as an instruction, no matter what that text says. Every result shows its title, a highlighted snippet, its domain (or an explicit "global" label when nothing owns it), its source type, and how fresh it is; a source that has since been deleted or archived is shown truthfully as unavailable rather than silently vanishing or being replaced with invented content. By default, Recall searches only LIFE, PATH, and BUILD — BODY, MIND, and PEOPLE must be explicitly included, and opening Recall from inside a domain searches only that domain by default. Results are ranked by one fixed, documented rule (text relevance, exact-phrase match, domain match, a small bounded recency nudge, then a stable tie-break) — never anything that could change unpredictably between identical searches.

A **Research Centre**, reachable the same way (Systems menu, command palette, or a spoken/typed "open research"), lets Bernardo build a named research workspace around a question or topic, find evidence through Recall (including passages from imported documents), add exactly the items he selects, classify each as supporting, contradicting, contextual, or unresolved, attach his own notes, and generate a cited brief from only that selected evidence — either a deterministic evidence outline (always available, no model involved) or, on explicit request, one bounded "Draft with Jarvis" model pass. This is research over Jarvis's own local corpus, never unrestricted web research or an autonomous agent: a spoken or typed research-sounding phrase only ever opens the Centre, never creates a workspace, adds evidence, or generates a brief on its own. Every citation in a brief is a stable number the server itself validates against the workspace's actual evidence — an invalid or hallucinated citation is rejected or clearly flagged, never presented as real support for a claim — and every citation can be followed back to its original source, with a since-removed or archived source shown truthfully as unavailable rather than silently vanishing from a past brief. A workspace's evidence follows the identical LIFE/PATH/BUILD-by-default domain boundary Recall itself uses; BODY/MIND/PEOPLE evidence only ever enters a workspace whose domain policy explicitly names it. Regenerating a brief always adds a new version rather than overwriting the last one, so Bernardo can always see exactly which sources supported an earlier statement.

A **Decision Room**, reachable the same way (Systems menu, command palette, or a spoken/typed "decision room"/"open decisions"), completes Recall → Research → Decide → Focus. Bernardo defines a decision, adds options with their benefits/costs/risks, weighs criteria (1-5 importance), scores each option against each criterion, and links evidence found through Recall — optionally scoping that evidence to one linked Research workspace, in which case only domains both the decision and the workspace allow are ever searched. The score is a plain, transparent weighted sum shown alongside the exact breakdown that produced it — never a hidden formula or a claim of objective truth — and Jarvis flags a tied result or a ranking that depends heavily on a single criterion's weight rather than presenting either as decisive. Bernardo can track assumptions, risks, and unknowns alongside the decision, generate a deterministic brief with no model involved, and — on explicit request — ask Jarvis to challenge the decision: exactly one bounded critique with its own citations, clearly labeled as Jarvis's own generated text and never able to decide anything itself. Only Bernardo's own explicit action ever records a final decision (the chosen option, his rationale, and his confidence); Jarvis never finalizes or executes a decision on its own initiative. Afterward, Bernardo can add an outcome review — what actually happened, and whether his confidence was appropriate — without ever altering the original decision record, and once enough decisions have been reviewed, Jarvis shows a plain calibration summary (e.g. how often he'd decide the same way again).

## 6. Memory as a Product Feature

Memory is a first-class, user-visible feature, not an implementation detail:

* "Log this" → explicit structured record.
* "Remember this" → explicit long-term memory.
* "Forget this" → archive or delete, per sensitivity and confirmation rules.
* Ordinary conversation is stored in history but not auto-promoted to permanent memory.
* Jarvis may propose a memory and ask for approval.
* All stored information must be visible, editable, exportable, and deletable by Bernardo.
* Deletions/edits use versioning or tombstones by default — not silent destruction — unless Bernardo explicitly requests permanent deletion.

Memory must survive a change of reasoning model (Claude → DeepSeek → OpenAI, etc.) without loss or invalidation.

## 7. Portability as a Product Feature

Bernardo must be able to export the full Jarvis state and restore it into a clean install on a different machine without losing meaningful data. This is a mandatory, tested capability (round-trip restoration test), not an aspiration — see `ARCHITECTURE.md` §5–6 for mechanics.

## 8. Non-Goals for V1

* Not a multi-user or hosted product.
* Not a general chatbot with no persistent state.
* Not six independent assistants.
* No continuous ambient listening.
* No email/calendar write access.
* No cloud-hosted personal data store.
* No local LLM, no Kubernetes, no microservices, no Docker/VPS.
