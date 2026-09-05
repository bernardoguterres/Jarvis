# Jarvis HUD - Visual Direction

This is the durable record of Jarvis's visual design decisions and the reasoning behind them, referenced directly by `CLAUDE.md`'s Frontend Aesthetics Doctrine. For the blow-by-blow history of each visual pass (exact defects found, exact before/after values), see `docs/DECISIONS.md`. This file keeps the doctrine and the reasoning behind it.

## Source

The original exploration was done in Claude Design:
* https://claude.ai/design/p/62a64ee0-4904-4926-9e44-dfae00be07c8

That project remains the canonical visual reference; this file is a text record of the decision, not a substitute for it.

## Direction

**"Direction B geometry with Direction C lighting and atmosphere."**

* Circular domain nodes only, no hexagons.
* Direction B's orbital proportions, spacing, hierarchy, labels, and keyboard shortcuts.
* Direction C's purple-black palette, violet central glow, cyan/teal accents, shadows, depth, and voice-state effects.
* Inactive domains stay visually restrained.
* Strong illumination is reserved for the central Jarvis element, the active domain, and meaningful system state (listening, thinking, speaking), never decorative or constant.

This was implemented in Phase 6, after the functional capabilities (voice, permissions, hooks, skills) were stable, per the project's own "don't implement later phases early" rule.

## Why Jarvis needs its own visual grammar, not generic AI/SaaS styling

This isn't a hypothetical concern; it's a failure mode that actually happened on this project (see D75) and is why `CLAUDE.md`'s aesthetics doctrine exists.

**Why "AI slop" happens.** Left without product-specific constraints, both AI-generated frontend work and default component libraries converge on the same handful of patterns: a rounded card per section, a gradient hero banner, glassmorphism, evenly-distributed accent colors. That's the path of least resistance, the median "modern app" pattern, not a decision grounded in what the screen actually does. That's exactly what happened here: internal pages were functionally correct but visually indistinguishable from a themed admin dashboard, because every screen had been solved the same generic way regardless of what it showed.

**The alternative**: every visual decision must be justifiable by something only Jarvis actually has: six real context spaces, real voice states, a real local-first architecture, a real approval lifecycle for anything Jarvis itself proposes. A structure chosen because it looks contemporary rather than because it's the right shape for the data it shows is the thing to redesign.

**Cinematic states vs. calmer operational screens.** Home, the central core, voice states, and full-page fault states are the instrument face: rare, high-stakes moments (opening Jarvis, speaking to it, something genuinely failing) that earn cinematic geometry and motion. Domain conversations, the general conversation, and the Centres are the control room: where real time is actually spent, dense and calm rather than spectacular, because cinematic treatment applied everywhere is exhausting. Both are unmistakably Jarvis; only the register differs.

**Color semantics** (defined once here, never restated with a different meaning elsewhere): violet is Jarvis and core intelligence; cyan/teal is focus, a successful connection, active or confirmed state; amber is waiting or degraded; red is genuine failure or a destructive action. A screen that distributes accent colors evenly just to look lively is misusing this system, not applying it.

