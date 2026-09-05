# Jarvis HUD — Provisional Visual Direction (Phase 4.5 exploration)

**Status: PROVISIONAL. Not an accepted production implementation.**

This document is the local, durable record of a visual-design exploration
done separately in Claude Design, so that a cloud URL is never the only
place this decision is recorded. It captures the *decision text* Bernardo
provided; it is not a reproduction of the actual visual artifacts (see
"Local export" below for why).

## Source

* Claude Design project: https://claude.ai/design/p/62a64ee0-4904-4926-9e44-dfae00be07c8
* Comparison view: https://claude.ai/design/p/62a64ee0-4904-4926-9e44-dfae00be07c8?file=Comparison.dc.html

These URLs remain the canonical visual reference. This file is a text
record of the decision, not a substitute for looking at the actual designs
before implementing them.

## Local export

No local export of the Claude Design artifacts (mockup files, images, etc.)
was performed. This session had no tool access to the Claude Design product
itself (`claude.ai/design/...` is a separate product from Claude Code's
Artifacts, and a direct fetch attempt returned an authenticated-access
error). If Claude Design later offers an explicit export/download of the
reference files, that export should be added under a clearly-labeled
`design-reference/` location outside `frontend/src`, without altering the
production frontend — never inline it into the app itself.

## Provisional direction

**"Direction B geometry with Direction C lighting and atmosphere."**

* Circular domain nodes only — no hexagons.
* Direction B's orbital proportions, spacing, hierarchy, labels, and
  keyboard shortcuts.
* Direction C's purple-black palette, violet central glow, cyan/teal
  accents, shadows, depth, and voice-state effects.
* Inactive domains remain visually restrained.
* Strong illumination is reserved for: the central Jarvis element, the
  active domain, and meaningful system states (e.g. listening/thinking/
  speaking) — not decorative or constant.

## Relationship to the roadmap

This direction is scoped for **Phase 6 — Build the functional animated
HUD** (`docs/ROADMAP.md`). It is explicitly **not** implemented during
Phase 5 (push-to-talk voice) or any earlier phase. Per CLAUDE.md's
sequencing principle ("do not implement later phases early") and
Bernardo's explicit instruction:

* Final frontend implementation and animation polish remain deferred until
  the functional capabilities (voice, permissions, hooks, skills — Phases
  5, 8, and related) are stable.
