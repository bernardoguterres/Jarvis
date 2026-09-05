# Jarvis

Phases 1-10B, Phase 6, Phase 11, Phase 12A, Phase 12B, Phase 12C, Mission
Control, Phase 12D, Phase 12E, and Phase 12F of Jarvis (see "Revised execution order"
in `docs/ROADMAP.md` — Phase 6, the real animated HUD, was deliberately
built after the other functional phases and is now **complete**, including
real-hardware voice acceptance performed by Bernardo himself (push-to-talk
from Home, one confirm-required voice command); a full VoiceOver pass is
deliberately deferred to installed-app acceptance after native macOS
packaging, and the 1280×800/1024×768/820×900 viewport inspection remains
outstanding — see "What Phase 6 includes" below. Phase 11 hardening is
**complete**, including a real (isolated, cleaned-up) macOS Keychain test;
VoiceOver is deferred the same way as Phase 6's — see "What Phase 11
includes" below. V1's feature set is frozen (Phase 12 ends at Phase 12F;
no Phase 12G is planned). **Native macOS packaging Stage 1 is complete**
(`docs/DECISIONS.md` D104): Jarvis is installed at `/Applications/Jarvis.app`
(Tauri 2 shell around the same frontend, a self-contained PyInstaller
backend sidecar, a stable local code-signing identity) — see "Running the
native app" below. **Cross-Mac portability** (D105) followed immediately:
a guarded in-app Restore action alongside Export, so a Jarvis snapshot can
move between Bernardo's Macs without a terminal. Only the deferred
VoiceOver pass and the 1280×800/1024×768/820×900 viewport inspection
remain outstanding, now against the installed native app itself. Phase 12A (a current situational briefing
on Home), Phase 12B (that briefing's continuity/change-tracking and local
acknowledge/snooze controls), Phase 12C (a small user-owned Mission
Focus watchlist referencing existing sources), Mission Control (a single
persisted, timed focus session — real-Mac accepted, see below), Phase 12D
(deterministic local search across every domain), Phase 12E (evidence
collection and cited research briefs built on that same search), and
Phase 12F (transparent, evidence-grounded decisions built on Recall and
Research, completing Recall → Research → Decide → Focus) are all
implemented and container-verified — Mission Control, Phase 12D, Phase
12E, and Phase 12F now have real-Mac data acceptance (`docs/DECISIONS.md`
D102); each still has one item folded into Phase 6's own outstanding
real-microphone voice checklist; see "What Phase 12A includes" through
"Phase 12F" below): local
persistence, a basic six-domain vertical slice,
verified export/import/backup portability, a first real model connection
through a dedicated local Hermes Agent profile — currently **GPT-5.6 Terra
via OpenAI Codex OAuth** (Bernardo's ChatGPT subscription) — and
model-independent local memory: versioned memories, structured records,
domain summaries, and fully auditable context retrieval, all in Jarvis's
own SQLite database. The connection is genuinely model-independent: Jarvis
never sends a model string to Hermes at all, so switching providers again
later needs zero Jarvis code changes, and memory survives it untouched.
Phase 5 adds explicit push-to-talk voice — hold Space (or a button) to
record, local `faster-whisper` transcription, the transcript sent through
the existing turn flow, and the reply spoken back via Edge TTS — with no
continuous listening and no raw audio retained after transcription. Phase 7
adds a local macOS runtime for daily use — `scripts/jarvisctl.sh` starts (or
idempotently focuses) Jarvis as a single app-like Chrome window backed by a
production frontend build and the FastAPI backend, plus optional
start-at-login and keyboard shortcuts (domain switching, a command palette,
a quick export shortcut) — all without Tauri, Electron, or any paid hotkey
manager. Phase 8 adds controller-owned permissions: a default-deny capability
registry, an auditable propose→approve→execute action lifecycle for every
mutation Jarvis itself proposes (never for actions you take directly through
the UI), explicit lifecycle hooks, and a local versioned skill system whose
invocations only ever go through that same approval lifecycle. Phase 9 adds
Google Calendar (read + limited owned-calendar-only write, through that same
action lifecycle), read-only Google Health (which can include data from
Fitbit and other connected sources), and explicit local document import —
all model-independent, all with credentials living only in the macOS
Keychain, never in SQLite/exports/logs. See `CLAUDE.md` for the full project
profile and `docs/` for the product spec, architecture, roadmap, and
decisions record.

## Where your data lives

Application source code lives in this Git repository. **Personal data never
does.** It lives under `JARVIS_DATA_DIR`, which defaults to `~/JarvisData`:

```
~/JarvisData/
  database/jarvis.sqlite
  documents/
  domain-summaries/
  skills/
  configuration/
  backups/
  exports/
```

**Deleting this repository (or your clone of it) must never delete
`~/JarvisData`.** They are intentionally separate. Set `JARVIS_DATA_DIR` in
your environment (or in `backend/.env`, see `.env.example`) to use a different
location.

## Prerequisites

* Python 3.12+
* [uv](https://docs.astral.sh/uv/) (`brew install uv`)
* Node.js 20+ and npm

## Backend (Python / FastAPI)

```bash
cd backend
uv sync --group dev            # install dependencies
uv run alembic upgrade head     # apply database migrations (creates the schema
                                 # under JARVIS_DATA_DIR; never overwrites existing data)
uv run uvicorn app.main:app --reload --host 127.0.0.1 --port 8000   # start the backend
```

Run the backend test suite (uses isolated temporary data directories only,
never `~/JarvisData`):

```bash
uv run pytest
```

## Frontend (React / Vite)

```bash
cd frontend
npm install         # install dependencies
npm run dev          # start the dev server (http://localhost:5173)
npm run test         # run Vitest + React Testing Library tests
npm run typecheck    # TypeScript project-reference type-checking
npm run build        # production build (outputs to frontend/dist)
```

## Running both together

```bash
scripts/dev.sh
```

This just runs the backend and frontend dev commands above concurrently and
stops both on exit. Each command also works independently.

## Export, backup, and restore

All commands below run from `backend/`. Every one accepts `--data-dir` (or,
for restore, `--target`) to point at a specific `JARVIS_DATA_DIR`; omit it to
use the current environment's default.

```bash
# Create a portable export archive (JARVIS_DATA_DIR/exports/jarvis-export-YYYYMMDD-HHMMSS.zip)
uv run jarvis-cli export

# Check whether an archive is valid WITHOUT restoring anything
uv run jarvis-cli validate path/to/jarvis-export-20260101-120000.zip

# Restore into a clean, empty JARVIS_DATA_DIR (moving to a new machine)
uv run jarvis-cli restore path/to/jarvis-export-20260101-120000.zip --target ~/JarvisData

# Restore over an EXISTING installation (requires --confirm; a rollback
# safety copy of the previous installation is made first automatically)
uv run jarvis-cli restore path/to/jarvis-export-20260101-120000.zip --target ~/JarvisData --confirm

# Create a manual backup (category defaults to daily)
uv run jarvis-cli backup
uv run jarvis-cli backup --category weekly

# Show the latest backup per category
uv run jarvis-cli list-backups
```

Restoration always validates the archive first (structure, checksums,
schema) in an isolated temporary directory before touching any real data,
and is only ever performed by this CLI — not the browser — because it can
replace a live database. The Data Management view in the HUD can create
exports/backups and *validate* an archive, but never restores one.

A lightweight due-check runs automatically on backend startup: if the daily,
weekly, or monthly backup is overdue, one is created then. This is not a full
recurring scheduler (see `docs/ARCHITECTURE.md`).

**Backups on this laptop do not protect you from losing the laptop.**
Periodically copy files from `JARVIS_DATA_DIR/exports/` to an encrypted
external drive or an encrypted Time Machine backup.

## Hermes and model setup

Jarvis talks to whatever model is configured through a **dedicated local
Hermes Agent profile** named `jarvis` — not the default Hermes profile, and
not six separate profiles. Hermes owns the model/provider connection
entirely; the FastAPI backend never sees, stores, or even names a specific
model in its requests (see `docs/ARCHITECTURE.md` §7a) — switching
providers is a Hermes-side command, never a Jarvis code change.

**Currently configured**: GPT-5.6 Terra via OpenAI Codex OAuth, authenticated
against Bernardo's ChatGPT subscription. No Anthropic key, no OpenAI API
key, and no model credential of any kind exists anywhere in this project —
the OAuth token lives only in Hermes's own `~/.hermes/profiles/jarvis/auth.json`.

### 1. Install Hermes (if not already installed)

```bash
curl -fsSL https://hermes-agent.nousresearch.com/install.sh | bash
```

Check what's installed at any time with `hermes --version` and `hermes doctor`.

### 2. Create the dedicated profile (one-time)

```bash
hermes profile create jarvis --no-skills --description "Bernardo's personal Jarvis assistant profile"
```

This creates a blank profile at `~/.hermes/profiles/jarvis` and a `jarvis`
wrapper command (`jarvis <cmd>` == `hermes -p jarvis <cmd>`) at
`~/.local/bin/jarvis`. It does not clone any other profile's memories or
credentials, and does not enable Honcho, messaging gateways (Telegram/
Discord/etc.), sub-agents, or cron.

### 3. Choose a provider and authenticate — **you do this yourself, not through an AI session**

```bash
jarvis setup model
```

Run this in your own terminal. Pick whichever provider/model you want —
this is exactly how the switch to GPT-5.6 Terra (OpenAI Codex OAuth) was
made, and how a future switch to Anthropic, or anything else Hermes
supports, would be made too. Nothing here should ever be pasted into or
read back by an assistant session — this is by design (see
`docs/DECISIONS.md` D21). For an OAuth-based provider (as currently
configured), this opens a browser login and stores the resulting token in
`~/.hermes/profiles/jarvis/auth.json`; for an API-key-based provider, you'd
enter the key directly at that same prompt instead. Either way, update
`HERMES_MODEL` in `backend/.env` (a display label only — see
`.env.example`) to match what you configured, so the HUD/audit log show the
right name; the backend's actual behavior needs no other change.

### 4. Generate the Hermes API server's bearer token (non-secret action, secret value)

This is a **different secret** from whatever model credential you just set
up — it authenticates the local FastAPI backend to the local Hermes API
server, nothing else.

```bash
openssl rand -hex 32 >> ~/.hermes/profiles/jarvis/.env   # prefix with API_SERVER_KEY=
chmod 600 ~/.hermes/profiles/jarvis/.env
```

Then copy the same value into `backend/.env` as `HERMES_API_BEARER_TOKEN=...`
(see `.env.example`; `backend/.env` is gitignored and never touches
`JARVIS_DATA_DIR`, so it's never included in an export or backup).

### 5. Lock down the profile's tool surface (minimal, conversation-only)

```bash
jarvis tools disable web browser terminal file code_execution vision image_gen delegation cronjob session_search todo --platform api_server
jarvis config set memory.write_approval true
jarvis config set skills.write_approval true
jarvis config set gateway.api_server.max_concurrent_runs 1
jarvis config set curator.enabled false
```

Verify what's actually enabled (don't just trust the config file):

```bash
jarvis tools list --platform api_server   # only 'skills' and 'memory' should show enabled
```

### Start / stop / check the gateway

```bash
scripts/hermes-gateway.sh start-background   # or: start (foreground)
scripts/hermes-gateway.sh health              # unauthenticated + authenticated checks
scripts/hermes-gateway.sh status
scripts/hermes-gateway.sh stop
scripts/hermes-gateway.sh doctor
```

The gateway binds to `127.0.0.1:8642` only. `scripts/dev.sh` checks whether
it's running and reminds you if not — Jarvis's own persistence and HUD work
fine either way; only "Send to Jarvis" needs the gateway up.

### Important distinctions

* Your **Claude Code subscription** (if you have one) and **whatever Jarvis
  is actually configured to use** are completely separate and unrelated —
  currently GPT-5.6 Terra, billed against your ChatGPT/OpenAI Codex
  subscription via OAuth, with no Anthropic involvement at all right now.
* Changing models later never removes Jarvis data — memory lives in
  Jarvis's own database, model-independent (see `docs/ARCHITECTURE.md`),
  and Jarvis's backend code doesn't even know which model is configured.
* If Hermes is down or misconfigured, local conversation storage, notes,
  domains, export/backup all keep working — only real Jarvis responses are
  unavailable, and the HUD says so.
* No external memory provider (Honcho, etc.) is enabled. No autonomous
  tools, sub-agents, or scheduled actions are enabled for this profile.

## Memory, records, and context (Phase 4)

All of Bernardo's personal memory lives in Jarvis's own SQLite database —
never in Hermes, never sent to an embedding API, and never tied to
whichever model happens to be configured. The main endpoints (all under
`backend/app/routers/memory.py`):

```
GET/POST   /api/memories                       list / create
GET        /api/memories/search?q=...          lexical (FTS5) search
GET        /api/memories/{id}                  read + full version history
POST       /api/memories/{id}/edit              new immutable version
POST       /api/memories/{id}/supersede         new memory, old one archived + linked
POST       /api/memories/{id}/archive           remove from retrieval, keep history
POST       /api/memories/{id}/unarchive         restore to active
POST       /api/memories/{id}/delete            PERMANENT — requires typed exact title

GET/PUT/DELETE  /api/domains/{slug}/summary            current summary
GET             /api/domains/{slug}/summary/history     all versions

GET/POST   /api/domains/{slug}/records          list / create structured records
POST       /api/records/{id}/archive

GET        /api/agent-runs/{run_id}/context     the exact context snapshot used for one turn

POST       /api/memory-index/rebuild            rebuild the derived FTS5 index from source data
GET        /api/memory-index/status             row count check
```

`POST /api/conversations/{id}/turns` now also accepts an optional
`additional_domain_ids` list — an explicit, single-turn "include another
domain" selection. It's never remembered across turns; the next turn must
select it again if wanted. The response's `context_snapshot_id` lets the
frontend fetch exactly what was assembled for that turn via the endpoint
above.

**Structured record types** (each locked to one domain, Pydantic-validated,
no unbounded/unvalidated JSON accepted): `body_weight`, `body_symptom`
(BODY); `mind_checkin` (MIND); `people_interaction` (PEOPLE);
`path_deadline` (PATH); `build_checkpoint` (BUILD); `life_task` (LIFE).

**In the HUD**: a "Memory Centre" (global profile memories + onboarding
form) is reachable from the home view; each domain view has its own
summary, memories, and structured-record panels, a "Remember" action on any
message, an "Include another domain" selector (with a warning before
including BODY/MIND/PEOPLE), and a "Context used" control on every
assistant response showing exactly which memories/records/summary
versions/messages were sent.

Editing a memory always creates a new version — nothing is ever overwritten
in place. Archiving removes a memory from retrieval without touching its
history. Permanent deletion requires typing the memory's exact current
title and automatically creates a rollback backup (`backups/pre_delete/`)
first.

## What Phase 1 includes

* Six fixed domains (BODY, MIND, PEOPLE, PATH, BUILD, LIFE) seeded with stable,
  deterministic UUIDs.
* Conversations and messages, one domain per conversation, persisted in SQLite
  via SQLAlchemy, with Alembic-managed schema migrations.
* A local FastAPI controller exposing health, domain, conversation, and
  message endpoints, bound to loopback and CORS-restricted to the local Vite
  origin.
* A minimal, unpolished HUD: a central Jarvis circle with six domain circles,
  a backend health indicator, and per-domain conversation/message views.

Jarvis does **not** generate assistant responses yet. Anything typed into a
conversation is stored as a plain user note. Intelligence (Claude/Hermes) and
voice arrive in later phases — see `docs/ROADMAP.md`.

## What Phase 2 includes

* A versioned, portable ZIP export (`jarvis-export-YYYYMMDD-HHMMSS.zip`)
  containing a consistent SQLite snapshot, any documents/domain-summaries/
  skills/configuration present, and a `manifest.json` with SHA-256 checksums,
  schema revision, and platform info (no secrets, no absolute paths).
  A `hermes_profile/` path is reserved in the format but never populated
  until Hermes is integrated (Phase 3+).
* Import validation that extracts an untrusted archive into an isolated
  temporary directory first, then checks structure, checksums, schema
  compatibility, and required domain data before anything ever touches
  `JARVIS_DATA_DIR`.
* A CLI-driven restore flow (`jarvis-cli restore`) that refuses to overwrite
  an existing installation without `--confirm`, takes a verified rollback
  copy first, and restores the previous installation automatically if
  anything fails partway through.
* Local backups (daily/weekly/monthly retention) using the same consistent
  SQLite snapshot mechanism, with safe pruning that only ever touches
  recognised Jarvis backup files.
* A Data Management view in the HUD for exporting, backing up, validating
  archives, and — since native packaging Stage 1 (D105) — a guarded,
  confirmation-gated in-app **restore** flow too (`POST /api/restore`,
  wrapping the exact same `restore_archive()` the CLI has always used); the
  CLI restore path remains fully supported alongside it.

## What Phase 3 includes

* A model-independent agent-provider interface (`app/providers/base.py`),
  with Hermes as its first implementation (`app/providers/hermes.py`),
  calling the local Hermes API server's OpenAI-compatible
  `/v1/chat/completions` endpoint.
* A new `POST /api/conversations/{id}/turns` endpoint that saves the user
  message, creates an audited `agent_runs` record, calls Hermes, saves the
  real assistant response with `model_used`, and returns both — separate
  from the existing plain note-saving endpoint. Idempotency-keyed so a
  browser retry can't double-charge for the same turn.
* A bounded, basic context per turn: a short system instruction, the active
  domain's name/description, the conversation title, and a configurable
  number of recent messages from that same conversation — no semantic
  memory search or cross-domain retrieval yet.
* `GET /api/agent/status` reporting Hermes availability and model
  configuration (never the bearer token) for a HUD indicator separate from
  the existing backend/database health indicator.
* "Save as note" vs. "Send to Jarvis" as two distinct, clearly labeled
  actions in the conversation view.
* Export/import extended to optionally include a Hermes profile export
  (via Hermes's own `hermes profile export`/`import` commands), scanned
  independently for `.env`/`auth.json` before ever being trusted, and never
  auto-imported on restore — Bernardo runs that step himself.

## What Phase 4 includes

* Versioned local memory (`memory_items` + immutable `memory_versions`),
  global or domain-scoped, with supersession, archive, and typed-confirmation
  permanent deletion (with an automatic rollback backup).
* Validated structured records for the seven initial types listed above.
* Manually-edited, versioned domain summaries (never auto-regenerated).
* A fully local, deterministic `ContextBuilder`/retrieval pipeline: SQLite
  FTS5 lexical search with an importance/recency fallback, active-domain
  isolation, explicit-only cross-domain inclusion, a configurable context
  size budget with visible truncation, and stored memory content always
  presented to the model as quoted reference data — never as instructions.
* An auditable `context_snapshots` table recording the *exact* memory/
  summary/record/message identifiers used for every turn that reached
  context construction, whether the model call then succeeded or failed.
* A Memory Centre view (global memories + onboarding) and per-domain
  memory/record/summary panels, a Remember action, an explicit
  cross-domain selector with a sensitivity warning, and a Context Used
  control per assistant response.
* Export/import/backup extended automatically to cover all of the above
  (it's the same SQLite file); the FTS5 index is never trusted as
  authoritative and is rebuildable from source data at any time.

## What Phase 5 includes

* `POST /api/voice/transcribe` (multipart audio upload → transcript text,
  local `faster-whisper`) and `POST /api/voice/speak` (text → `audio/mpeg`,
  Edge TTS), both behind model-independent `SpeechToText`/`TextToSpeech`
  Protocols (`app/voice/base.py`) — same shape as the Phase 3 agent-provider
  interface.
* Push-to-talk in the HUD: hold Space (while no text field is focused) or
  the on-screen "Hold to talk" button in any domain's conversation view;
  release to stop, transcribe, send through the existing turn flow, and
  hear the reply spoken back. Escape cancels an in-progress recording.
* No raw audio is ever written under `JARVIS_DATA_DIR`; the uploaded
  recording is written to an OS temp file and deleted immediately after
  transcription, success or failure (see `docs/DECISIONS.md` D37).
* This phase adds only these functional controls to the existing plain
  HUD — no visual redesign (that's Phase 6; see `docs/DESIGN_DIRECTION.md`).

`faster-whisper` downloads its model weights (~150MB for the default
`base` model) from Hugging Face on first real transcription, then caches
them locally — this needs network access once, the first time you actually
use voice, not on every backend startup. Model size/device are configurable
via `WHISPER_MODEL_SIZE`/`WHISPER_DEVICE`/`WHISPER_COMPUTE_TYPE` in
`backend/.env` (see `.env.example`); the TTS voice via `EDGE_TTS_VOICE`.

## What Phase 7 includes

* `backend/app/main.py` serves the production frontend build (`frontend/dist`)
  from the same origin/port as the API, whenever that build exists — no
  separate frontend server needed for ordinary use (see `docs/ARCHITECTURE.md`
  §8b, D41/D42).
* `scripts/jarvisctl.sh` — the local runtime controller: `open`/`focus`
  (idempotent start-or-focus), `status`, `stop`, `install-startup`,
  `uninstall-startup`. See "Running Jarvis day-to-day" below.
* A project-owned LaunchAgent template (`macos/com.bernardo.jarvis.launcher.plist.template`)
  for optional start-at-login — only ever installed with your explicit
  approval, never silently.
* In-app keyboard shortcuts: digits `1`-`6` select a domain, `Cmd+K` opens a
  functional command palette, `Cmd+Shift+E` opens the export workflow
  (Data Management), and Escape cancels an in-progress voice recording or
  otherwise returns to the Jarvis home view — none of them fire while a text
  field has focus.
* No visual redesign — the plain HUD from Phase 1 is unchanged; Phase 7 adds
  only the functional controls above (see `docs/DESIGN_DIRECTION.md`).

## Running the native app

Jarvis is packaged as a real native macOS app — `/Applications/Jarvis.app`
— since native packaging Stage 1 (`docs/DECISIONS.md` D104). This is the
normal way to use Jarvis day-to-day; the `jarvisctl.sh`/browser workflow
below remains available for development and as a recovery fallback.

* **Open it** from Finder/Spotlight/Dock like any other app — no Chrome,
  no terminal, no manually-entered URL. It opens its own native window,
  starts (or reuses an already-running) backend silently in the background,
  and waits for it to become healthy before showing anything.
* **Menu-bar icon**: Open Jarvis / Hide Jarvis / System Status / Sync
  Integrations / Export Portable Jarvis Backup / Restore from Jarvis
  Export… / Reveal Jarvis Data Folder / Launch Jarvis at Login (off by
  default) / Quit Jarvis.
* **Closing the window** (the red button) hides Jarvis rather than quitting
  it — scheduled integration syncs and routines keep running. Click the
  Dock icon, or "Open Jarvis" from the menu bar, to bring it back.
* **Quit Jarvis** (menu bar, or Cmd+Q) stops only the backend process this
  app itself started — it never touches a `jarvisctl.sh`-started backend it
  didn't spawn, and never leaves an orphaned process behind.
* **Moving to a new Mac**: install `Jarvis.app` there (it starts with an
  empty `~/JarvisData`), use **Export Portable Jarvis Backup** here, copy
  the resulting `.zip` over, then use **Restore from Jarvis export** in
  Data Management on the new Mac. `Jarvis.app` itself is application code
  only — your real data always stays in `JARVIS_DATA_DIR`
  (`~/JarvisData` by default), untouched by installing, rebuilding, or
  replacing the app bundle. See `docs/DECISIONS.md` D105 and
  `docs/ARCHITECTURE.md` §23 for the full guarantees restore always
  preserves (secrets never included, integrations/schedules always forced
  disabled until you review them, a rollback copy kept automatically).
* **Code signing**: signed with a self-signed certificate that exists only
  on this Mac ("Jarvis Local Dev") — not a paid Apple Developer identity,
  never notarized, never distributed. macOS may ask you to approve Keychain
  access the first time a build with a given signing identity runs; that
  approval then persists across ordinary relaunches and rebuilds signed
  with the same certificate.
* **Building it yourself**: `cd backend && uv run pyinstaller
  packaging/jarvis_backend.spec --distpath packaging/dist` builds the
  backend sidecar; copy the result to
  `frontend/src-tauri/binaries/jarvis-backend-aarch64-apple-darwin`, then
  `cd frontend && npx @tauri-apps/cli@2 build` produces
  `frontend/src-tauri/target/release/bundle/macos/Jarvis.app`.

## Running Jarvis day-to-day (development / recovery fallback)

```bash
scripts/jarvisctl.sh open     # start Jarvis if needed, then open/focus it
scripts/jarvisctl.sh focus    # same thing — alias, for when it's already running
scripts/jarvisctl.sh status   # Hermes gateway + backend health, start-at-login state
scripts/jarvisctl.sh stop     # stop the Jarvis-owned backend only (not the Hermes gateway)
```

`open`/`focus` is fully idempotent: running it again while Jarvis is already
healthy just reopens/refocuses the window — it never starts a second backend,
rebuilds the frontend unnecessarily, or starts a second Hermes gateway. It
applies pending database migrations and builds the frontend automatically, so
day-to-day use never needs the manual `uv run alembic ...`/`npm run build`
steps described elsewhere in this README (those remain useful for
development). State this script owns — PID file, logs, a dedicated Chrome
profile for Jarvis's app-mode window — lives under
`~/Library/Application Support/Jarvis`, never under `JARVIS_DATA_DIR`, and is
never included in an export (see `docs/DECISIONS.md` D43).

Test all of the above safely, without touching your real machine, at any time:

```bash
bash scripts/test_jarvisctl.sh
```

### One-time setup: the `Control+Option+J` global shortcut

macOS has no built-in way for a script to silently register a global
keyboard shortcut, and Jarvis will never modify macOS Shortcuts on your
behalf (see CLAUDE.md's safety boundary) — so this is a short one-time
manual step, using only the built-in Shortcuts app:

1. Open **Shortcuts.app** → **+** (new shortcut).
2. Add a single **"Run Shell Script"** action, shell `/bin/bash`, with:
   ```bash
   /path/to/Jarvis/scripts/jarvisctl.sh open
   ```
   (use this repository's actual absolute path).
3. Name it (e.g. "Open Jarvis"), then click the **ⓘ** info button in the
   shortcut's detail view → **Add Keyboard Shortcut** → press
   `Control+Option+J`.

That's it — no separate hotkey manager, no Automator, nothing else installed.

### Optional: start Jarvis automatically at login

`scripts/jarvisctl.sh install-startup` installs a LaunchAgent that runs
`jarvisctl.sh open` once at login (not a supervisor — it doesn't restart
Jarvis if it's later stopped). Before running this yourself:

* **What gets installed**: a plist rendered from
  `macos/com.bernardo.jarvis.launcher.plist.template`, with this repository's
  actual absolute path substituted in.
* **Exact destination**: `~/Library/LaunchAgents/com.bernardo.jarvis.launcher.plist`.
* **Permissions required**: none beyond your own user account — it runs as
  you, not as root, and touches nothing outside your own LaunchAgents
  directory and Jarvis's own runtime/log directory.
* **How to remove it**: `scripts/jarvisctl.sh uninstall-startup` (unloads it
  from `launchd` and deletes the file) — fully reversible.
* **What you still do yourself**: nothing further; login-time behavior takes
  effect at your next login (or run `launchctl kickstart -k gui/$(id -u)/com.bernardo.jarvis.launcher`
  to test it immediately without logging out).

## What Phase 8 includes

* A fixed, code-owned **capability registry** (`backend/app/capabilities.py`) —
  `memory.create`, `structured_record.create`, `domain_summary.update`, all
  "Confirm" tier, all controller-owned internal records with no external
  side effect. Not a database table, not extensible at runtime by a skill,
  an import, or a model.
* An auditable **action lifecycle**
  (`POST /api/actions`, `.../approve`, `.../execute`, `.../deny`, and
  `GET /api/actions`) — every mutation *Jarvis itself* proposes goes through
  propose → approve → execute, bound to an immutable payload digest and a
  short-lived, single-use confirmation token; every transition is recorded
  in an append-only audit trail. Actions you take directly through the
  existing UI (saving a note, editing a memory by hand) are unaffected.
* Four explicit, ordered, auditable **lifecycle hooks**
  (`backend/app/hooks.py`): `before_context` (guards turn construction
  against a stale domain), `before_action` ×3 (capability allowlist check,
  the confirmation-token/digest/expiry enforcement itself, a recursion
  guard), `after_action`, `on_failure` — never arbitrary user-provided code.
* A local, versioned **skill system** (`POST /api/skills`, `.../edit`,
  `.../activate`, `.../archive`, `.../invoke`) — declarative workflows only,
  always start as a draft, editing an active skill always demotes it back
  to draft for re-review, and invoking one only ever creates action
  proposals through the same approval lifecycle above. Four clearly-labeled
  inactive example templates (BODY weekly check-in, BUILD project
  checkpoint, PATH deadline review, LIFE daily planning) are seeded as
  drafts — never auto-activated.
* An **Actions Centre** and **Skills Centre** in the HUD for reviewing,
  approving, denying, and inspecting audit history, and for
  creating/reviewing/activating/invoking skills — still no visual redesign
  (see `docs/DESIGN_DIRECTION.md`).
* Hermes's own toolsets remain fully disabled throughout (live-verified via
  `jarvis tools list --platform api_server` — zero enabled); no terminal,
  filesystem, browser, code-execution, delegation, cron, email, or calendar
  tool access was introduced.

## What Phase 9 includes (complete — live acceptance passed)

Both integrations below use a Google OAuth **Web application** client
(never a Desktop/installed client) — Google's own documentation states that
incremental authorization (used to request Calendar's write scope only
when you explicitly enable it) is not supported for installed/Desktop
clients. This backend performs the authorization-code exchange itself and
owns a fixed callback endpoint per provider, which is exactly what a Web
application client type is for. See `docs/DECISIONS.md` for the full
rationale.

* **Google Calendar**: read (`calendar.calendarlist.readonly` + `calendar.events.readonly`
  by default) and limited write (`calendar.events.owned` — owned calendars
  only, requested via a separate incremental-consent step only when you
  enable it). Select which calendar(s) Jarvis may access, manual sync over a
  bounded range (1 day past, 30 days future), a normalized local cache with
  last-sync/staleness shown. Writes (create/update/delete one event) are
  Phase 8 capabilities — always propose → your exact approval → single
  execution → audit, never a bare API call. No attendees, invitations,
  recurring events, sharing changes, or calendar deletion. The write
  capability checks the connection's *actually-granted* scopes (never what
  was merely requested) both when a write is proposed and again immediately
  before it executes — refusing cleanly if `calendar.events.owned` isn't
  present.
* **Google Health** (internal provider id `google_health`): a general
  integration, not Fitbit-specific — it reads reconciled, consented data
  through the current Google Health API (`health.googleapis.com/v4`, not
  the legacy Fitbit Web API Google is retiring in September 2026) that can
  originate from Fitbit, Pixel Watch, Health Connect, Google Fit, or any
  other source connected to the account. Availability depends on the
  account, contributing devices/apps, granted scopes, and device
  capabilities — never assumed complete. Read-only, manual sync only.
  Daily summaries (steps, distance, floors, active zone minutes, active/
  total calories, heart rate, resting heart rate, HRV, oxygen saturation,
  respiratory rate, VO2 max, weight, body fat, blood glucose where present)
  plus full sleep sessions (with stages) and exercise sessions — each
  fetched via the correct officially-supported operation for that type
  (`dailyRollUp`, or `list` with a live-verified filter/date-truncation
  strategy), never all sent through one operation. A single metric's fetch
  failure is handled per-metric (a sync can be `"partial"`) and never
  aborts the rest of the sync. Daily Readiness Score, Sleep Score, Stress
  Management Score, and Cardio Load/Target Load are shown as explicitly
  **unsupported** (no documented Google Health data type exposes them) —
  never estimated or relabeled from another metric. No write capability
  exists at all, and none is registered in the capability registry.
  Periodic automatic resync is now available (Phase 10) — see below;
  manual "Sync now" still works exactly as before regardless.
* **Local documents**: explicit browser upload only (PDF/DOCX/TXT/Markdown)
  — never a scanned or watched folder. Content is validated by its actual
  bytes, not the filename extension; macro-bearing DOCX and zip-bomb-like
  content are rejected outright; SHA-256 duplicate detection; extracted text
  is chunked and locally indexed (rebuildable, like the memory index) with
  citations back to the source document/chunk/page. Permanent deletion
  requires typing the exact original filename and creates a rollback backup
  first, same as memory deletion.
* Every credential (OAuth client id/secret, access/refresh tokens) lives
  only in the macOS Keychain — never in SQLite, `.env`, exports, backups, or
  logs, and never returned by any API response.
* An **Integrations Centre** in the HUD for connection status, scopes,
  selected calendars, sync, and document management — still no visual
  redesign.
* Context is domain-aware: Google Health data enters only BODY context by
  default, Google Calendar only LIFE, both explicitly labeled with sync
  staleness; document citations follow the document's assigned domain. All
  of it is quoted, untrusted reference data — the same framing that already
  governs memories — so document/calendar/Google Health content can never
  itself approve or execute an action.

### Connecting real accounts (one-time, done by you — never through a chat session)

**Use two separate Google OAuth Web application clients — one for
Calendar, one for Google Health.** An earlier version of this guidance
recommended sharing one client (or even one Cloud project) for simplicity;
live acceptance found that Google associates OAuth consent with the
**(user, Cloud project) pair, not (user, client_id)** — sharing either a
client or a project let one integration's consent screen return the
other's scopes, corrupting what got stored (see `docs/DECISIONS.md`
D62-D65). Jarvis defensively filters each callback's granted scopes down
to only what that specific provider uses, so this can no longer corrupt
storage, but two genuinely separate clients (ideally in separate Cloud
projects) avoids the underlying confusion entirely and is what Bernardo's
real installation now uses. Full step-by-step instructions (Google Cloud
Console project/OAuth-client setup, both exact callback URIs, enabling the
Calendar API and the Google Health API, a consent-screen test user, exact
scopes and why each is needed, and revocation steps) were provided
directly to Bernardo, per CLAUDE.md's rule that Jarvis never asks you to
paste credentials into a chat and never handles real secrets itself. In
short:

```bash
cd backend
uv run jarvis-cli configure-integration google_calendar   # prompts for client id/secret, stores in Keychain
uv run jarvis-cli configure-integration google_health      # same, for Google Health (can include Fitbit, Pixel Watch, Health Connect, Google Fit, and other connected sources)
```

Then use the Integrations Centre's "Connect" button for each provider —
this opens the real OAuth consent screen in your browser; nothing about the
exchange that follows is visible to or handled by any AI session.

## What Phase 10A includes: automatic integration resync

Both Calendar and Google Health can now sync on their own schedule instead
of only when you click "Sync now" — entirely controller-owned (a single
background loop inside the Jarvis backend itself, never a Hermes cron job,
sub-agent, or model call). **Disabled by default** — you enable it
per-provider in the Integrations Centre.

* Calendar: 15/30/60-minute cadence. Google Health: 1/3/6-hour or daily.
  Both minimums are enforced by the backend, not just the dropdown.
* Enabling runs one sync immediately, then follows the chosen interval.
* Automatic sync only runs while Jarvis is running. If your laptop sleeps
  or Jarvis is closed, at most **one** catch-up sync happens per overdue
  provider the next time it starts — missed intervals are never replayed.
* A manual "Sync now" and an automatic sync can never run at the same
  time for the same provider.
* A sync failure never marks the integration disconnected — it's recorded
  with a bounded retry backoff, and a "reconnect required" indicator only
  appears when reauthorization is genuinely needed.
* A bounded local history (last 50 attempts per provider) records what
  triggered each sync, its outcome, and non-sensitive counts — never a
  raw provider response or any credential.
* Calendar automatic sync remains strictly read-only — it never creates,
  updates, or deletes an event. Google Health remains strictly read-only.

## What Phase 10B includes: proactive routines (live and enabled on the real installation)

A fixed, controller-owned set of three routines — **disabled by default on
a fresh install**, each individually enabled and scheduled by you (all
three are enabled on Bernardo's real installation: Morning Briefing daily
08:00, Evening Check-in daily 21:30, Weekly Review Sunday 18:00, all
Europe/London — see `docs/DECISIONS.md` D102). No routine ever calls a
model, changes Calendar or Health data, writes a memory, sends a
notification, speaks aloud, or contacts anyone on its own; the only place
this feature can reach a model is the manual "Discuss with Jarvis" button.

* **Morning Briefing** — a local-time-scheduled summary of today's selected
  Calendar events, active LIFE tasks, upcoming PATH deadlines, and active
  BUILD checkpoints. BODY, MIND, and PEOPLE data appears only if you
  explicitly opt each one in, since those are sensitive contexts.
* **Evening Check-in** — a short, fixed set of four questions (what got
  done, mood, notable events, tomorrow's priority). Your answers are saved
  locally to that check-in only — never automatically turned into a
  permanent memory.
* **Weekly Review** — a structured review of whichever domains you
  explicitly select (every domain requires opt-in here, sensitive or not),
  covering completed work, open threads, upcoming deadlines, and Health
  trends when BODY is included.
* Every line in every routine's output carries a source reference back to
  the record, calendar event, or Health summary it came from.
* Uses the exact same background scheduler as Phase 10A automatic sync —
  no separate loop, no arbitrary cron expressions, timezone/DST-aware, at
  most one catch-up run after downtime, and duplicate-run-proof across
  restarts.
* The Routine Centre (reachable from the top bar and command palette) lets
  you enable/disable each routine, set its schedule and domain selection,
  run it manually, review its history, and — only if you choose — send its
  output into a real conversation via "Discuss with Jarvis." The routine's
  own local summary and any model reply are always visually and textually
  distinguished from each other.
* Implemented and tested against fakes only so far, still pending a live
  restart-safety check. Bernardo's schedule selections are already made and
  recorded (Morning Briefing: daily 08:00 Europe/London, BODY included,
  MIND/PEOPLE excluded; Evening Check-in: daily 21:30 Europe/London;
  Weekly Review: Sunday 18:00 Europe/London, all six domains included) —
  activation is deferred only because no session so far has had access to
  the real Mac runtime to apply them. See `docs/ROADMAP.md`'s Phase 10
  entry.

## What Phase 6 includes: the cinematic HUD and visual system

A single token-driven visual system ("Direction B geometry with Direction C
lighting and atmosphere" — see `docs/DESIGN_DIRECTION.md`) applied across
every screen: deep purple-black backgrounds, a violet/cyan accent language,
circular geometry for the core/domains/state indicators only (never
hexagons), and rounded panels/cards for information-dense screens.

* **Jarvis core** (`frontend/src/components/JarvisCore.tsx`): a layered,
  independently-rotating ring HUD — an outer boundary, a segmented ring, a
  radial tick ring, a counter-rotating inner ring, and a scanning sweep,
  plus a pulsing halo and radial "audio bars" during listening/speaking —
  built from CSS transform/opacity animation (masked conic-gradients, no
  SVG, no JS animation loop). Colour, speed, and which layers are active
  change per real voice state (idle/listening/transcribing/thinking/
  speaking/error); the "JARVIS" label and state text live in their own
  non-rotating layer so they're always upright and readable. The core is
  also a real interactive control ("Talk to Jarvis") — click or Enter/Space
  opens a **general Jarvis conversation**: a genuine, persisted conversation
  scope with `domain_id IS NULL`, not a seventh domain (`domains` still
  seeds exactly six rows). It uses only your global profile by default —
  no domain memories, records, or summaries are auto-retrieved — with six
  optional per-turn domain chips (the same sensitive BODY/MIND/PEOPLE
  acknowledgement as a domain conversation) for explicit, single-turn
  inclusion, and "Remember" always saves a global memory, never a
  domain-assigned one. See `docs/DECISIONS.md` D75.
* **Internal-console design system** (`frontend/src/components/console/`):
  a shared set of primitives (`ConsoleHeader`, `ConsoleModule`,
  `MiniCoreIndicator`, `ContextRail`, `TechnicalDetails`, and others) gives
  every domain conversation, the general conversation, and all six Centres
  one coherent near-black, matte, thin-violet-border interior language —
  cyan reserved strictly for something genuinely live (listening, syncing,
  executing) — replacing an earlier pass that Bernardo correctly flagged as
  reading like "a themed React admin dashboard." Domain conversations were
  restructured into a "cockpit" layout (a wide conversation workspace
  beside a narrower collapsible context rail) as the deepest structural
  change; all six Centres share the new header/surface language, with
  Actions and Skills Centres' existing structure already substantially
  matching their described identity and Memory/Integrations/Routine/Data
  Management still awaiting a fully bespoke per-page layout. See
  `docs/DECISIONS.md` D75 for the exact, honestly-scoped breakdown.
* **Orbital Home**: resting domain nodes show only a name and a short
  fixed subtitle (e.g. BODY: "Health · Training · Recovery") — the full
  domain description appears in a separate panel only when a node is
  hovered/focused, never crowding the circle itself. A faint shared orbit
  path brightens when any node is hovered/focused, idle nodes are
  otherwise genuinely static (no periodic glow), and a brief (~220ms)
  focus/energize transition plays on the selected node before navigating
  into its domain view — short enough to never delay navigation.
* **Shell**: the six management centres are reachable through one
  "Systems" popover instead of six identical top-bar buttons — nothing
  became harder to reach, the header just no longer reads as a row of
  generic pills. A visible `⌘K` button keeps the command palette
  discoverable alongside it.
* **A deterministic, model-independent command layer**
  (`frontend/src/commands/`) lets the Command Palette and spoken voice
  transcripts both recognize navigation commands and aliases ("health
  area" → BODY, "integrations" → Integrations Centre, "go home") without
  ever calling Hermes or a model. A command naming a specific sensitive
  control (Google Calendar/Health connect, disconnect, enable-writing,
  automatic-sync) only navigates there and briefly highlights it — it is
  never auto-clicked. Any other phrase combining a mutating verb
  (connect/delete/approve/execute/etc.) with a recognizable system noun is
  refused with an explanation rather than silently acted on or forwarded
  anywhere. Fully unit-tested (52 cases) as a pure function, independent
  of any UI framework.
* A consistent hover/active/focus/disabled motion system (two duration
  tokens, one easing curve) now applies to every button, nav item, domain
  node, and panel — hover lifts slightly and highlights, pressed scales
  down, disabled never lifts or glows.
* Every animation is disabled under `prefers-reduced-motion` (a single
  global rule), falling back to static colour/text/icon state with no
  loss of meaning or functionality.
* Responsive at 1440×900, 1280×800, 1024×768, and narrower split-screen
  widths — all six domain nodes (including PATH) stay visible and
  non-overlapping, chrome (top/bottom bars) reserves its own layout space
  rather than overlaying content, and long values (scopes, filenames,
  audit entries, calendar titles) wrap safely instead of overflowing.
* Verified so far only inside a temporary, non-persisted Playwright/
  Chromium harness (and, for this refinement pass, an interactive
  hot-reload preview) against fictional fixture data in a secondary
  devcontainer — see `docs/ARCHITECTURE.md` §9f-§9g and `docs/DECISIONS.md`
  D71-D75 for exactly what that covered. **Real-Mac voice hardware
  acceptance is complete** (Bernardo personally performed a real
  push-to-talk question from Home and a real confirm-required voice
  command — D103); a full VoiceOver pass is deliberately deferred to
  installed-app acceptance after native macOS packaging, and genuine
  1280×800/1024×768/820×900 viewport inspection remains outstanding — see
  `docs/ROADMAP.md`'s consolidated real-Mac checklist.

**Real-Mac visual pass: no rectangular panel behind the core, and a real shared-element navigation transition (D90)** — the first real-Mac inspection of the production build found and fixed two defects: a visible rectangular panel behind the central `JarvisCore` (a CSS specificity gap, not a structural issue — a global button-reset rule had never been taught to exclude `.jarvis-hud-interactive`, the one interactive-core class that needed it), and a manually-simulated, `setTimeout`-based domain-navigation delay (up to 220ms, plus a 14%-growth "balloon" scale) standing in for real motion. Every Home→domain navigation path (click, keyboard, number shortcuts, typed/spoken commands, and the reverse "Back to Jarvis") now runs through one shared function (`frontend/src/transitions/domainViewTransition.ts`) built on the real browser View Transitions API — a continuous morph from the selected orbital node into a new small circular emblem in the domain view's own header when Home was actually visible, or a clean default crossfade when it wasn't (e.g. navigating from a Centre page) — with no artificial delay in either case, and a structural (not merely CSS) reduced-motion bypass. See `docs/ARCHITECTURE.md` §9l and `docs/DECISIONS.md` D90 for the full account, including a genuine environment-specific finding (a `document.hidden` automated-tab limitation, not a real defect) documented rather than papered over.

**DomainGlyph: the canonical `lucide-react` icon set, after a real domain-numbering defect found and fixed, and three rounds of hand-drawn iteration (D91-D93, superseded by D94)** — the plain B/M/P/P/B/L first-letter mark inside each domain emblem/node went through three rounds of hand-drawn inline-SVG iteration before Bernardo made a final decision to adopt six specific icons from the official `lucide-react` package as canonical instead: **BODY→`Activity`, BUILD→`Boxes`, LIFE→`CalendarDays`, MIND→`Brain`, PATH→`Compass`, PEOPLE→`UsersRound`** — never a generated PNG, emoji, or a first-letter fallback, and always purely decorative (`aria-hidden`, no `aria-label` of its own). `frontend/src/components/DomainGlyph.tsx` (the one shared component both Home and every domain header render) imports only these six icons by name (never a barrel import, so tree-shaking keeps the rest of Lucide's icon set — well over a thousand icons — out of the production bundle, confirmed by the shipped JS growing only ~1KB gzipped) and renders each with `fill="none"`, `currentColor`, and one shared stroke width so all six read as equally weighted. Building the original hand-drawn version surfaced a real, previously-invisible defect along the way: the domain-header badge and the `1`-`6` keyboard shortcut each carried their own hardcoded domain-order array using the *original* CLAUDE.md narrative order, while Home's own badges number domains by the live API's actual (alphabetical) order — so a domain's number could genuinely disagree between Home, its own header, and which key opened it. `frontend/src/domainOrder.ts` is now the one authoritative mapping (`domainNumber()`/`domainSlugForNumber()`) every surface reads from, unaffected by the later icon change. The icon is the dominant central visual inside each large Home node (scaled proportionally to the node, never a fixed pixel size) and travels via the exact same component into that domain's own header, and the small violet arc-and-dot Jarvis-activity indicator beside the header emblem is only rendered while it's genuinely signaling something, so an idle header shows exactly one identity mark. See `docs/ARCHITECTURE.md` §9m-§9p and `docs/DECISIONS.md` D91-D94 for the full account, including the hand-drawn iteration history and the two durable perceptual lessons (a closed loop around a centered shape reads as an eye; outline asymmetry alone doesn't prevent a "cloud" reading) recorded in CLAUDE.md for any future icon work.

## What Phase 11 includes (complete — real Keychain tested D103; VoiceOver deferred to installed-app acceptance)

Phase 11 is hardening, not new product surface — no backend or frontend behavior changed. Everything below was independently re-checked against the current code in this pass, not re-asserted from an earlier phase's description. See `docs/DECISIONS.md` D81 and `docs/ARCHITECTURE.md` §12 for the full account.

* **Security review**: confirmed every local service binds `127.0.0.1` only (no `0.0.0.0` anywhere), CORS allows exactly one non-wildcard origin, no hardcoded secrets or secret-bearing log statements exist anywhere in the backend or frontend, the frontend never touches `localStorage`/`sessionStorage` (it doesn't call it at all), the Hermes bearer token is never exposed by any API response, and schema-version rejection (`app/migration_info.py`) genuinely enumerates the full known-revision history rather than only comparing to head. One correctness gap (not a vulnerability) was found: CORS's `allow_methods` omitted `PUT`, which blocked a cross-origin `npm run dev` call to a `PUT` endpoint (domain summary, integration/routine schedule) — invisible in production, since Phase 7 serves the frontend same-origin. Fixed as an isolated follow-up correction (`PUT` added to the explicit allow-list, still no wildcard origin or method) — see `docs/DECISIONS.md` D82.
* **Accessibility pass**: a full axe-core (WCAG 2 A/AA) sweep across Home, populated and empty Domain views, the general conversation, all six Centres, the command palette, the 404 diagnostic, and the Controller Offline diagnostic — zero violations anywhere. A keyboard-only Tab sweep confirmed a complete, logical focus order from Home.
* **Restoration drill**: a genuine live drill (real `jarvis-cli`, two real backend processes, two isolated data directories) populated an installation with data across every subsystem reachable without Hermes/OAuth, exported it, restored it into a clean installation, and ran 15 integrity assertions against the restored copy — all passed, including both restore-time safety-forcing behaviors (a never-approved action proposal forced to `expired`; an enabled routine schedule forced back to disabled).
* **Real Keychain and Hermes reconfirmation (D103)**: `KeychainCredentialStore` was exercised for real, against a uniquely-named temporary test entry only (create/read/update/delete, plus an independent post-delete absence check via both the raw `keyring` package and the macOS `security` CLI) — the real `jarvis.google_calendar`/`jarvis.google_health` entries were confirmed present and untouched throughout, and no real credential was ever read, displayed, or altered. The Hermes gateway was reconfirmed loopback-only with all toolsets still disabled. A full manual VoiceOver pass remains deliberately deferred, at Bernardo's explicit direction, to installed-app acceptance after native macOS packaging — not claimed as passed.

### Running the backend test suite in a Linux devcontainer (no macOS `.venv` needed)

`backend/.venv` may be a macOS-built virtualenv that a Linux container can't use. Rather than modifying it, provision a separate, disposable one with `uv` itself:

```bash
curl -LsSf https://astral.sh/uv/install.sh | sh   # if uv isn't already installed
cd backend
uv python install 3.12   # a complete CPython — a container's system python3 may be a stripped build missing tomllib/http/ensurepip
UV_PROJECT_ENVIRONMENT=/tmp/jarvis-backend-venv uv sync --group dev --python 3.12
UV_PROJECT_ENVIRONMENT=/tmp/jarvis-backend-venv uv run --python 3.12 pytest -q
```

This never touches `backend/.venv` and can be deleted (`rm -rf /tmp/jarvis-backend-venv`) at any time with no effect on the real project.

## V1 reliability and intelligence audit

A cross-cutting adversarial review (not tied to a single phase) across failure/recovery, natural-language command safety, memory/context, and scale, covering everything already implemented in Phases 1-10B. Found and fixed three backend defects — a crashed action proposal could get permanently stuck instead of recovering at the next startup, SQLite writes lacked an explicit `busy_timeout` (risking an unhandled error under ordinary concurrent use on some platforms), and a malformed Google Calendar/Health API response could abort an entire sync — and two frontend defects — a question about a voice/typed command, or an explicitly negated one, could execute the real command immediately rather than being recognized as merely explanatory. A fictional full year of heavy personal use (240 conversations, 1,920 messages, 745 memories, 360 records) benchmarked at a 1.98MB database with every operation completing in milliseconds — no scale defect found. See `docs/DECISIONS.md` D83/D84 and `docs/ARCHITECTURE.md` §13 for the complete risk register and every fix.

## What Phase 12A includes: the current situational briefing

When Jarvis opens, Home now shows a concise, deterministic **situational briefing** below the orbit — up to five NOW (immediate/overdue) / NEXT (upcoming soon) / WATCH (failing, stale, or pending) items, each with a real source reference. It is assembled entirely locally: no model call, no Hermes call, no action proposal, no mutation of any kind — see `docs/ARCHITECTURE.md` §15 and `docs/DECISIONS.md` D86 for the full design.

* **Sources**: selected Google Calendar events today, open LIFE tasks and PATH deadlines with a parseable due date, pending/failed action proposals (aggregated counts only, never per-proposal content), failed/stale integration syncs, failed routine runs, a very-recent BUILD checkpoint, and Google Health staleness — the last only when explicitly opted in (`GET`/`PUT /api/briefing/settings`).
* **Privacy**: BODY is included by default (matching Bernardo's already-recorded Phase 10B selection); MIND and PEOPLE are never read by this feature at all, regardless of any setting — there is no code path from either domain's tables into the briefing assembler.
* **Shared logic, not a second engine**: the same underlying data-gathering functions (`app/briefing_service.py`) are now also used internally by the pre-existing Phase 10B Morning Briefing routine, so the two features can never silently disagree about the same facts.
* **Home UI**: a slim "mission strip" below the orbit (never a large generic card), with Refresh, Discuss with Jarvis (opens a real conversation, only reachable this way), and Read briefing aloud (reuses Phase 5's existing text-to-speech path; never plays automatically).
* **Status**: implemented and verified with the full backend/frontend test suites (27 new backend tests, 7 new frontend tests) and a container Playwright/Chromium QA pass (zero overflow, zero axe-core violations, at all four supported viewports) against fictional fixture data. Not yet exercised against Bernardo's real `~/JarvisData`/real Calendar/Health data — that data-shape confirmation, and one real-hardware "Read briefing aloud" check, remain outstanding (see `docs/ROADMAP.md`'s Phase 12A entry). No routine, Hermes toolset, credential, schedule, or OAuth configuration was touched by this phase.

## What Phase 12B includes: briefing continuity, change detection, acknowledgement, and snoozing

The Home briefing (Phase 12A) now remembers its own state across visits instead of repeating the same picture every time. Every item carries a real, deterministically-computed **NEW / CHANGED / ONGOING / RESOLVED / REOPENED** status, and Bernardo can **Acknowledge** or **Snooze** an item — both a local presentation preference only, never a mutation of the underlying Calendar event, task, action, integration, routine, or Health record. See `docs/ARCHITECTURE.md` §16 and `docs/DECISIONS.md` D87 for the full design.

* **Two identifiers per item**: a stable identity (the same underlying concern across time, e.g. one integration's sync health) and a content fingerprint (only the specific fields worth noticing, e.g. title/due-date/urgency-tier) — comparing both against a persisted per-identity ledger is what produces the change status, never a model's judgment.
* **False-resolution protection**: if a source's read genuinely fails, its previously-shown items are never marked resolved and never lose their acknowledge/snooze history — "no data this pass" is never confused with "this got fixed."
* **Home and Morning Briefing never share a baseline**: the routine records its own separate, lightweight audit snapshot; only Home's own view/refresh calls ever update the ledger that change-state classification is computed against.
* **Snoozing** offers exactly four fixed, server-validated durations (1 hour, 4 hours, until tomorrow morning, 1 week — DST-safe) — never an arbitrary timestamp — and expires automatically. Both acknowledging and snoozing automatically stop applying the moment the item's underlying facts genuinely change, and both are visible and reversible in a compact "Acknowledged & snoozed" history.
* **Status**: implemented and verified with the full backend/frontend test suites (53 new backend tests, 8 new frontend tests) and a container Playwright/Chromium QA pass (zero overflow, zero axe-core violations even with the history and a snooze menu expanded, at all four supported viewports) against fictional fixture data. Not yet observed against real data changing over genuine elapsed real-Mac time. No routine, Hermes toolset, credential, schedule, or OAuth configuration was touched by this phase.

## What Phase 12C includes: Mission Focus — a small, user-owned priority watchlist

A small "Mission Focus" list — at most five things Bernardo has explicitly chosen to prioritize, shown as a compact rail below the situational briefing. This is deliberately not an autonomous task manager: Jarvis never pins, unpins, reorders, or picks a priority on its own. See `docs/ARCHITECTURE.md` §17 and `docs/DECISIONS.md` D88 for the full design.

* **Every pin is a typed reference to a real existing source** — a LIFE task, a PATH deadline, a BUILD checkpoint, a selected Calendar event, or an unresolved action proposal — never a copy of it and never a free-form note. Pinning/unpinning/editing/reordering are direct local actions (never the Phase 8 approval lifecycle) and never touch the underlying record: unpinning never deletes or completes anything, and editing only ever changes Mission Focus's own next-action/target/blocker text.
* **At most five active pins, enforced by the database itself** — not just application code — via a real SQLite trigger and partial unique indexes, closing the race a plain "count, then insert" check can't fully close alone.
* **Fully integrated into the Phase 12A/12B briefing assembler**, never a second, disconnected widget: a pin gets real new/changed/ongoing/resolved/reopened classification, participates in acknowledge/snooze (acknowledging or snoozing a pinned briefing item never unpins it), and gets a modest priority boost that can never outrank a genuine failure or real urgency signal.
* **Privacy stays structural**: a pin's domain is always resolved from the real source, never accepted from the client — MIND/PEOPLE content cannot be pinned, verified even against a direct-database-insert bypass attempt.
* **"Add to Mission Focus"** appears on each eligible source's own screen (LIFE/PATH/BUILD records, Actions Centre, Integrations Centre's Calendar events); **"Discuss Mission Focus with Jarvis"** is the only path anywhere in this feature that can reach a model.
* **Status**: implemented and verified with the full backend/frontend test suites (64 new backend tests, 18 new frontend tests) and a container Playwright/Chromium QA pass (zero overflow, zero axe-core violations, at all four supported viewports) against fictional fixture data. Not yet exercised against Bernardo's real `~/JarvisData`/real LIFE/PATH/BUILD/Calendar/Actions data. No routine, Hermes toolset, credential, schedule, or OAuth configuration was touched by this phase.

## Mission Control / Current Focus: a single, timed focus session (not Phase 12D — a bounded extension of Phase 12A-12C)

A persisted, timed "Current Mission" — one at a time, answering "what should I do now?" This is deliberately not a task manager, Kanban board, or a second briefing/prioritization engine: it reuses Phase 12A's exact same NOW/NEXT/WATCH assembler for candidates and Phase 12C's exact same source-resolution logic for "start from a real item." See `docs/ARCHITECTURE.md` §18 and `docs/DECISIONS.md` D95/D96 for the full design, including six real defects found and fixed along the way (three during implementation, two during real-Mac acceptance, one pre-existing Command Palette gap found during implementation).

* **At most one session may be active or paused at a time, enforced by the database itself** — a partial unique index, proved directly against a raw connection bypassing the service layer, closing the same kind of race Mission Focus's 5-pin trigger closes for its own invariant.
* **The timer is always derived from real timestamps**, never a stored or decrementing countdown — `started_at`, `paused_at`, and accumulated paused time are the only source of truth, so an ordinary restart is accurate automatically, and the frontend re-derives the identical formula rather than trusting its own interval.
* **Ending a mission (complete or abandon) never mutates the underlying Calendar event, task, or record** it was started from — those stay entirely separate, verified directly by completing a mission and confirming its source record is byte-for-byte unchanged.
* **An export/restore into any installation forces an in-flight session into a safe, clearly-labeled `abandoned` state** rather than silently letting it keep running against data that's no longer live — mirroring the same safety measure already applied to in-flight action proposals, integration connections, and schedules. An ordinary restart is untouched by this and preserves an active session exactly as-is.
* **Reachable from Home, a domain page, the command palette, or voice** — seven new safe, local, never-confirm-required commands (start/pause/resume/complete/abandon, plus showing the current mission or its history), each routed through the existing command-safety gate so negated ("don't start a focus session") and clarifying-question ("what happens if I finish this?") phrasings correctly don't execute anything.
* **Privacy stays structural**: candidates can never include MIND/PEOPLE content, for the same reason Phase 12A's briefing itself never reads those sources — regardless of any settings flag's value. No model/Hermes call happens anywhere in the ordinary start/pause/resume/complete/abandon lifecycle; "Discuss with Jarvis" remains the only path that can ever reach a model.
* **Status**: implemented, container-verified, and **real-Mac accepted for lifecycle, persistence, privacy, restart continuity, export/restore, command-parser safety, and source immutability** against Bernardo's actual `~/JarvisData` — full backend/frontend test suites (671/671 backend, 328/328 frontend) plus clean typecheck/lint/production build on both sides, a real backup/export/checksum before migration, migration 0015 applied live via the ordinary `jarvisctl.sh` flow, a full data-integrity comparison (zero loss, integration scopes reconfirmed unregressed), a real lifecycle drill against a real Calendar event, a real restart-continuity check, and a real export/restore drill into an isolated destination. Two real defects were found and fixed live (Home's Mission Control strip not refreshing immediately after a command/voice action; keyboard focus dropping to `<body>` after starting a mission from the manual form) — see `docs/DECISIONS.md` D96. **The real microphone voice-command check is now closed** — Bernardo personally performed a real push-to-talk question from Home and a real confirm-required voice command (D103), covering Mission Control's seven voice commands as part of that. Genuine 1280×800/1024×768/820×900 breakpoint inspection remains outstanding (the automation environment cannot actually change the real viewport size, reconfirmed D103). No routine, Hermes toolset, credential, schedule, or OAuth configuration was touched at any point.

## Phase 12D — Unified Recall and Provenance: deterministic local search across every domain

One fast, local place to search everything Jarvis has stored and open the exact underlying source — never a model feature. See `docs/ARCHITECTURE.md` §19 and `docs/DECISIONS.md` D98 for the full design.

* **Deterministic local retrieval only** — search never calls Hermes, never generates a summary, never infers a fact, never executes a command, and never treats retrieved text as an instruction, no matter what that text says. Ranking is one fixed, documented pipeline (text relevance, exact-phrase match, domain match, a bounded recency nudge, a stable tie-break) — never embeddings, never a similarity model.
* **Reuses FTS5 wherever it already existed** rather than duplicating content into a second index: memory items and document-chunk text keep using their existing `memory_fts`/`document_fts` tables unchanged; one new table, `recall_fts`, covers everything else (conversations, messages, structured records, domain summaries, document names, cached Calendar events, action proposals, routine run outputs, and Mission Control sessions).
* **Every result has exactly one owning domain, or an explicit global/system label** — never ambiguous. BODY, MIND, and PEOPLE never appear unless explicitly requested; the default view searches only LIFE, PATH, and BUILD, and opening Recall from inside a domain defaults to searching only that domain.
* **The index is derived and rebuildable, never authoritative** — kept live-synchronized on every relevant create/update/archive/delete across the codebase, backfilled automatically for an installation upgrading from before this phase, and repairable on demand. A deleted or archived source is truthfully reported as unavailable rather than left as a "ghost" result.
* **Status**: implemented and fully tested end to end — backend (78 new tests, full suite 940/940 as of D102, `ruff check` clean) and frontend (30 new tests, full suite 430/430, `tsc -b`/`vite build`/`oxlint` all clean). Reachable from the Systems menu, the command palette ("search Jarvis for X", "find X in my memories", "look up X in `<domain>`"), a domain page's own "Search this domain" button, and a new Cmd/Ctrl+Shift+F shortcut. **Real-Mac search acceptance done (D102)**: `GET /api/recall/search` exercised against the real, populated database with correct domain scoping and highlighting. The palette/voice search phrasing has not yet been exercised with a real microphone — folded into Phase 6's outstanding real-hardware voice item.

## Phase 12E — Source-Grounded Research Workspace: evidence collection and cited briefs, built on Recall

Lets Bernardo collect explicitly selected evidence (found through Phase 12D Recall, including imported-document passages) into a named research workspace, classify it, attach his own notes, and generate a versioned, cited brief from only that selected evidence — never unrestricted web research, never an autonomous agent, and never a second search/indexing engine. See `docs/ARCHITECTURE.md` §20 and `docs/DECISIONS.md` D99 for the full design.

* **Evidence discovery always delegates to Recall's own search**, scoped to the workspace's own domain policy — no parallel query/ranking implementation. Evidence is always a typed pointer to a real, already-existing source, never a copy of its live content; a frozen citation-safe snapshot is captured at add-time, but current availability is always re-checked fresh when a brief is reopened.
* **The same LIFE/PATH/BUILD-by-default domain boundary Recall itself uses applies per workspace** — BODY/MIND/PEOPLE evidence can only ever enter a workspace whose policy explicitly names that domain, and an explicit empty policy is honored literally, never silently widened.
* **A deterministic evidence outline always works with no model call.** The one path that can reach a model, "Draft with Jarvis," makes exactly one bounded request with no tools enabled and no context beyond the workspace's own selected evidence, and is always clearly labeled a model-generated draft. Retrieved evidence — including anything phrased as an instruction to an AI — is always treated as inert, displayed data, never as something that can change a system prompt, trigger a tool, or create a mutation.
* **Citations are stable numbers the server itself validates** — a citation is only ever trusted if it was assigned from evidence genuinely in the workspace; a hallucinated or invalid citation is rejected or visibly flagged, never presented as real support for a claim. A model-call failure never corrupts or loses the workspace, its evidence/notes, or any existing brief version, and regenerating a brief always adds a new version rather than overwriting the last one.
* **Status**: implemented and fully tested end to end, with zero open findings — backend (80 new tests including two AST-walk structural-safety tests, full suite **829/829**; `ruff check` clean beyond two pre-existing project-wide warning categories) and frontend (35 new tests including 8 dedicated WCAG-contrast regression tests, full suite **393/393**, `tsc -b`/`vite build`/`oxlint` all clean). A corrective pass root-caused and fixed the two findings an earlier container QA sweep had left open — four `test_hermes_profile_export.py` failures (a test-fixture shebang resolving to a stdlib-stripped system Python via inherited `PATH`, not a real backend defect) and one axe-core color-contrast reading on the shared `--text-tertiary` design token (corrected centrally, verified against every Centre using it) — see `docs/DECISIONS.md` D100. Reachable from the Systems menu, the command palette, and spoken/typed "open research"/"show research centre" (navigation only — no autonomous research action). **Real-Mac acceptance done (D102)**: a labeled `[ACCEPTANCE TEST]` workspace was created against real LIFE/PATH/BUILD content, real evidence was added via real Recall search, a deterministic outline was generated, and one real "Draft with Jarvis" call was made against the real GPT-5.6 Terra model — correctly labeled, correctly cited, no mutation of any kind. A real export/restore drill confirmed the brief survives byte-identical, with no regeneration. The palette/voice "open research" phrasing has not yet been exercised with a real microphone — folded into Phase 6's outstanding real-hardware voice item.

## Phase 12F — Evidence-Based Decision Room: transparent, evidence-grounded decisions, completing Recall → Research → Decide → Focus

Lets Bernardo weigh a real decision — options, criteria, evidence, assumptions/risks/unknowns — with a deterministic, inspectable score, optionally challenge it with one bounded Jarvis critique, record the actual final choice, and later review how it turned out. Built entirely on Phase 12D Recall and Phase 12E Research; Jarvis supports the decision, it never makes it. See `docs/ARCHITECTURE.md` §21 and `docs/DECISIONS.md` D101 for the full design.

* **Evidence discovery always delegates to Recall's own search**, and when a decision links a Research workspace, the effective search scope is the **intersection** of the decision's own domain policy and the workspace's — never their union, so linking a workspace can only narrow access, never widen it.
* **Scoring is a plain, transparent weighted sum, never a hidden formula or a claim of objective truth.** An unscored option/criterion pair is reported as "unassessed," never defaulted to zero; a tied result, or a ranking that depends heavily on one criterion's weight, is flagged plainly rather than smoothed over.
* **Jarvis supports the decision; it never makes it.** Only Bernardo's own explicit action ever records a final decision (option, rationale, confidence). "Ask Jarvis to challenge this decision" makes exactly one bounded, tool-free critique with its own server-validated citations — structurally a separate record from the final decision itself, so it can never set status, choose an option, or decide anything.
* **Outcome review is a separate, additive record** — reviewing how a decision turned out never edits the original rationale. A calibration summary is only ever shown once enough decisions have been reviewed to mean anything statistically.
* **Status**: implemented and fully tested end to end, with zero open findings — backend (111 new tests including three AST-walk structural-safety tests, full suite **940/940**; `ruff check` clean beyond three pre-existing project-wide warning categories, confirmed by a full-repo comparison) and frontend (37 new tests, full suite **430/430**, `tsc -b`/`vite build`/`oxlint` all clean). This pass's own container QA found and fixed two genuine defects before reporting complete: every multi-field form (details, decide, add-factor, outcome review) initially rendered its labels overlapping, since no earlier Centre's forms needed a stacked layout — fixed with one new CSS utility; and the assessment matrix never read or displayed a previously-set score — fixed by wiring in the existing `listDecisionAssessments` endpoint the frontend had defined but never called. See `docs/DECISIONS.md` D101 for the complete account, including a deliberate scope trade-off (Mission Control's "Focus on this decision" reuses the existing `manual` source type rather than a deeper integration, explicitly permitted by the spec) and two pre-existing defects found and fixed along the way. Reachable from the Systems menu, the command palette, and spoken/typed "decision room"/"open decisions" (navigation only — no autonomous decide/score/evidence action). **Real-Mac acceptance done (D102)**: a labeled `[ACCEPTANCE TEST]` decision was scored (correctly reporting a missing assessment and a sensitivity warning rather than hiding either), decided, and challenged with one real critique call against the real GPT-5.6 Terra model — correctly labeled, changed no lifecycle state. Read-only enforcement on a decided decision was confirmed to correctly reject a mutation attempt. A real export/restore drill confirmed full survival with no regeneration. The palette/voice "decision room" phrasing has not yet been exercised with a real microphone — folded into Phase 6's outstanding real-hardware voice item.

## Explicitly out of scope for Phase 1-6, 7-10B

Automatic memory extraction from conversation (memory is deliberate/explicit
only), semantic/embedding-based retrieval, a custom wake word or any
continuous/always-listening microphone mode, Hermes skills/tool
behaviour beyond approval-gating (all Hermes toolsets remain disabled),
sub-agents (deliberately excluded from V1, reconsidered only after Phase 11
if a concrete use case emerges), email, Telegram/Discord/other messaging
gateways, contacts, smart-home control, arbitrary filesystem access
(documents are explicit-upload only), browser automation, terminal/code
execution, macOS notifications for routines, automatic TTS for routines,
calendar attendees/invitations/recurring events/sharing changes, and any
Google Health write capability. A full recurring backup scheduler and an
encrypted-secrets export are also deferred. See `docs/ROADMAP.md` for the
full phase sequence.