**Motion hierarchy.** State-communicating motion (the core's voice states, a waveform genuinely reacting to audio, a sync in progress) is the only motion that runs continuously. Interaction feedback (hover, press, focus) is momentary and tied to a real event. Anything purely decorative is disallowed. Hover carries a small, deliberate delay (roughly 90-120ms) so a pointer moving across the screen doesn't light up everything it crosses; keyboard focus never carries this delay, since a keyboard user isn't "passing through."

**Why repeating identical cards is banned as the default.** Solving every section of every page with the same rounded-card treatment is precisely what makes a personal instrument read as generic. A live approval queue, a conversation transcript, a sync status, and a schedule each need a different structure. See `CLAUDE.md`'s "Internal screens" doctrine for the vocabulary to reach for instead.

**Verify visually, not just by source.** Source code can look entirely correct, the right classes, the right components, while still rendering into the generic result, because "looks generic" is a property of the rendered composition, not any one line of code. A screen is only evaluated once inspected at real viewports, in its real interactive states.

## Internal-console design language

The orbital brief above was written for Home. Once the internal pages (domain conversations, the general conversation, all six Centres) reused Home's literal visual weight (large rounded cards, a purple-gradient hero per page), it read as a generic themed admin dashboard rather than the interior of the same instrument. The resolved direction for interior pages, deliberately distinct from Home's own atmosphere:

* A near-black, flat canvas with a faint fixed grid texture, not a continuation of Home's atmospheric glow.
* Matte module surfaces with a thin 1px violet border and a smaller corner radius than Home's circular language: instruments, not cards.
* Cyan reserved strictly for a module genuinely live right now (listening, syncing, executing), never a default accent.
* A small circular status glyph in place of a large decorative core wherever an interior page needs a system-status presence.
* Calmer motion than Home's: entrance-only transitions, no permanently rotating decoration, hover as a border/foreground response rather than a card lift.

Home's own geometry, palette, and ring system are unchanged by this; it governs only what a page looks like once you've left Home.

**A further pass** added a small operational-component vocabulary reused across the Centres wherever the content shape actually calls for it: compact ledger rows for a list of like items, a connected-dot timeline for an audit trail or run history, a status-cluster strip for a provider/schedule overview at a glance, a left-border accent for queue priority (never opacity or color alone), a segmented tab row restyled from a plain radio-button group, a collapsed-by-default builder surface for an authoring form, and a numbered tier hierarchy for a storage/backup narrative. None of this introduces a new color or panel geometry; it's additional composition vocabulary for arranging the existing language to fit what a screen actually shows.

## Home's situational-briefing strip

A slim, dense panel of up to five real, source-backed items sits quietly below the orbit, never a large card, never positioned so it competes with the core for attention. It borrows the console interior's matte surface and thin violet border rather than Home's own atmospheric glow, since its content is closer in kind to what a Centre shows, but stays visually subordinate by living below the core at a smaller scale with no animation of its own. Every item shows an explicit text badge for urgency and a left-border tone accent, reusing the same left-accent convention already established for the Actions Centre queue rather than inventing a second language. The strip has exactly three actions and no per-item icon set or progress indicator; a genuinely empty result renders the literal sentence "No immediate items," never a fabricated suggestion.

That strip later gained a second badge dimension (new/changed/ongoing/resolved/reopened), kept visually distinct from the urgency badge since conflating the two would force one color to carry two unrelated facts. New/resolved use cyan, changed/reopened use amber, and ongoing (deliberately the quietest choice, since most items settle here after the first pass) renders with no fill or border at all, just muted text. Acknowledge and a snooze disclosure sit beside the navigate button, never inside it, since a resolved item shows neither control and mixing "go there" with "dismiss this" in one hit target invites accidental dismissal. A closed-by-default history discloses acknowledged/snoozed items with one explicit sentence that neither ever touches the underlying record.

A small watchlist rail (Mission Focus) sits below that: a plain numbered badge per row, since the order is Bernardo's own explicit choice, not a computed score, so no star or flame icon implying Jarvis assigned importance. It reuses the same change-state badges, since a pin is a briefing item under the hood. A blocker or target date shows only when present, never as an empty placeholder. The top three show by default, the rest behind the same closed-disclosure mechanism as the acknowledge/snooze history.

## Domain icons

Every domain node originally carried only a single letter (with two real collisions: BODY/BUILD and PEOPLE/PATH). A bespoke hand-drawn six-icon family was attempted first, deliberately avoiding a stock icon library to avoid the generic-admin-dashboard failure mode. Three iteration rounds each fixed a real problem the last one introduced without reaching a finished result: a "network" icon that read too generically, a compass needle that read as GPS navigation, a calendar-and-orbit mark where the orbit and calendar visually knotted together, several MIND attempts that read as a cloud or a flower, and a PEOPLE attempt that read as a restroom pictogram.

Two durable, genuinely reusable lessons came out of that process, worth keeping for any future icon work even though they no longer apply to a specific glyph: a closed loop fully enclosing a centered shape reads as an eye almost regardless of intent (fix: use an open arc, which makes the misreading structurally impossible rather than just unlikely); and an asymmetric outline alone doesn't stop a shape from reading as a cloud, since the number and uniformity of small bumps around an outline does that on its own (fix: fewer, larger segments plus one clearly distinct feature, like a stem, that no cloud silhouette has).

After three rounds, Bernardo made the final call to stop redrawing and adopt six specific, named icons from `lucide-react` as canonical: BODY-`Activity`, BUILD-`Boxes`, LIFE-`CalendarDays`, MIND-`Brain`, PATH-`Compass`, PEOPLE-`UsersRound`. A well-chosen icon from a mature, widely-used set, recolored to Jarvis's own violet/cyan language and never carrying its own background, glow, or animation, still reads as native, since the surrounding HUD chrome (the ring, the glow, the state color, the orbital layout) is what makes something feel like Jarvis, not the icon's linework alone. This is now the canonical, fixed set; see `CLAUDE.md`'s domain-iconography section before ever redrawing or replacing one of these six.
