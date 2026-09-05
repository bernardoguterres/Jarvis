# Jarvis

A private, local-first, voice-controlled personal assistant for daily use,
divided into six life domains, running primarily on Bernardo's own Mac.
Personal data stays local. The reasoning model is a swappable,
model-independent component, not something baked into the app.

**Status: V1 is feature-complete and frozen.** Jarvis is packaged as a
native macOS app, backed by a FastAPI backend and a React frontend, with
local voice, local memory, and a handful of deterministic tools built on
top of a local search index. Two items remain outstanding: a full
VoiceOver pass and a real-viewport visual inspection, both blocked on
manual acceptance rather than code. See `docs/ROADMAP.md` for the
complete phase-by-phase history and current status, and `docs/DECISIONS.md`
for every non-obvious decision and bug fix made along the way.

## What it does

* **Six life domains** (Body, Mind, People, Path, Build, Life), each with
  its own conversation history, structured records, and long-term memory,
  stored in Jarvis's own SQLite database.
* **Explicit push-to-talk voice.** Hold Space (or a button) to record,
  local `faster-whisper` transcribes it, the transcript goes through the
  normal turn flow, and the reply is spoken back via Edge TTS. No
  continuous listening, no raw audio kept after transcription.
* **Model-independent memory.** Jarvis never sends a model string to
  Hermes and never depends on which model is configured. Switching
  providers needs zero Jarvis code changes, and memory survives it
  untouched.
* **Controller-owned permissions.** A default-deny capability registry
  and an auditable propose-then-approve-then-execute lifecycle for every
  mutation Jarvis proposes on its own, never for actions you take directly
  through the UI.
* **Google Calendar and Google Health integrations**, read-only except for
  limited owned-calendar writes, all through that same approval lifecycle.
  Credentials live only in the macOS Keychain.
* **Recall**: deterministic local full-text search across every domain.
  No embeddings, no similarity model, never a model call.
* **Research**: collect evidence from Recall into a named workspace and
  generate a versioned, cited brief.
* **Decision Room**: weigh a real decision with a transparent, inspectable
  score. Jarvis supports the decision; it never makes it.
* **Mission Control**: a single persisted, timed focus session, and a
  small Mission Focus watchlist of things you've deliberately chosen to
  prioritize.
* **A current situational briefing** on the home screen, assembled
  entirely locally with no model call.

See `docs/PRODUCT_SPEC.md` for the full product spec and
`docs/ARCHITECTURE.md` for the technical design behind all of the above.

## Tech stack

Backend: Python, FastAPI, SQLAlchemy, Alembic migrations, SQLite.
Frontend: React, TypeScript, Vite. Native shell: Tauri 2, with the backend
packaged as a self-contained PyInstaller sidecar. Reasoning model:
whatever is configured through a dedicated local Hermes Agent profile,
currently GPT-5.6 Terra via OpenAI Codex OAuth. Voice: local
`faster-whisper` for transcription, Edge TTS for speech.

## Where your data lives

Application source code lives in this Git repository. **Personal data
never does.** It lives under `JARVIS_DATA_DIR`, which defaults to
`~/JarvisData`:

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
`~/JarvisData`.** They are intentionally separate. Set `JARVIS_DATA_DIR`
in your environment (or in `backend/.env`, see `.env.example`) to use a
different location.

## Running the native app

Jarvis is packaged as a real native macOS app at `/Applications/Jarvis.app`.
This is the normal way to use it day to day; the `jarvisctl.sh`/browser
workflow below remains available for development and as a recovery
fallback.

* **Open it** from Finder, Spotlight, or the Dock like any other app. No
  Chrome, no terminal, no manually-entered URL. It starts (or reuses an
  already-running) backend silently in the background and waits for it to
  become healthy before showing anything.
* **Menu-bar icon**: Open Jarvis, Hide Jarvis, System Status, Sync
  Integrations, Export Portable Jarvis Backup, Restore from Jarvis
  Export, Reveal Jarvis Data Folder, Launch Jarvis at Login (off by
  default), Quit Jarvis.
* **Closing the window** hides Jarvis rather than quitting it, so
  scheduled integration syncs and routines keep running. Click the Dock
  icon, or "Open Jarvis" from the menu bar, to bring it back.
* **Quit Jarvis** (menu bar, or Cmd+Q) stops only the backend process
  this app itself started. It never touches a `jarvisctl.sh`-started
  backend it didn't spawn, and never leaves an orphaned process behind.
* **Moving to a new Mac**: install `Jarvis.app` there (it starts with an
  empty `~/JarvisData`), use Export Portable Jarvis Backup on this Mac,
  copy the resulting `.zip` over, then use Restore from Jarvis Export in
  Data Management on the new Mac. The app bundle is application code
  only; your real data always stays in `JARVIS_DATA_DIR`.
* **Code signing**: signed with a self-signed certificate that exists
  only on this Mac, never notarized, never distributed.
* **Building it yourself**:
  ```bash
  cd backend && uv run pyinstaller packaging/jarvis_backend.spec --distpath packaging/dist
  cp packaging/dist/jarvis-backend frontend/src-tauri/binaries/jarvis-backend-aarch64-apple-darwin
  cd frontend && npx @tauri-apps/cli@2 build
  ```

## Development setup

