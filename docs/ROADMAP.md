# Jarvis - Roadmap

Subordinate to `CLAUDE.md`. If anything here conflicts with it, `CLAUDE.md` wins.

This is a status tracker: what phase is done and what's left. For the full history of how each phase was built, verified, and what bugs came up along the way, see `docs/DECISIONS.md`.

**V1's feature set is frozen.** Every phase below is complete. Two items remain, both against the installed native app rather than a dev build:

1. **A full manual VoiceOver pass**, deliberately deferred to installed-app acceptance (see D103). A checklist covering Home, one domain, General Conversation, Recall, Research, Decision Room, Actions Centre, and one diagnostic state is ready to run. Not yet done.
2. **Real-viewport inspection at 1280x800, 1024x768, and 820x900**, outstanding since the automation tooling used throughout this project can't actually resize a real browser window. The native app's own window can be resized by hand instead, whenever this is revisited.

## Phases

Actual execution order: 7, then 8, 9, 10, 6, 11 (the HUD was deliberately built last, once the underlying behavior it renders was stable, see D40).

| Phase | Scope | Status |
|---|---|---|
| 0 | Project docs and architecture contract | Complete |
| 1 | Local persistence, six-domain vertical slice | Complete |
| 2 | Export, import, backup | Complete |
| 3 | Hermes profile + model integration | Complete |
| 4 | Domain conversations, context assembly, memory | Complete |
| 5 | Push-to-talk voice | Complete |
| 6 | Functional animated HUD | Complete (D103) |
| 7 | macOS launch shortcut, optional startup | Complete |
| 8 | Permissions, hooks, first skills | Complete |
| 9 | Read-only integrations (+ limited Calendar write) | Complete |
| 10A | Automatic integration resync | Complete |
| 10B | Proactive routines (Morning Briefing, Evening Check-in, Weekly Review) | Complete, schedules active on real data (D102) |
| 11 | Security, portability, accessibility, recovery hardening | Complete |
| 12A | Home situational briefing (NOW/NEXT/WATCH) | Complete, real-data confirmed (D89) |
| 12B | Briefing continuity, change detection, acknowledge/snooze | Complete |
| 12C | Mission Focus watchlist | Complete |
| - | Mission Control / Current Focus session (bounded extension of 12A-12C) | Complete (D95-D97) |
| 12D | Unified Recall (local search) | Complete |
| 12E | Research workspaces | Complete |
| 12F | Decision Room | Complete |
| - | Native macOS packaging, Stage 1 | Complete, installed at `/Applications/Jarvis.app` (D104) |
| - | Cross-Mac portability (in-app restore) | Complete (D105) |

Sub-agents remain a deliberate V1 exclusion (Jarvis stays one assistant with six context spaces, not six agents), to be reconsidered only if a concrete bounded-task need shows up after Phase 11. See D70.

## Post-freeze fixes

A few real-use issues surfaced after Stage 1 packaging shipped and were fixed without reopening any phase:

* Seven real defects reported from daily use of the installed app (icon/tray issues, Keychain re-prompting, a broken OAuth Connect button, a voice-error screen with no way out, denied microphone access, a scroll-hijacking Space key). See D106.
* A diagnostic pass on push-to-talk latency: one real fix kept (transcription no longer blocks the event loop), one attempted fix (eager model preload) reverted after it caused a runaway process-respawn loop on the real Mac. See D107.
* The respawn loop's actual root cause, a missing `multiprocessing.freeze_support()` call in the packaged entrypoint, was found and fixed. See D109.

## Explicitly deferred

ElevenLabs voice, a dedicated always-on device, remote access over a private network, hosted speech services, additional model providers, Telegram, email/calendar write access beyond what Phase 9 already covers, smart-home integration, a custom wake word, and an encrypted-secrets export. Added only if repeated use shows a real need.
