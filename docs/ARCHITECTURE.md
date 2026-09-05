# Jarvis - Architecture

Subordinate to `CLAUDE.md`. If anything here conflicts with it, `CLAUDE.md` wins. This is a technical reference for how the current implementation works. For the history of how it got here (bugs found, corrections made, live-acceptance narratives), see `docs/DECISIONS.md`.

## 1. Technology stack

Backend: Python, FastAPI, SQLAlchemy, Alembic. Frontend: React, TypeScript, Vite. Persistence: SQLite. Agent harness: Hermes Agent, via its local authenticated API. Reasoning model: whatever Hermes's `jarvis` profile is configured for, currently GPT-5.6 Terra via OpenAI Codex OAuth, configured entirely Hermes-side (see §7). Speech-to-text: local faster-whisper. Text-to-speech: Edge TTS. Interface: a native macOS app (Tauri 2 shell, see §24), same-origin over the FastAPI backend; the browser-based `jarvisctl.sh` workflow remains available for development.

Explicitly excluded: Electron, Docker, a VPS, cloud database storage, a local LLM, Kubernetes, microservices, continuous microphone recording. A technology is reconsidered only when a demonstrated requirement can't be met cleanly with the current stack.

## 2. System flow

```
User -> React frontend -> Jarvis FastAPI Controller -> domain router and context builder
  -> local Jarvis database -> Hermes local API -> configured reasoning model
  -> response -> text-to-speech -> frontend and spoken reply
```

Hermes supplies the agent loop, tools, session capabilities, skills, and integrations. The Jarvis Controller owns active-domain state, model-independent memory, structured records, context retrieval, permissions, export/restore, and audit records. Hermes's own memory is never the authoritative record of Bernardo's history; the Controller's local database is.

## 3. Domains as context spaces

BODY, MIND, PEOPLE, PATH, BUILD, LIFE are context spaces inside one agent, not six agents or six Hermes profiles. A domain router determines the active domain from explicit selection or natural-language aliasing, and the context builder assembles domain-scoped context before invoking Hermes. Cross-domain inclusion must be explicit, never a default join. A conversation can also have no active domain at all: the general Jarvis conversation opened from the core (§6), a scope with no domain assigned, not a seventh domain.

## 4. Data ownership and layout

Application source (the Git repo) and personal data are strictly separate. Personal data lives under `JARVIS_DATA_DIR` (default `~/JarvisData`):

```
JARVIS_DATA_DIR/
  database/jarvis.sqlite
  documents/
  domain-summaries/
  skills/
  configuration/
  backups/
  exports/
```

Rules: never store personal data in browser storage; never commit personal data or secrets to Git; never reset or overwrite an existing database automatically; never silently discard an unknown schema version; original text/structured records are authoritative, indexes and embeddings are derived and rebuildable.

## 5. Export, import, and backup