**Prerequisites**: Python 3.12+, [uv](https://docs.astral.sh/uv/)
(`brew install uv`), Node.js 20+ and npm.

```bash
# Backend
cd backend
uv sync --group dev
uv run alembic upgrade head
uv run uvicorn app.main:app --reload --host 127.0.0.1 --port 8000
uv run pytest   # run the backend test suite

# Frontend, in a separate terminal
cd frontend
npm install
npm run dev         # dev server at http://localhost:5173
npm run test         # Vitest + React Testing Library
npm run typecheck    # tsc project-reference type-checking
npm run build        # production build, output to frontend/dist

# Or run both together
scripts/dev.sh
```

### Day-to-day / recovery fallback

```bash
scripts/jarvisctl.sh open     # start Jarvis if needed, then open/focus it
scripts/jarvisctl.sh status   # Hermes gateway + backend health
scripts/jarvisctl.sh stop     # stop the Jarvis-owned backend only
```

This is fully idempotent and applies pending migrations and builds the
frontend automatically. Test it safely at any time with
`bash scripts/test_jarvisctl.sh`. See `docs/ARCHITECTURE.md` §10 for how
this relates to the native app above.

## Export, backup, and restore

```bash
cd backend

uv run jarvis-cli export                                  # create a portable export archive
uv run jarvis-cli validate path/to/export.zip              # check an archive without restoring
uv run jarvis-cli restore path/to/export.zip --target ~/JarvisData          # restore into a clean install
uv run jarvis-cli restore path/to/export.zip --target ~/JarvisData --confirm  # restore over an existing one

uv run jarvis-cli backup                    # manual backup (daily by default)
uv run jarvis-cli backup --category weekly
uv run jarvis-cli list-backups
```

Restoration always validates the archive first in an isolated temporary
directory before touching any real data. Restoring over an existing
installation requires `--confirm` and makes a rollback copy first,
automatically. A lightweight due-check runs on backend startup, so an
overdue daily, weekly, or monthly backup gets created automatically.

**Backups on this laptop do not protect you from losing the laptop.**
Periodically copy files from `JARVIS_DATA_DIR/exports/` to an encrypted
external drive or an encrypted Time Machine backup.

## Hermes and model setup

Jarvis talks to whatever model is configured through a dedicated local
Hermes Agent profile named `jarvis`, never a shared or default profile.
Hermes owns the model/provider connection entirely. The FastAPI backend
never sees, stores, or names a specific model in its own requests.

**Currently configured**: GPT-5.6 Terra via OpenAI Codex OAuth,
authenticated against Bernardo's own ChatGPT subscription. No Anthropic
key, no OpenAI API key, and no model credential of any kind exists
anywhere in this project.

```bash
# 1. Install Hermes
curl -fsSL https://hermes-agent.nousresearch.com/install.sh | bash

# 2. Create the dedicated profile (one-time)
hermes profile create jarvis --no-skills --description "Bernardo's personal Jarvis assistant profile"

# 3. Choose a provider and authenticate yourself, in your own terminal
jarvis setup model

# 4. Generate the Hermes API server's bearer token (a separate secret
# from whatever model credential you just configured)
openssl rand -hex 32 >> ~/.hermes/profiles/jarvis/.env   # prefix with API_SERVER_KEY=
chmod 600 ~/.hermes/profiles/jarvis/.env
# then copy the same value into backend/.env as HERMES_API_BEARER_TOKEN=...

# 5. Lock down the profile's tool surface to conversation-only
jarvis tools disable web browser terminal file code_execution vision image_gen delegation cronjob session_search todo --platform api_server
jarvis config set memory.write_approval true
jarvis config set skills.write_approval true
jarvis config set gateway.api_server.max_concurrent_runs 1
jarvis config set curator.enabled false

# Verify what's actually enabled
jarvis tools list --platform api_server

# Start / stop / check the gateway
scripts/hermes-gateway.sh start-background
scripts/hermes-gateway.sh health
scripts/hermes-gateway.sh stop
```

Nothing in step 3 should ever be pasted into or read back by an AI
session; that is by design. Update `HERMES_MODEL` in `backend/.env` to
match whatever you configure (a display label only, see `.env.example`).
If Hermes is down or misconfigured, local conversation storage, notes,
domains, and export/backup all keep working; only real Jarvis responses
are unavailable, and the HUD says so.

### Connecting Google Calendar and Google Health

Use two separate Google OAuth Web application clients, one for Calendar
and one for Health, ideally in separate Cloud projects. Google associates
OAuth consent with the (user, Cloud project) pair, not (user, client_id),
so sharing a client or project can let one integration's consent screen
return the other's scopes. Jarvis defensively filters each callback's
scopes to only what that provider actually uses, but two separate clients
avoids the confusion entirely. Full Google Cloud Console setup
instructions live outside this repo, per the rule that Jarvis never asks
you to paste credentials into a chat session.

```bash
cd backend
uv run jarvis-cli configure-integration google_calendar
uv run jarvis-cli configure-integration google_health
```

Then use the Integrations Centre's "Connect" button for each provider.
This opens the real OAuth consent screen in your own browser.

## Explicitly out of scope

Automatic memory extraction from conversation, semantic/embedding-based
retrieval, a custom wake word or any always-listening microphone mode,
autonomous Hermes tools or sub-agents, email/Telegram/Discord/other
messaging, smart-home control, arbitrary filesystem access, browser
automation, terminal/code execution, and any Google Health write
capability. See `docs/ROADMAP.md` for what's deferred and why.

## Further documentation

* `CLAUDE.md`: the full project profile and durable engineering rules.
* `docs/PRODUCT_SPEC.md`: the product spec.
* `docs/ARCHITECTURE.md`: how the current implementation actually works.
* `docs/ROADMAP.md`: phase-by-phase status, complete and outstanding.
* `docs/DECISIONS.md`: an append-only log of every decision and bug fix.
* `docs/DESIGN_DIRECTION.md`: the visual design brief.