* Until Phase 6 is actually undertaken, the current plain/unpolished HUD
  (six circles, minimal styling — see `docs/DECISIONS.md` D10) stays as-is.
  Later phases add only what they functionally require to the existing
  frontend (e.g. Phase 5's push-to-talk controls), not visual redesign.
* When Phase 6 begins, this document is the starting brief — but the
  Claude Design URLs above should be reopened and reviewed directly before
  committing to implementation details, since this file only captures the
  decision text, not the actual visual mockups.

## Why Jarvis needs its own visual grammar, not generic AI/SaaS styling

This section exists because the failure mode it describes actually happened
during this project (`docs/DECISIONS.md` D75) — it is not a hypothetical
concern. It also records the permanent doctrine now in `CLAUDE.md`'s
`<jarvis_frontend_aesthetics>` section as project guidance, not just a
one-off correction.

**Why "AI slop" happens.** Left without product-specific constraints, both
AI-generated frontend work and default component libraries converge on the
same handful of patterns — a rounded card per section, a gradient hero
banner, glassmorphism, evenly-distributed accent colors — because those are
the path of least resistance: the median "modern app" pattern, not a
decision grounded in what the screen actually does. That is exactly what
happened here: the internal pages were functionally correct but visually
indistinguishable from a themed admin dashboard, because every screen had
been solved the same generic way regardless of what it actually showed.

**Why Jarvis uses a context-specific visual grammar instead.** Every visual
decision must be justifiable by something only Jarvis actually has: six
real context spaces, real voice states, a real local-first architecture, a
real approval lifecycle for anything Jarvis itself proposes. A structure
chosen because it looks contemporary, rather than because it is the right
shape for the real data/state it shows, is the thing to redesign — see the
`<jarvis_frontend_aesthetics>` doctrine's "Internal screens" and
"Evaluation" rules.

**Cinematic states vs. calmer operational screens.** Home, the central
core, voice states, and full-page fault states are the *instrument face* —
rare, high-stakes moments (opening Jarvis, speaking to it, something
genuinely failing) that earn cinematic geometry and motion. Domain
conversations, the general conversation, and the Centres are the *control
room* — where real time is actually spent, dense and calm rather than
spectacular, because cinematic treatment applied everywhere is exhausting
and slows down the person trying to get something done. Both are
unmistakably Jarvis; only the register differs. See the "Addendum" below
for exactly how that split was drawn for internal pages.

**Color semantics.** Violet (Jarvis/core intelligence), cyan/teal (focus,
successful connection, active/confirmed operational state), amber
(waiting/degraded), red (genuine failure, destructive action) — defined
once in `CLAUDE.md`'s doctrine and never restated with different meanings
elsewhere. A screen that distributes accent colors evenly just to look
lively is misusing this system, not applying it.

**Motion hierarchy and the hover-delay philosophy.** Motion sits on a
strict hierarchy: state-communicating motion (the core's voice states, a
waveform genuinely reacting to audio, a sync in progress, an approval
executing) is the only motion that runs continuously; interaction feedback
(hover, press, focus) is momentary and tied to a real event; anything
purely decorative is disallowed. Hover specifically carries a small,
deliberate delay (tuned in D75's motion pass — roughly 90-120ms before a
hover state visibly activates) precisely so a pointer moving across the
screen doesn't light up everything it crosses; keyboard focus never carries
this delay, since a keyboard user is never "passing through." This is a
restraint mechanism, not decoration for its own sake.

**Why repeating identical cards is banned as the default solution.** D75's
correction is the concrete, lived example: solving every section of every
page with the same rounded-card treatment is precisely what makes a product
this personal read as generic. Different information (a live approval
queue, a conversation transcript, a sync status, a schedule) needs a
different structure — see `<jarvis_frontend_aesthetics>`'s "Internal
screens" list for the vocabulary to reach for instead.

**Why screenshots and live interaction states matter, not just source
review.** Source code can look entirely correct — the right classes, the
right components — while still rendering into the generic result, because
"looks generic" is a property of the rendered composition, not of any
single line of code. A screen is only actually evaluated once it has been
inspected at real supported viewports, in its real interactive states
(hover, focus, active, loading, error), the way D75's and every subsequent
visual pass in this project were verified.

**Relationship to the Claude Cookbook.** The "Prompting for frontend
aesthetics" Cookbook article is an influence on *methodology* — asking
specific, product-grounded questions, avoiding generic instructions,
verifying visually rather than trusting source inspection alone — not a
visual template. None of its example screens, component choices, or
specific styling are used here; Jarvis's actual visual system (Direction B
geometry with Direction C atmosphere, six domains, the violet/cyan/amber/red
semantics above) predates that article's influence on this project and
remains its own thing.

## Addendum: internal-console design language (D75)

The original brief above was written for the orbital Home/core geometry.
Once Phase 6 reached the internal pages (every domain conversation, the
general conversation, and all six Centres), reusing Home's literal visual
weight there — large rounded cards, a purple-gradient hero background per
page — read as a generic themed admin dashboard rather than an interior of
the same instrument, and was corrected mid-pass (`docs/DECISIONS.md` D75).
The resolved direction for *interior* pages, kept deliberately distinct
from Home's own atmosphere:

* A near-black, flat canvas (a faint fixed grid texture standing in for
  Home's atmospheric violet glow) rather than a continuation of Home's
  background.
* Matte module surfaces with a thin 1px violet border and a smaller
  corner radius than Home's circular language — instruments, not cards.
* Cyan reserved strictly for a module that is genuinely live right now
  (listening, syncing, executing) — never a default accent.
* A small circular `MiniCoreIndicator` glyph in place of a large
  decorative core wherever an interior page needs a system-status
  presence.
* Motion calmer than Home's: entrance-only transitions, no permanently
  rotating per-card decoration, module hover as a border/foreground
  response rather than a card lift.

Home's own geometry, palette, and ring system are unchanged by this
addendum — it governs only what an internal page looks like once you've
left Home.

## Addendum 2: operational-vocabulary redesign (D80)

D75 established the console *surface* language above (matte modules, thin
violet borders, `MiniCoreIndicator`) but explicitly left Memory, Integrations,
Routine, and Data Management as a stack of generic `<section>`s wearing that
surface treatment, rather than a layout suited to what each page actually
shows — a scope boundary D75 itself called out, not an oversight. A further
pass (`docs/DECISIONS.md` D80) closed that gap by adding a small
**operational-component vocabulary** on top of D75's surfaces, reused across
all six Centres wherever the content shape actually calls for it rather than
by default:

* **Ledger rows** (`.ledger`/`.ledger-row`) — a dense label/value/action row
  for a list of like items (calendars, cached events, Health summaries and
  sessions, documents, the skill registry) instead of a `.memory-card` per
  item.
* **Timeline** (`.timeline`/`.timeline-item`) — a connected-dot vertical
  history for an audit trail or run history (Actions Centre's per-proposal
  audit log, Routine Centre's run history), with tone colour on the dot
  only (never the only signal — the event text is always present too).
* **Status cluster** (`.status-cluster`/`.status-cluster-item`) — a
  provider/schedule-overview strip (Integrations Centre's per-provider
  header, Routine Centre's three-routine schedule overview) so the current
  state of several like systems is scannable in one glance before reading
  any one section in full.
* **Queue accent** (`.queue-item.is-pending`/`.is-approved`) — a left-border
  accent (amber for awaiting review, cyan for approved-and-armed) that
  visually prioritizes Actions Centre's pending queue over its history,
  without a decorative "casual" motion or ever relying on colour alone.
* **Segmented tab row** (`.tab-row`) — restyles an existing radio-button
  filter/tab group (Actions' status filter, Skills' draft/active/archived
  tabs) into a real segmented control purely via CSS (`text-transform`,
  `:has()`), changing no accessible name, label text, or underlying markup.
* **Builder surface** (`.builder-surface`, a native `<details>`) — Skills
  Centre's new-skill form is now a deliberately collapsed-by-default
  authoring surface rather than competing with the registry list for
  attention on every visit.
* **Vault hierarchy** (`.vault-tier`) and a single prominent secrets-excluded
  guarantee banner — Data Management's storage/backup narrative as a
  numbered, ordered hierarchy instead of three equally-weighted paragraphs,
  with the "secrets never leave this machine" guarantee stated exactly once
  (previously it risked being said twice, which a live axe-core/contrast
  pass during this redesign also caught being reused inside `ConsoleHeader`'s
  `meta` slot — a slot styled for short uppercase telemetry, not prose — and
  corrected into its own banner).
* **Ask-vs-note action distinction** (`button.action-note`) — "Save as note"
  is now a neutral outline button and "Send to Jarvis" the only violet
  primary action in that row, in both the domain cockpit and the general
  conversation, so only the control that actually reaches the model reads
  as the primary action.

None of this introduces a new color, a new panel geometry, or a departure
from D75's near-black/matte/thin-violet-border language — it is additional
*composition* vocabulary for arranging that same language to fit what a
screen is actually showing, per the original `<jarvis_frontend_aesthetics>`
"Internal screens" doctrine. See `docs/ARCHITECTURE.md` §9k and
`docs/DECISIONS.md` D80 for the full screen-by-screen account and the two
real WCAG contrast regressions this pass introduced and then caught with
axe-core before shipping (an `opacity`-based de-emphasis on resolved Actions
Centre rows, and `--text-disabled` used for Data Management's tier index
numbers) — both fixed by removing the opacity trick and switching to
`--text-tertiary`, confirmed back to zero violations.

## Addendum 3: Home's situational-briefing "mission strip" (Phase 12A, D86)

A new element on Home itself, not an internal page — worth a short separate
note because Home's own register (large, cinematic, orbital) is different
from the console-interior register the addenda above describe, and a naive
implementation could easily have imported a console-style module onto Home
and broken that split.

**What it is**: a slim, dense panel of up to five real, source-backed
NOW/NEXT/WATCH items, sitting quietly below the orbit — never a large
rounded card, never bullet-point prose, never positioned so it competes
with the core/orbit for attention. It borrows the console interior's matte
surface and thin violet border (D75) rather than Home's own atmospheric
glow, since its content (dense, textual, scannable) is closer in kind to
what a Centre shows than to the orbit's spacious circular geometry — but it
stays visually subordinate to the core by living below it, at a smaller
scale, with no animation of its own.

**Tone without relying on color alone**: every item shows an explicit
NOW/NEXT/WATCH text badge *and* a left-border tone accent (amber=attention,
red=failure, cyan=neutral) — reusing the exact `.queue-item` left-accent
convention Addendum 2 already established for Actions Centre's pending
queue, rather than inventing a second left-border language. No new color
was introduced; every tone maps to an existing `--status-*`/`--accent-*`
token.

**Restraint over decoration**: the strip has exactly three actions
(Refresh, Discuss with Jarvis, Read briefing aloud) and no per-item icon
set, sparkline, or progress indicator — CLAUDE.md's "no meaningless
decorative numbers or fake activity" rule applies here as directly as
anywhere else in the product, and a genuinely empty result renders the
literal sentence "No immediate items," never a fabricated suggestion.

See `docs/ARCHITECTURE.md` §15 and `docs/DECISIONS.md` D86 for the full
technical account, including the container browser QA confirming the strip
never obstructs the orbit at any supported viewport.

## Addendum 4: change-state badges and acknowledge/snooze controls (Phase 12B, D87)

Addendum 3's mission strip gained a second badge dimension and a small
set of per-item controls without changing its register or introducing a
new panel geometry — worth its own short note because a change-tracking
feature is exactly the kind of thing that tempts a generic "diff view"
treatment (arrows, plus/minus counters, a timeline chart) that would read
as a foreign, imported UI pattern rather than an instrument reporting its
own state.

**Two independent badges, not one overloaded one.** The existing
NOW/NEXT/WATCH category badge (Addendum 3) answers "how urgent is this;"
a new NEW/CHANGED/ONGOING/RESOLVED/REOPENED badge answers "has this
changed since you last looked" — kept visually distinct (a different
shape/position, never merged into one badge with dual meaning) because
conflating them would force one color to carry two unrelated facts.

**A color mapping of its own, not a reuse of severity tone.** New/resolved
use cyan (arrival/recovery), changed/reopened use amber (something to
notice), and — deliberately the quietest choice in this whole system —
ongoing renders with no fill or border at all, just muted text. This is
the concrete answer to "unchanged items must not dominate every
briefing": after the first pass, most items settle into ongoing, and if
that state got its own bordered/filled treatment the strip would look
busier every single day for no informational reason. Every badge still
carries its own text label regardless of color, so no state is ever
communicated by hue alone.

**Controls beside the item, never inside it.** Acknowledge and a native
`<details>` Snooze disclosure sit in their own cluster next to the
existing navigate button rather than crowding into it, both because a
`<button>` cannot legally contain another interactive control and because
mixing "go there" with "dismiss this" inside one hit target would make an
accidental dismissal too easy. A resolved item shows neither control —
there is nothing left to act on, and showing disabled controls anyway
would read as clutter rather than restraint.

**The history is a closed door, not a second list competing for
attention.** "Acknowledged & snoozed" is a `<details>` disclosure, closed
by default, holding its own explicit sentence that acknowledging/snoozing
never modifies the underlying record — stated once, plainly, rather than
implied by the UI's tone. This mirrors Addendum 2's `.builder-surface`
precedent (a collapsed-by-default authoring surface) applied to a review
surface instead.

See `docs/ARCHITECTURE.md` §16 and `docs/DECISIONS.md` D87 for the full
technical account, including the container browser QA confirming all
seven badge texts render as real text (never color-only) and that the
history disclosure and a snooze menu both pass a zero-violation axe-core
sweep when expanded.

## Addendum 5: Mission Focus rank ledger (Phase 12C, D88)

A second rail sits below Addendum 4's mission strip — worth its own note
because a small, deliberate "top priorities" list is exactly the kind of
feature a generic template would render as a row of equal-weight cards
with a star icon and a drag handle, none of which fits an instrument that
is explicitly *not* a task manager.

**Rank is the anchor, not a decoration.** Each row leads with a plain
numbered badge (`#1`-`#5`) in the violet accent — no icon, no drag
affordance, no progress ring — because the ordering is Bernardo's own
explicit choice, not a computed priority score Jarvis is presenting back
to him. A numbered index reads as "this is the order you set," which is
the honest thing to communicate; a star or flame icon would have implied
Jarvis assigned some kind of importance value, which it structurally
never does.

**Reuses Phase 12B's change-state badge vocabulary exactly, never a new
one.** A pin can be NEW/CHANGED/ONGOING/RESOLVED/REOPENED exactly like any
other briefing item, because under the hood it *is* one (D88's merge
logic) — inventing a second "pin status" language here would have
contradicted the one thing this whole continuity system is for: one
consistent way of saying "has this changed."

**Blocker and target date are shown only when present, never as an empty
placeholder.** A row with neither reads as a plain rank/title/next-action
line; the meta row only grows when there's a real fact to add. This is
the same "never show a zero or a placeholder the API didn't actually
supply" rule already applied throughout the console system.

**The disclosure boundary is exactly three.** Showing the top three by
default and folding the remainder behind a closed `<details>` (identical
mechanism to Phase 12B's "Acknowledged & snoozed" history) is a
deliberate, literal reading of "a sensible default display is the top
three" — not a generic "show 3, load more" pagination pattern borrowed
from elsewhere.

**A pin's presence in the unified feed above is marked, never
re-explained.** The small violet `PINNED #N` badge on a briefing item is
the only place the two surfaces cross-reference each other; Mission Focus
itself never repeats the NOW/NEXT/WATCH category badge, since that
information belongs to the briefing's own urgency read, not to Mission
Focus's "you chose to track this" one.

See `docs/ARCHITECTURE.md` §17 and `docs/DECISIONS.md` D88 for the full
technical account, including the container browser QA confirming the
rail never obstructs the orbit at any supported viewport and that the
resolved/unavailable states render as truthful text, never a fabricated
"all clear."

## Addendum 6: DomainGlyph — a bespoke six-icon family, and one authoritative domain-number mapping (Phase 6, D91)

Every domain node and domain-view header carried only a single first
letter (B/M/P/P/B/L — two collisions, BODY/BUILD and PEOPLE/PATH) as its
"identity mark." Worth its own note because the obvious shortcut — reach
for a stock icon library — was explicitly rejected: a Lucide/Font Awesome
glyph would have read as "a themed admin dashboard wearing Jarvis colors,"
exactly the failure mode D74/D75 already spent real effort correcting
elsewhere in this system.

**One glyph, six meanings, one visual grammar.** Every `DomainGlyph`
shares the same construction: a 24×24 viewBox, `currentColor` fill/stroke,
~1.6px rounded-cap/join strokes, primarily outline-based. The six concepts
were each iterated at least once against genuine rendered-size inspection
(not just source review) before settling: MIND went from an abstract
converging-wave mark to an actual minimal brain outline once the wave mark
tested as ambiguous at 20px; LIFE went from tick-mark dial → dot-and-arrow
dial → a plain circle+cross (which read as a crosshair/target) before
landing on a slim compass needle, which is unambiguous at any size PEOPLE
was tested at; PEOPLE went from a three-node "share/network" triangle
(literally the generic icon this whole exercise exists to avoid) → two
embracing arcs (which collapsed into an unreadable ring-and-dot at small
size) → two minimal overlapping figures, which is what actually reads as
"people" rather than "abstract connection." BUILD deliberately avoids both
a code-bracket glyph and an org-chart look — three rounded modules
overlapping directly (no connector lines) reads as pieces joining, not a
hierarchy diagram.

**Purely decorative, always.** Every glyph is `aria-hidden="true"` and
`focusable="false"`, with no `aria-label` of its own — the enclosing
control (a domain button's own `aria-label`, a domain view's `<h1>`)
remains the one source of truth for what a domain is called, so the icon
can never drift out of sync with, or duplicate, the real accessible name.

**One authoritative number, not three coincidentally-matching arrays.** A
real defect was found while wiring this in: Home's orbital badges number
domains by the order `GET /api/domains` actually returns them
(alphabetical by slug — `order_by(Domain.slug)`, matching CLAUDE.md's
canonical BODY/BUILD/LIFE/MIND/PATH/PEOPLE shortcut order), but the domain
view's header badge and the `1`-`6` keyboard shortcut handler each carried
their own separate hardcoded array in the *original* CLAUDE.md narrative
order (BODY/MIND/PEOPLE/PATH/BUILD/LIFE) — so MIND showed "4" on Home but
"2" in its own header, and pressing "2" actually opened MIND while Home
visibly labeled BUILD as "2". `frontend/src/domainOrder.ts` is now the
one place this mapping is declared; every surface reads `domainNumber()`/
`domainSlugForNumber()` from it rather than maintaining its own array —
structurally closing off the specific failure mode of three independent
arrays quietly drifting apart again.

**The glyph is the dominant identity, not a second decoration next to
one.** Once every domain had a real glyph, the small violet arc-and-dot
`MiniCoreIndicator` sitting beside the domain-header emblem read as a
second, competing circular icon at rest — it conveys a real thing (Jarvis
genuinely processing/listening), so it was never simply deleted; instead
it's only mounted at all while that's actually true, so an idle header
shows exactly one identity mark. The same glyph is now also the dominant
central visual inside each large Home node itself, sized off the node's
own `--node-size` so it scales with the node rather than a fixed pixel
value, while the Jarvis core's own size and detail level were left
untouched — the hierarchy is still core → domain glyph → domain name →
subtitle → shortcut number, never the reverse.

See `docs/ARCHITECTURE.md` §9m and `docs/DECISIONS.md` D91 for the
full technical account, including the exact Home↔domain shared-element
transition behavior once the glyph itself became the morphing element.

## Addendum 6 revision: a visual-reference pass, and glyph detail scaled by size (Phase 6, D92)

Bernardo supplied a ChatGPT-generated moodboard image as a proportion/
hierarchy/line-weight reference (never traced or embedded — the six final
marks below are original inline-SVG path data) and asked for four of the
six D91 concepts to be pushed further once seen at real rendered size, plus
a size-aware detail mechanism so a symbol can carry more shape at Home's
larger node without becoming a cluttered smear at the header's ~20px.

**Four concepts revised, two left alone.** BODY (a plain vitals waveform,
now with an explicit five-segment/central-peak/terminal-dot shape) and
BUILD (three overlapping modules) were already correct and are unchanged
in concept, only tuned. MIND moved from a symmetric two-hemisphere outline
to a genuinely asymmetric, organic side-profile silhouette — the earlier
version, while a real brain shape, still read as the "front-facing medical
logo" this pass specifically wanted to avoid. PEOPLE gained an explicit
connecting arc above the two figures' heads — the D91 version already
looked like two people, but nothing visually stated "connection" beyond
proximity. PATH became three explicit ascending waypoint dots ending in a
small beacon glint, replacing an arrowhead-tipped curve that risked reading
as a directional-navigation (GPS) arrow rather than progression. LIFE
became a small calendar panel with an open orbital sweep around it — the
D91 compass needle correctly stopped reading as sync/refresh, but read as
generic "direction" rather than LIFE's actual breadth (calendar, tasks,
finances, admin); a "planning panel with an orbit" is a more specific fit
for coordinated life administration.

**`variant="home" | "header"`, added to `DomainGlyph`.** Both variants are
strictly the same symbol — same viewBox, same primary/first shape,
`"home"` never renders *fewer* shapes than `"header"` (enforced by a
direct test) — only a few fine internal strokes differ: MIND's two fold
lines, PATH's beacon detail, BUILD's two joint-accent dots, and LIFE's
internal date-row ticks all disappear at header size rather than
compressing into an illegible smear. This is a deliberate, narrow escape
hatch — a glyph earns a second render path only when a genuinely secondary
detail measurably hurts small-size legibility, never as a way to give two
sizes different personalities.

See `docs/DECISIONS.md` D92 for the full before/after account of each
glyph's visual correction and the exact size-testing that drove it.

## Addendum 6 second revision: PEOPLE/PATH/MIND/LIFE re-drawn again, and a durable eye-shape lesson (Phase 6, D93)

D92's four revised glyphs still weren't right once seen live: PEOPLE read
as a restroom/group pictogram, PATH read as a bone or wand, MIND read as a
cloud or flower, and LIFE's orbit sat so tightly against its calendar that
the two shapes knotted together. BODY and BUILD were untouched.

**The single most useful thing this pass found**: a closed loop fully
enclosing a centered shape reads as an eye almost regardless of what the
loop and the shape are actually meant to represent — this is a durable
perceptual trap worth remembering for any future glyph, not specific to
calendars. LIFE's fix (an *open* arc, never a closed ellipse) makes that
reading structurally impossible rather than merely unlikely.

**The second durable lesson**: an asymmetric outline alone doesn't stop a
silhouette from reading as a cloud — the number and uniformity of bumps
does. MIND's D92 attempt was genuinely asymmetric but used many small,
similarly-sized curve segments all the way around, which is exactly what
a cloud/cauliflower silhouette also does. The fix was fewer, larger
segments with exactly one deliberate dip (not a dozen small ones), plus a
clearly separate protruding stem — a feature no cloud, flower, gear, or
badge silhouette has.

**A real, in-app comparison surface — reused CSS, not a mockup — is what
caught both.** A temporary `frontend/src/GlyphLab.tsx` (behind
`?glyphlab=1`, removed once finished) rendered every glyph through the
real `.domain-button`/`.domain-emblem` classes so what appeared on screen
was pixel-identical to production. Both defects above were only visible
once actually rendered at real size on the real dark background — reading
the path coordinates alone gave no hint of either problem, which is the
whole justification for building a temporary comparison surface rather
than iterating from source review alone.

See `docs/DECISIONS.md` D93 for the exact final geometry of all four
glyphs and the complete before/after reasoning.

## Addendum 6, superseded: the canonical `lucide-react` icon set (Phase 6, D94)

After three rounds of hand-drawn iteration (D91-D93) — each one genuinely
fixing a real problem the last round introduced, but never quite reaching
a finished result — Bernardo made a final call: stop redrawing, and adopt
six specific, named icons from the official `lucide-react` package as
**canonical**. This deliberately reverses this addendum's own original
premise (a bespoke hand-drawn family, explicitly rejecting an icon
library, to avoid "a themed admin dashboard wearing Jarvis colors"). That
concern doesn't disappear as a design principle — but for domain identity
specifically, three rounds of hand-drawn attempts (a restroom pictogram,
a bone/wand, a cloud/flower, an eye) demonstrated that reaching a genuinely
polished, unambiguous six-icon family by hand, inside this project's scope
and timeline, cost more than it delivered. A well-chosen icon from a
mature, widely-used, MIT-licensed set, recolored to this system's own
violet/cyan language and never carrying its own background/glow/animation,
still reads as native to Jarvis rather than generic — the surrounding
HUD chrome (the ring, the glow, the state color, the orbital layout) is
what makes something feel like Jarvis, not the icon's own linework alone.

**The canonical mapping**: BODY→`Activity`, BUILD→`Boxes`,
LIFE→`CalendarDays`, MIND→`Brain`, PATH→`Compass`, PEOPLE→`UsersRound`.
Future sessions should not redraw, replace, or reinterpret these without
the same kind of explicit, deliberate decision this one required — see
CLAUDE.md's domain-iconography section, which has been rewritten in place
to state this as the current rule rather than layering a contradiction on
top of the earlier one.

**The two hard-won lessons from D91-D93 (the eye trap, the cloud trap)
remain true and worth keeping** for any future icon work this project
does, even though they no longer apply to these six specific icons —
they're recorded as durable principles in CLAUDE.md, not deleted just
because the six glyphs they were learned from are gone.

See `docs/DECISIONS.md` D94 for the complete account, including why a
temporary comparison harness (used for all three earlier rounds) was
judged unnecessary this time — official, pre-vetted, universally
recognized icons carry far less ambiguity risk than a fresh hand-drawn
attempt, and direct verification in the real app was judged sufficient.