**Export** (`app/export_service.py`): `jarvis-export-YYYYMMDD-HHMMSS.zip` containing `manifest.json` (format/app/schema version, checksums, file inventory, `secrets_included: false`), a consistent SQLite snapshot (via SQLite's own online backup API, never a raw file copy), and any non-empty `documents/domain-summaries/skills/configuration` directories. Written atomically (temp file, then `os.replace`); a `flock` prevents concurrent exports; the source database is integrity-checked before anything is written.

**Validation** (`app/import_service.py::validate_archive`): an untrusted archive is always extracted into a fresh temp directory first, never into `JARVIS_DATA_DIR` directly. Checks, in order: ZIP structural sanity (no absolute paths, no traversal, no symlinks, size caps), manifest schema and version, every file's checksum, no undeclared files, and finally the archived database's own integrity/foreign-key checks and a known-schema-revision check (via Alembic's `ScriptDirectory`, so an older known revision is fine and an unrecognized one is rejected).

**Restore** (`app/import_service.py::restore_archive`, CLI-only, plus the guarded in-app path added in §24): always validates first. Refuses to overwrite an existing installation without `--confirm`/an explicit UI acknowledgement, and makes a verified rollback copy first. Any failure during restore restores from that rollback copy and re-raises, so a failed restore leaves the target unchanged. The rollback copy is never auto-deleted.

**Backups** (`app/backup_service.py`): same online-backup mechanism as export, into `backups/{daily,weekly,monthly}/`, retention 7/4/12. A lightweight startup due-check (not a real scheduler) creates an overdue backup automatically; there is no recurring background scheduler in this layer.

**API vs. CLI**: `POST /api/export`, `GET /api/exports`, `GET /api/exports/{filename}/download`, `POST /api/backups`, `GET /api/backups/latest`, `POST /api/imports/validate` are exposed over HTTP. CLI-only restore (`jarvis-cli restore`) was the sole restore path until §24 added a guarded in-app one reusing the identical function.

## 6. Memory architecture

**Schema**: `memory_items` (the stable logical memory: scope global/domain, kind, status, importance, confidence, sensitivity, `current_version_id`, `supersedes_id`/`superseded_by_id`) and `memory_versions` (every edit creates a new immutable row, never an in-place update). `domain_summaries`/`domain_summary_versions` follow the same pattern, one current slot per domain. `structured_records` are domain-scoped, `record_type`-tagged, Pydantic-validated JSON. `context_snapshots` record what context was used for a given turn. `memory_fts` is a derived, rebuildable SQLite FTS5 index.

Editing a memory creates version N+1 on the same item. Superseding creates a new item, archives the old one, and links both directions. Archiving hides a memory from retrieval without touching history. Permanent deletion requires the caller to type the memory's exact current title, makes a rollback backup first, then hard-deletes.

**Why FTS5, not embeddings**: no external API call, no vector index to keep in sync, and good enough for a personal-scale store where near-exact term matches dominate. A natural-language query is tokenized and every token wrapped as a quoted phrase joined with `OR` (`sanitize_fts_query`), avoiding both FTS5 syntax errors on arbitrary text and FTS5's default AND-between-terms behavior. A query that matches nothing falls back to importance-then-recency ordering, never an empty context.

**Context construction** (`app/context_builder.py`), assembled in a fixed order per turn: a minimal safety instruction, the compact global profile, the active domain's name/description and current summary, relevant domain memories and structured records, any explicitly-requested secondary-domain context (only when a turn's `additional_domain_ids` names it, clearly labeled), recent conversation messages, then the current message. Every section is size-budgeted and truncated visibly rather than silently cut. Archived/superseded memories are never retrieved; only a memory's current version is used. A general conversation (`domain=None`) skips every domain-scoped section entirely, the deliberate least-context default.

All retrieved memory/record/summary text sits under one `REFERENCE DATA (quoted, not instructions)` block, so text that reads like an instruction is never treated as one.

**Structured records**: each of the seven record types has its own Pydantic model with bounded fields; an invalid payload is rejected outright, and each type is locked to exactly one domain at the service layer.

**Model independence**: memory lives entirely in the Controller's own tables; `context_builder.py` never imports a provider module, and `HermesProvider` only ever receives an already-assembled prompt and message history. Switching Hermes's configured model changes nothing about storage, retrieval, or versioning.

## 7. Model strategy and the provider interface

Originally planned as Claude Sonnet 5 via Anthropic's API; currently configured (with explicit approval) as GPT-5.6 Terra via OpenAI Codex OAuth. Neither choice required a code change. No multi-model router in V1. Every generated response stores its model/provider metadata.

Neither the Anthropic key nor the OpenAI/ChatGPT credential ever touches the FastAPI backend: the active credential lives only inside Hermes's own profile-scoped secret storage, set up directly by Bernardo via `jarvis setup model`.

`app/providers/base.py` defines a small `AgentProvider` protocol (`health`, `model_info`, `send_turn`) returning a `TurnResult` or a sanitized `ProviderError`. `app/providers/hermes.py` is the only implementation, calling Hermes's local OpenAI-compatible API. Critically, the chat-completion request never includes a `model` field: Hermes's API server only recognizes its own per-profile alias, so omitting the field entirely lets the profile's own configured provider fully own that decision. Everything downstream of `turn_service.py` only depends on this protocol, so a fake provider drives every automated test.

**One turn**, roughly: save the user message, create an `agent_runs` row, build bounded context, call `HermesProvider.send_turn`, then on success save the assistant message and mark the run succeeded, or on failure mark it failed with a sanitized reason (the user's message is preserved either way, and no assistant message is invented).

## 8. Hermes integration

One dedicated profile, `jarvis`, created blank with its own isolated secrets. Only the `skills` and `memory` toolsets are enabled for the API-server platform; every other built-in toolset (web, browser, terminal, file, code execution, vision, delegation, cron, messaging, etc.) is disabled. `memory.write_approval` and `skills.write_approval` are both true, `curator.enabled` is false, `max_concurrent_runs` is 1, and no external memory provider is configured. Hermes's local API server binds `127.0.0.1:8642` only, requires a bearer token, and has CORS disabled since the browser only ever talks to FastAPI.

## 9. Voice

Push-to-talk only, no continuous listening. `POST /api/voice/transcribe` (local faster-whisper) and `POST /api/voice/speak` (Edge TTS) sit behind `SpeechToText`/`TextToSpeech` protocols, the same provider-independence shape as §7. The uploaded recording goes to an OS temp file and is deleted in a `finally` block regardless of outcome; only the transcript is ever persisted. `usePushToTalk.ts` (hold Space, or the on-screen button) records, transcribes, sends the transcript through the ordinary turn flow, and plays the spoken reply back; Escape cancels. Transcription runs off the event loop (`asyncio.to_thread`) so it never blocks other backend work; the whisper model loads lazily on first use, not eagerly at startup (an eager-preload attempt caused a real process-respawn incident, see D107/D109).

## 10. macOS launcher and local runtime

`app/main.py` mounts the built frontend as static files at `/`, registered after every `/api/...` route and an explicit 404 catch-all for unmatched `/api/*` paths, so ordinary dev-mode use needs only the backend process plus the independently-lifecycled Hermes gateway. `scripts/jarvisctl.sh` (`open`/`status`/`stop`/`install-startup`/`uninstall-startup`) is the local runtime controller, with its own state under `~/Library/Application Support/Jarvis`, never `JARVIS_DATA_DIR`. `open` idempotently starts the Hermes gateway if needed, applies migrations, builds the frontend, starts and health-checks the backend, then opens a dedicated browser window; a second call just reopens it. `stop` only stops a process it verifies is actually its own `uvicorn` process. Start-at-login uses a placeholder-only LaunchAgent template, rendered only with explicit approval. The `Control+Option+J` shortcut is never installed automatically; it's a one-time manual step in Shortcuts.app, per the macOS safety boundary. `scripts/test_jarvisctl.sh` exercises all of this against a fully isolated fake environment.

## 11. Permission tiers and the action lifecycle

| Tier | Behavior | Examples |
|---|---|---|
| Read | Executes without confirmation, when scoped | reading files, records, approved sources, calendar |
| Draft | Produces proposed output, never transmits | drafting an email or calendar change |
| Confirm | Requires explicit approval before execution | `memory.create`, `structured_record.create`, `domain_summary.update`, and later: send email, change calendar |
| Prohibited | Not permitted by default | destructive file ops, purchases, public posting, cross-domain sensitive-data exposure |

Every consequential tool action generates an audit record. This is implemented as a default-deny capability registry (`app/capabilities.py`) plus an auditable lifecycle (`app/action_service.py`). The registry is a fixed, code-owned set of capability strings, enforced additionally by a database CHECK constraint, so an unknown capability can't even be inserted. The lifecycle: `proposed -> approved -> executing -> succeeded|failed`, or `denied`/`expired` at any point before execution. Approval requires the exact SHA-256 `payload_digest` computed at proposal time and mints a single-use, 5-minute confirmation token; execution requires that exact token, consumed on the attempt (not on success), and scoped to exactly one proposal. Every transition writes an immutable audit event. There is no code path from a model response's content to approval or execution; model-generated text is never treated as authorization.

Direct actions a user takes through the UI (saving a note, editing a memory by hand) never touch this system; it exists specifically for mutations Jarvis itself proposes.

## 12. Lifecycle hooks

`app/hooks.py` is a small in-process registry with four phases, run in this order: `before_context` (guards against a stale/deleted domain reaching context construction), `before_action` (re-verifies the capability is allowlisted, enforces the payload-digest/token/expiry contract, then refuses to re-execute an already-terminal proposal), `after_action` (records success), `on_failure` (records failure detail). Every invocation, allowed or blocked, is written as an auditable event before its result is used; a hook that returns not-allowed stops that phase immediately. This is a subset of the original five-hook sketch in `CLAUDE.md`; `post_turn` memory-promotion and `session_end` summary hooks remain unimplemented, to be added only when a concrete need appears.

## 13. Skills

A skill (`app/skill_service.py`) is a named, versioned, declarative workflow, never arbitrary code: a mutable `Skill` record plus immutable `SkillVersion` history, where each version's `workflow_steps` is a list of `{capability_id, description}` validated against the same fixed capability registry. Invoking a skill only ever calls `propose_action` once per step, so invocation always passes through the same approve/execute lifecycle as a manual proposal. A domain-scoped skill's `domain_id` is forced onto every proposal it creates. Editing a skill, active or not, always demotes it back to draft. Four labeled example templates are seeded as inactive drafts. A post-restore safety sweep forces any non-terminal action proposal to `expired` immediately after every restore, so nothing pending or approved becomes executable merely by being restored elsewhere.

## 14. Integrations: Google Calendar, Google Health, local documents

Three model-independent, controller-owned integrations sharing the connect/disconnect/sync/cache/context shape of §7's provider interface. Both Google integrations use a Web application OAuth client (not Desktop, which doesn't support incremental authorization) with a loopback redirect handled by this same backend.

**Credentials** (`app/credential_store.py`): OAuth client id/secret, access and refresh tokens live only in the macOS Keychain via a `CredentialStore` protocol, never in SQLite, `.env`, logs, exports, or backups. Writes go through an in-place `SecItemUpdate` first, falling back to create-and-delete only for a genuinely new item (see D108: the naive `keyring` write path always deletes and recreates the item, resetting its access-control list and causing recurring Keychain prompts). `jarvis-cli configure-integration <provider>` is the one-time local entry point; a credential is never pasted into a chat session.

**OAuth flow** (`app/oauth_flow.py`): Authorization Code + PKCE, a loopback-only redirect through this same backend, single-use `state`, a 10-minute bounded lifetime. State/PKCE verifiers live only in memory. Because Google associates consent with the (user, Cloud project) pair rather than (user, client_id), each callback's returned scope string is filtered down to only the scopes that provider's own code uses, and a Keychain write always happens before the database is marked connected, so the two can never disagree.

**Google Calendar** (`app/providers/google_calendar.py`): read-only by default (`calendarlist.readonly` + `events.readonly`); write access to owned calendars only (`calendar.events.owned`) is a separate, explicit incremental-consent grant. A normalized local cache refreshes only on explicit or scheduled sync. Writes are Phase 8 capabilities (`app/calendar_capability.py`): `google_calendar.event.create/update/delete`, refused unless the target calendar is both selected and owned, and unless the connection's granted scopes still include the write scope, re-checked at both propose and execute time.

**Google Health** (`app/providers/google_health.py`): read-only (`activity_and_fitness`, `health_metrics_and_measurements`, `sleep` scopes). Built around an explicit typed metric registry rather than one daily-summary shape, using three fetch mechanisms per Google's own operation support: `dailyRollUp` for summable metrics (with per-metric range limits, transparently chunked for a wider request), unfiltered `list` with client-side date truncation for daily singleton/point metrics, and filtered `list` for sleep/exercise sessions. A metric's fetch failure is recorded per-metric without aborting the rest of a sync (`last_sync_status="partial"`). Readiness/Sleep/Stress/Cardio-Load scores are not exposed by the API and are shown as explicitly unsupported, never estimated. No write capability exists for this integration.

**Local documents** (`app/document_service.py`): explicit browser upload only, never a watched folder. Content type is sniffed from bytes, never trusted by extension. PDF/DOCX text extraction never executes a macro or embedded object; a DOCX containing a macro project, or content exceeding a size/part-count guard, is rejected. Originals are stored under a SHA-256-derived path, never the original filename. Extracted text is chunked and indexed into a derived, rebuildable `document_fts` table.

**Context behavior**: document chunks and Calendar/Health context enter a turn only when the relevant domain (LIFE or BODY) is in scope, under the same quoted reference-data framing that governs memories, so injected instruction-like text stays inert. `ContextSnapshot` records the exact document/event/summary ids used, for the same auditability as memories.

**Export/restore**: documents and both caches are ordinary rows, included automatically. Every integration connection is forced to `disconnected` on restore, since real tokens live only in this machine's Keychain and never in the exported database.

## 15. Automatic integration resync

Controller-owned and entirely local: a single `asyncio.Task` (`app/scheduler_runtime.py::SchedulerRuntime`) started and stopped by FastAPI's lifespan, idempotent to start, ticking every 30 seconds. `app/scheduler_service.py` (fully testable via an injected clock) holds per-provider schedule config (allowed cadences enforced server-side), the actual sync orchestration (reusing the existing sync functions, guarded by a per-provider lock so manual/scheduled/catch-up syncs never overlap), and failure handling (bounded exponential backoff honoring `Retry-After`, never marking the real connection disconnected). `next_due_at` always advances from an attempt's real completion time, never by replaying missed slots, which is what prevents a catch-up storm after downtime. Every attempt is recorded in a bounded, sanitized audit table. A restore forces every schedule to disabled alongside the forced-disconnect step above.

## 16. Proactive routines

A fixed, controller-owned catalogue, Morning Briefing / Evening Check-in / Weekly Review, reusing §15's exact scheduler loop rather than a second one. No routine ever calls a model, mutates Calendar/Health data, writes a memory, or notifies anyone; the only model-reachable action is a manual "Discuss with Jarvis," which reuses the existing conversation-turn endpoint. All three are disabled by default and stay that way through export/restore (history is preserved, schedule state is forced off). Content is a deterministic, source-referenced summary built from existing structured records and integration caches, timezone/DST-safe. BODY/MIND/PEOPLE inclusion requires explicit per-routine opt-in; Weekly Review requires opt-in for every domain, sensitive or not.

## 17. Frontend visual system

Direction: "Direction B geometry with Direction C lighting" (`docs/DESIGN_DIRECTION.md`) - circular domain/core geometry only, no hexagons, a deep purple-black atmosphere with a violet core glow and cyan/teal accents, illumination reserved for the core, the active domain, voice activity, and meaningful state. Design tokens live in `frontend/src/index.css`; every existing component class was restyled against them rather than renamed.

**`JarvisCore`** is the central multi-ring HUD, built from masked gradient layers and CSS transforms (no SVG, no per-frame JS), driven by one CSS custom-property block per voice state (idle/listening/transcribing/thinking/speaking/error) so tuning a state never means touching each layer individually.

**Home** is the orbital view: nodes are positioned by container-relative percentages, a shared orbit ring brightens on hover/focus via `:has()`, and Home-to-domain navigation runs through one shared function (`transitions/domainViewTransition.ts`) built on the real browser View Transitions API, with a structural (not just CSS) reduced-motion bypass.

**Domain icons** (`frontend/src/components/DomainGlyph.tsx`): after several rounds of hand-drawn inline SVG that didn't read correctly at small sizes, the canonical set is six named `lucide-react` icons, imported individually (never a barrel import) so tree-shaking keeps the rest of the package out of the bundle: BODY-Activity, BUILD-Boxes, LIFE-CalendarDays, MIND-Brain, PATH-Compass, PEOPLE-UsersRound. `frontend/src/domainOrder.ts` is the one authoritative domain-number mapping every surface (Home badges, header emblem, `1`-`6` shortcuts) reads from, replacing two previously-separate hardcoded arrays that used to disagree with each other. Every icon is `aria-hidden`, decorative only; the enclosing control's own accessible name is always the source of truth for what a domain is called.

**A deterministic local UI-command layer** (`frontend/src/commands/registry.ts`) is shared by the Command Palette and voice transcript handling. `parseCommand(text)` is a pure function with no model involvement, matching exact phrases against fixed alias tables. It returns one of: `navigate` (a safe destination, executed immediately), `focus_control` (navigates to and highlights a sensitive control, e.g. an integration connect button, but never clicks it), `safe_action` (a reversible action like sync-now or run-a-routine, executed immediately), `confirm_required` (opens a real confirm dialog; disconnect/export only execute from that dialog's own button), `blocked` (a mutating verb plus a system noun, refused with an explanation), or `none` (falls through to an ordinary conversation turn). Matching deliberately excludes negated ("don't disconnect...") and interrogative ("what does sync do?") phrasings from executing, and Calendar/memory/record-proposing phrases are deliberately left unmatched so they always fall through to the Phase 8 propose-approve-execute lifecycle rather than a local shortcut.

**General conversation**: the Jarvis core itself opens a conversation with no domain assigned (`domain_id`/`active_domain_id` nullable), global-memory-only by default with optional per-turn domain chips. A single ambient instance handles Home/Centre voice questions by lazily creating or reusing one real general conversation.

**Diagnostics**: a shared set of primitives (`frontend/src/components/diagnostic/`) gives each real fault state (unknown route, backend unreachable with bounded auto-retry, Hermes unreachable but backend fine, an unhandled frontend error, a single failed supplementary request) its own truthful, distinct visual treatment rather than one generic error screen, distinguished by tone and ring shape, never by color alone.

**Voice waveform**: a shared Web Audio analyser hook drives a real bar visualization from the actual microphone stream while listening and the actual TTS playback element while speaking, never a randomized decorative substitute, with a static CSS fallback when Web Audio is unavailable or motion is reduced.

**Operational screens**: Memory, Actions, Skills, Integrations, Routine, and Data Management Centres each use a small shared vocabulary of compact components (ledger rows, a connected timeline, a status-cluster strip, a segmented tab row, a collapsed builder surface, a numbered tier hierarchy) suited to what each screen actually shows, rather than one generic stacked-card layout, per `docs/DESIGN_DIRECTION.md`'s "internal screens" doctrine.

**Motion and accessibility**: exclusively `transform`/`opacity` animation, no JS animation loops; a single `prefers-reduced-motion` rule zeroes every animation/transition duration globally, verified directly by reading computed transforms rather than assumed. State is always also expressed as text, never color alone. The full frontend has undergone repeated axe-core (WCAG2 A/AA) sweeps across every screen and diagnostic state, currently at zero known violations.

## 18. Sub-agents

Deliberately excluded from V1, a standing product decision, not "not started." Jarvis remains one assistant with six context spaces; Hermes delegation and toolsets remain disabled. If reconsidered after Phase 11, sub-agents would be temporary workers for bounded tasks (multi-source research, large code-change review), receiving minimum necessary context, never writing permanent memory directly, always returning results to the central Jarvis for presentation and memory-promotion decisions.

## 19. Engineering constraints

Local services bound to loopback only. Schema migrations required for any DB change. Validate all external/imported input. Every model/provider integration replaceable behind an interface. No destructive Git commands. Small, reviewable changes; no premature abstractions or speculative integrations.

## 20. Security, accessibility, and recovery hardening (Phase 11)

A verification pass, not a feature: confirmed loopback-only binding everywhere, a single non-wildcard CORS origin with credentials disabled, no secrets or browser storage anywhere in the codebase (grepped, not assumed; the frontend has zero `console.log` calls and zero browser-storage reads or writes), and that the schema-version check accepts any genuinely known older revision while rejecting an unrecognized one. A full axe-core sweep across every screen and diagnostic state found zero violations. A live restoration drill (two real backend processes, two isolated data directories, data populated across every subsystem reachable without Hermes/OAuth) confirmed a real export/validate/restore round-trip preserves everything and correctly forces pending proposals to expired and schedules to disabled. The real macOS Keychain and the real Hermes gateway's loopback/zero-toolset configuration were both independently reconfirmed against production. A full manual VoiceOver pass remains deliberately deferred to installed-app acceptance (see `docs/ROADMAP.md`).

## 21. Reliability and command-safety audit

A broader adversarial review across failure/recovery, natural-language command safety, memory/context, and scale (not tied to a specific phase's acceptance criteria) found and fixed five real defects: a proposal crashed mid-execution could get stuck forever (now swept and marked failed on startup); no explicit SQLite busy-timeout could produce an unhandled 500 under concurrent writes (now set explicitly); a malformed Calendar/Health API response could abort an entire sync instead of failing just that data point (now caught per-item); a genuine question about a voice command could execute it immediately instead of being recognized as a question; a negated command ("don't disconnect...") resolved the same as its affirmative form. All four command-safety fixes are now a shared guard in the command registry (§17). A later follow-up ran a five-year, ~53,000-row scale benchmark with no operation approaching its threshold, and fixed a real (disk-hygiene-only) risk of orphaned export scratch files with a narrow, dated startup cleanup. See D83-D85 for the full account.

## 22. Current situational briefing (Home)

A concise, deterministic NOW/NEXT/WATCH view assembled locally with no model call, no Hermes call, and no mutation of any kind.

**Shared assembler** (`app/briefing_service.py`): a small set of functions (today's Calendar events, open LIFE/PATH/BUILD records, the latest Health summary) that both the Home briefing and the Morning Briefing routine build on, so there is never a second independent derivation of the same facts. Candidates: Calendar events (NOW if imminent or under way, else NEXT), overdue or soon-due LIFE/PATH records, aggregated pending/failed action-proposal counts, failed or stale integration/routine state, a recent BUILD checkpoint, and, only when explicitly opted in, Google Health staleness. Ordering is fully deterministic and capped at roughly five items.

**Privacy is structural**: a single settings row seeded with BODY opted in and MIND/PEOPLE opted out; there is no code path from any MIND/PEOPLE table into this module at all, and the settings endpoint forces MIND/PEOPLE back off server-side regardless of what a client sends. Verified two ways: an AST test confirms the module imports no provider and calls no `send_turn`, and an HTTP test confirms the endpoint never changes agent status. "Discuss with Jarvis" is the only path that can reach a model.

**Continuity, acknowledge, and snooze**: each candidate carries a stable identity (never embedding volatile state) and a content fingerprint (a hash of only the fields worth noticing). A persisted ledger classifies each pass as new, ongoing, changed, resolved, or reopened; a source that fails to evaluate leaves its previously-active identities untouched rather than marking them resolved. Acknowledging or snoozing an item is presentation-only, keyed to the exact current fingerprint so it's automatically undone the moment that fingerprint changes, and never creates a Phase 8 proposal or touches the underlying source. The Morning Briefing routine records its own separate lightweight snapshot lineage, structurally isolated from Home's own comparison baseline.

**Mission Focus**: a small watchlist, at most five active pins, each a typed reference to a real existing source (a LIFE task, PATH deadline, BUILD checkpoint, selected Calendar event, or action proposal), never a copy of its content. The five-pin limit and one-active-pin-per-source rule are enforced at the database level via partial unique indexes and triggers, not just in application code. Pinning, unpinning, editing, and reordering are direct local actions, never Phase 8 proposals, and never touch the underlying source. A pin's domain is always resolved fresh from the real source, never accepted from a client, and MIND/PEOPLE sources are rejected outright.

**Mission Control**: a single persisted, timed focus session, drawing its candidates from the exact same assembler rather than a second priority engine. At most one session may be active or paused at a time, enforced by a database-level partial unique index. The timer is always derived from persisted timestamps (start time, accumulated paused time), never a client-side countdown treated as truth, so an ordinary restart is accurate for free. An export or restore into any installation forces an in-flight session into an interrupted state, exactly like Phase 8's in-flight proposals and Phase 9/10's live integration connections. Starting, pausing, resuming, completing, and abandoning a session are all direct local actions that never touch the item the session references.

## 23. Recall, Research, and Decision Room

**Recall** (`app/recall_service.py`): one fast, local search across everything Jarvis has stored, deterministic retrieval only, never a model feature. Memory items and document chunks keep using their existing FTS5 tables; every other source type (conversations, messages, structured records, domain summaries, calendar events, action proposals, routine runs, mission-control sessions) is indexed into one new `recall_fts` table, kept live-synchronized by the relevant create/update/archive/delete call sites rather than a periodic rebuild (a manual rebuild endpoint exists as a repair path). Every indexed row carries a domain slug or an explicit global/system classification; a query without an explicit domain filter defaults to LIFE/PATH/BUILD only, and an explicit empty filter is honored literally. Ranking is one fixed, documented pipeline (normalized bm25 relevance, an exact-match bonus, a same-domain hint, a small capped recency bonus, then a deterministic tie-break), never embeddings or a model call, confirmed by an AST test that the module imports no provider and calls no `send_turn`. Snippets are HTML-escaped before any highlighting is applied, so retrieved text, including anything phrased as an instruction, can never inject markup or be treated as a command. Availability is re-checked fresh at read time rather than trusted from the index, so a deleted source is truthfully reported unavailable rather than served as a stale result.

**Research** (`app/research_service.py`): lets Bernardo collect explicitly selected Recall evidence into a named workspace, classify it, attach notes, and generate a versioned, cited brief. Evidence discovery always delegates to Recall's own search, scoped by the workspace's own domain policy (defaulting to LIFE/PATH/BUILD, an explicit empty list honored literally). Evidence is a typed pointer to a real source, never a copy, with a frozen title/snippet/domain snapshot for citation stability. A deterministic outline always works with no model call; the one model path, "Draft with Jarvis," makes exactly one bounded request with no tools enabled and no evidence beyond what's actually in the workspace. Every `[N]` citation the model produces is validated server-side against the actual evidence set; an invalid citation is flagged, never silently dropped or accepted. A model-call failure never touches the workspace or any existing version; regenerating a brief always creates a new version, never overwrites one.

**Decision Room** (`app/decision_service.py`): built on top of Recall and Research, lets Bernardo weigh options against weighted criteria with a plain, deterministic, auditable score (a weighted sum; an unassessed pair is reported as missing, never defaulted to zero; a result sensitive to a single criterion is flagged). Evidence discovery again delegates to Recall; when a decision links a Research workspace, the two domain policies combine as an intersection, never a union. The one model path, "Ask Jarvis to challenge this decision," produces a labeled critique with the same tool-free, citation-validated shape as Research's model draft, and can never itself decide, finalize, or change the decision's status: deciding is always Bernardo's own explicit action, recorded as a new, separate, never-overwritten final version. Outcome review is a separate, additive record that never edits the original decision; a calibration summary is only shown once a minimum sample of reviewed decisions exists.

All three features share the same export/restore story as the rest of the database: no dedicated per-table export code, since a whole-database snapshot already includes them, and no regeneration or model call ever happens on restore.

## 24. Native macOS packaging and cross-Mac portability

Turns the existing dev-mode app into `/Applications/Jarvis.app` without changing frontend or backend product behavior. Private, single-Mac use only: no notarization, no paid Developer account, no DMG or updater, no pending "Stage 2."

**Layout**: `frontend/src-tauri/` (Tauri 2 shell: window, tray menu, single-instance enforcement, disabled-by-default launch-at-login) and a PyInstaller onefile arm64 sidecar built from `backend/packaging/`. The native window loads the sidecar's own `http://127.0.0.1:8000/` same-origin, exactly as `jarvisctl.sh` already does; the frontend-serving code is frozen-aware so it resolves the bundled frontend correctly whether running from source or from inside the packaged binary.

**Startup**: the Rust shell probes the backend's health endpoint; a genuine Jarvis response means reuse an already-running instance, silence means spawn and own one, and anything else is reported as a real port conflict rather than silently adopted. A background task permanently drains the sidecar's stdout/stderr pipes (an undrained pipe otherwise deadlocks the child once its startup log fills the kernel buffer). Quit sends SIGTERM to the owned process first, escalating to SIGKILL only if needed, then independently verifies via the actual bound process that nothing owned by this app was left behind, since PyInstaller onefile's outer process is a bootloader stub that SIGKILL alone can orphan.

**Signing**: one stable, self-signed local certificate, created only after Bernardo's explicit approval of the exact proposal, so Keychain's per-item approval survives rebuilds. Hardened runtime required two specific entitlements (disabled library validation, for the bundled Python framework; the audio-input entitlement, without which `getUserMedia` never reaches the system permission prompt at all).

**Cross-Mac portability**: `POST /api/restore` and the native "Restore from Jarvis export" flow both call the exact same `restore_archive()` the CLI always used, gated by the same explicit-confirmation-to-overwrite rule. Restoring over a live process's own database is made safe by disposing the shared database engine's pooled connections immediately before the file underneath is replaced; the engine object itself is never rebuilt, so every later request transparently reopens the now-restored file. `GET /api/data-dir` exposes the resolved, non-secret data directory path, backing both the UI and the tray's "Reveal Jarvis Data Folder."

**Post-ship stabilization**: real daily use of the installed app surfaced and fixed several real defects, documented in full in D106-D109: icon rendering, an OAuth Connect button that opened nothing (Tauri's IPC bridge isn't present on same-origin content loaded via `navigate()`, fixed by opening the system browser server-side instead), a voice-error screen with no way to dismiss, denied microphone access before a permission prompt could even appear, and a missing `multiprocessing.freeze_support()` call that caused a runaway startup-respawn loop under specific conditions (fixed with one line, see D109).
