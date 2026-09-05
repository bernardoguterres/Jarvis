# Jarvis - Product Specification

Subordinate to `CLAUDE.md`. If anything here conflicts with it, `CLAUDE.md` wins.

## 1. What Jarvis is

A private, local-first, voice-controlled personal assistant for Bernardo, meant for genuine daily use, not a chatbot demo or portfolio piece. One assistant, one personality, six context spaces. Not six agents.

## 2. Who it's for

A single user: Bernardo, on his MacBook Pro M2 Pro (16 GB RAM). No multi-tenant model, no accounts system, no sharing.

## 3. The six domains

| # | Domain | Icon (`lucide-react`) | Covers |
|---|---|---|---|
| 1 | BODY | `Activity` | Fitness, weight, strength, training, knee symptoms, sleep, nutrition, recovery, wearables, medical prep |
| 2 | BUILD | `Boxes` | Software projects, coding, research, technical decisions |
| 3 | LIFE | `CalendarDays` | Calendar, reminders, finances, housing, travel, purchases, admin |
| 4 | MIND | `Brain` | Mood, anxiety, habits, confidence, motivation, journaling, reflection |
| 5 | PATH | `Compass` | Education, career, applications, interviews, deadlines, long-term goals |
| 6 | PEOPLE | `UsersRound` | Relationship, family, friendships, social plans, boundaries |

The `#` column is the one authoritative shortcut/display number (`frontend/src/domainOrder.ts`), identical on Home's orbital badges, a domain's own header badge, and the `1`-`6` keyboard shortcuts. Aliases route naturally ("knee" to BODY, "career" to PATH). Cross-domain retrieval must be explicit; sensitive PEOPLE/MIND content must never leak into an unrelated BUILD conversation.

## 4. V1 definition of done

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

All eleven are met. On top of that baseline, V1 also ships: Google Calendar/Health integrations (read, plus limited approval-gated Calendar write), the full animated HUD, a general Jarvis conversation entry point, a deterministic local command layer, a truthful diagnostic system for every real failure state, a real audio-reactive voice waveform, the Home situational briefing with continuity/acknowledge/snooze, Mission Focus, Mission Control, Recall, Research, and Decision Room. See `docs/ARCHITECTURE.md` for how each works and `docs/ROADMAP.md` for status.

Telegram, email integration, external memory providers, sub-agents, and always-on hosting remain out of scope. A full VoiceOver pass and real-viewport inspection remain outstanding against the installed native app (see `docs/ROADMAP.md`).

## 5. Interaction model

* **Voice**: explicit push-to-talk only, never continuous listening. Hold Space to record, release to transcribe and submit.
* **Keyboard**: Control+Option+J opens/focuses Jarvis; keys 1-6 select domains; Command+K opens the command palette; Command+Shift+E exports; Escape cancels or returns to the HUD.
* **HUD**: a central Jarvis core with six circular domains around it. Selecting a domain zooms into it and surfaces its conversation and real data; the core reflects voice/processing state (idle, listening, transcribing, thinking, speaking, error). The core itself is also a control: clicking it, or Enter/Space while focused, opens a general Jarvis conversation, a real persisted scope with no domain assigned, not a seventh domain. It uses the global profile by default, with the same optional per-turn domain chips a domain conversation uses for explicit cross-domain inclusion.
* Each domain supports three modes: **TALK**, **TRACK**, **PLAN**.
* **Commands** (typed or spoken): a fixed, deterministic set of navigation phrases executes immediately, with no model involved. A command naming a sensitive control (an integration's connect/disconnect toggle, say) only navigates to and highlights it. Jarvis never activates a mutating or externally-reaching control from a spoken or typed instruction alone; that always requires an explicit click.

No decorative or fake activity indicators; every HUD status reflects real application state. The HUD is usable without animation and respects reduced-motion preferences.

**Situational briefing**: Home shows a concise NOW/NEXT/WATCH view, up to five items, assembled locally from Calendar, LIFE/PATH/BUILD records, pending actions, and integration/routine health. BODY (Google Health) appears only when explicitly opted in; MIND and PEOPLE never appear. It's never generated or summarized by a model; every item carries a real source reference, and a genuinely empty result says so plainly. Clicking an item navigates to it; "Discuss with Jarvis" is the only way this feature reaches a model.

Each item also tracks its own state across visits (new, changed, ongoing, resolved, reopened), computed deterministically rather than repeating the same picture forever. Bernardo can acknowledge an item (hide this exact version, never marks the underlying task as done) or snooze it for a fixed duration; either is automatically undone the moment the item's real facts change, and both remain visible and reversible in a compact history.

**Mission Focus**: a watchlist of at most five things Bernardo has explicitly chosen to prioritize, each a typed reference to a real existing LIFE task, PATH deadline, BUILD checkpoint, Calendar event, or action proposal, never a copy and never something Jarvis picks on its own. "Add to Mission Focus" appears on each eligible source's own screen; removing a pin never deletes or completes the underlying item.

**Mission Control**: one persisted, timed "Current Mission" at a time. With none active, Home shows a suggested candidate (drawn from the same briefing data, labeled "Suggested," never a claim of what matters most) plus a free-text option with an explicit domain and duration. Once started, Home shows title, domain, elapsed/target time, and source, with Pause/Resume/Complete/Abandon controls. The timer is derived from real timestamps, never a client-side countdown, and survives an ordinary restart accurately. Ending a mission never marks its underlying source as done. The same controls are reachable by voice or the palette as immediate local actions, since none of them touch Calendar, memory, Health, or Hermes.

**Recall Centre**: one fast, local place to search everything Jarvis has stored (conversations, memories, records, summaries, documents, cached Calendar events, action proposals, routine history, Mission Control sessions) and open the exact source. Deterministic local search only: never calls a model, never summarizes or infers, never treats retrieved text as an instruction. By default it searches only LIFE, PATH, and BUILD; BODY/MIND/PEOPLE must be explicitly included. A deleted or archived source is shown truthfully as unavailable, never silently dropped or replaced with invented content.

**Research Centre**: builds a named workspace around a question, finds evidence through Recall, lets Bernardo select and classify it (supporting, contradicting, contextual, unresolved), attach notes, and generate a cited brief, either a deterministic outline or, on explicit request, one bounded "Draft with Jarvis" pass. Never unrestricted web research or an autonomous agent; a research-sounding phrase only opens the Centre, never creates a workspace or a brief on its own. Every citation is a stable number the server validates against the workspace's actual evidence; an invalid citation is flagged, never presented as real support. Regenerating a brief always adds a new version rather than overwriting the last one.

**Decision Room**: completes Recall to Research to Decide to Focus. Bernardo defines a decision, adds options and weighted criteria, scores each pair, and links evidence found through Recall (optionally scoped to one linked Research workspace). The score is a plain, transparent weighted sum shown with its full breakdown; a tied result or one driven by a single criterion is flagged rather than presented as decisive. Bernardo can track assumptions, risks, and unknowns, generate a deterministic brief, and optionally ask Jarvis to challenge the decision with one bounded, cited critique that can never itself decide anything. Only Bernardo's own explicit action records a final decision. An outcome review afterward never alters the original record, and a calibration summary appears only once enough decisions have been reviewed to mean something.

## 6. Memory as a product feature

Memory is user-visible, not an implementation detail:

* "Log this" creates an explicit structured record.
* "Remember this" creates an explicit long-term memory.
* "Forget this" archives or deletes, per sensitivity and confirmation rules.
* Ordinary conversation is stored in history but never auto-promoted to permanent memory.
* Jarvis may propose a memory and ask for approval.
* All stored information is visible, editable, exportable, and deletable by Bernardo.
* Edits and deletions use versioning or tombstones by default, never silent destruction, unless Bernardo explicitly requests permanent deletion.

Memory must survive a change of reasoning model without loss or invalidation.

## 7. Portability as a product feature

Bernardo must be able to export the full Jarvis state and restore it into a clean install on a different machine without losing meaningful data. This is a mandatory, tested capability (a round-trip restoration test), not an aspiration. See `docs/ARCHITECTURE.md` §5.

## 8. Non-goals for V1

* Not a multi-user or hosted product.
* Not a general chatbot with no persistent state.
* Not six independent assistants.
* No continuous ambient listening.
* No email or calendar write access beyond the limited, approval-gated Calendar writes above.
* No cloud-hosted personal data store.
* No local LLM, Kubernetes, microservices, Docker, or VPS.
