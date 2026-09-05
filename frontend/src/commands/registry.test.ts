import { describe, expect, it } from "vitest";
import { parseCommand } from "./registry";

describe("parseCommand — safe navigation", () => {
  it.each([
    ["memory centre", "memory_centre"],
    ["open memory centre", "memory_centre"],
    ["memory", "memory_centre"],
    ["actions centre", "actions_centre"],
    ["skills centre", "skills_centre"],
    ["integrations", "integrations_centre"],
    ["integration centre", "integrations_centre"],
    ["routines", "routine_centre"],
    ["routine centre", "routine_centre"],
    ["data management", "data_management"],
    ["go to data management", "data_management"],
  ])("recognizes %s as %s", (text, expectedTarget) => {
    const parsed = parseCommand(text);
    expect(parsed.kind).toBe("navigate");
    if (parsed.kind === "navigate") expect(parsed.target).toBe(expectedTarget);
  });

  it.each([
    ["body", "domain:body"],
    ["BODY", "domain:body"],
    ["health area", "domain:body"],
    ["mind", "domain:mind"],
    ["mind space", "domain:mind"],
    ["people", "domain:people"],
    ["path", "domain:path"],
    ["career space", "domain:path"],
    ["go to career space", "domain:path"],
    ["build", "domain:build"],
    ["life", "domain:life"],
  ])("recognizes domain alias %s as %s", (text, expectedTarget) => {
    const parsed = parseCommand(text);
    expect(parsed.kind).toBe("navigate");
    if (parsed.kind === "navigate") expect(parsed.target).toBe(expectedTarget);
  });

  it.each([
    ["go home", "home"],
    ["home", "home"],
    ["0", "home"],
    ["zero", "home"],
    ["go back", "back"],
    ["back", "back"],
    ["open command palette", "command_palette"],
    ["command palette", "command_palette"],
  ])("recognizes %s as %s", (text, expectedTarget) => {
    const parsed = parseCommand(text);
    expect(parsed.kind).toBe("navigate");
    if (parsed.kind === "navigate") expect(parsed.target).toBe(expectedTarget);
  });

  it("is case-insensitive and tolerates trailing punctuation", () => {
    const parsed = parseCommand("Go To Integrations.");
    expect(parsed.kind).toBe("navigate");
    if (parsed.kind === "navigate") expect(parsed.target).toBe("integrations_centre");
  });
});

describe("parseCommand — sensitive control focusing (never auto-clicked)", () => {
  it.each([
    ["go to integrations and show google health automatic sync", "google_health.auto_sync_toggle", "integrations_centre"],
    ["show google health automatic sync", "google_health.auto_sync_toggle", "integrations_centre"],
    ["take me to calendar writing", "google_calendar.enable_writing", "integrations_centre"],
    ["connect google calendar", "google_calendar.connect", "integrations_centre"],
  ])("resolves %s to a focus_control targeting %s", (text, expectedControlId, expectedNav) => {
    const parsed = parseCommand(text);
    expect(parsed.kind).toBe("focus_control");
    if (parsed.kind === "focus_control") {
      expect(parsed.control.controlId).toBe(expectedControlId);
      expect(parsed.control.navigateTo).toBe(expectedNav);
    }
  });

  it("never returns a kind that implies direct activation for a sensitive phrase", () => {
    // "disconnect" is now a confirm_required action (Phase 6 global-voice
    // pass) rather than focus_control — a real confirm dialog, then a real
    // disconnect only if accepted — but it still never implies *direct*
    // activation from the spoken/typed phrase alone.
    const parsed = parseCommand("disconnect google calendar");
    expect(parsed.kind).not.toBe("execute");
    expect(parsed.kind).toBe("confirm_required");
  });
});

describe("parseCommand — blocked mutations without a specific known control", () => {
  it.each([
    "approve this action",
    "deny this action",
    "execute this action",
    "delete this document",
    "restore this backup",
    "import this file",
    "archive this record",
    "run the sync now",
  ])("refuses to execute: %s", (text) => {
    const parsed = parseCommand(text);
    expect(parsed.kind).toBe("blocked");
  });

  it("blocks positional control selection regardless of phrasing", () => {
    const parsed = parseCommand("press the second button");
    expect(parsed.kind).toBe("blocked");
  });

  it("never lets a blocked phrase resolve to navigate or focus_control", () => {
    for (const text of ["approve this action", "press the third item", "delete this document"]) {
      const parsed = parseCommand(text);
      expect(parsed.kind).not.toBe("navigate");
      expect(parsed.kind).not.toBe("focus_control");
    }
  });
});

describe("parseCommand — ordinary conversation is never misread as a command", () => {
  it.each([
    "What do you remember about my knee?",
    "I've been feeling a bit low this week.",
    "This knee pain is really affecting my body",
    "I want to remove this bad habit from my life eventually",
    "Can you help me plan my week?",
  ])("returns none for: %s", (text) => {
    const parsed = parseCommand(text);
    expect(parsed.kind).toBe("none");
  });

  it("returns none for empty or whitespace-only input", () => {
    expect(parseCommand("").kind).toBe("none");
    expect(parseCommand("   ").kind).toBe("none");
  });
});

describe("parseCommand — opening the general Jarvis conversation (not a seventh domain)", () => {
  it.each(["talk to jarvis", "ask jarvis", "general conversation", "start a new conversation", "start a general conversation"])(
    "resolves %s to navigate:general",
    (text) => {
      const parsed = parseCommand(text);
      expect(parsed.kind).toBe("navigate");
      if (parsed.kind === "navigate") expect(parsed.target).toBe("general");
    },
  );
});

describe("parseCommand — safe direct actions (read-only or trivially reversible, execute immediately)", () => {
  it("resolves 'sync calendar' to a safe sync action, not a focus_control or a block", () => {
    const parsed = parseCommand("sync calendar");
    expect(parsed.kind).toBe("safe_action");
    if (parsed.kind === "safe_action") {
      expect(parsed.action).toEqual({ kind: "sync_provider", provider: "google_calendar", providerLabel: "Google Calendar" });
    }
  });

  it("resolves 'sync google health' to a safe sync action", () => {
    const parsed = parseCommand("sync google health");
    expect(parsed.kind).toBe("safe_action");
    if (parsed.kind === "safe_action") {
      expect(parsed.action).toEqual({ kind: "sync_provider", provider: "google_health", providerLabel: "Google Health" });
    }
  });

  it("does not let a bare 'sync' shadow the automatic-sync *schedule toggle*, which stays a focus_control", () => {
    const parsed = parseCommand("show google health automatic sync");
    expect(parsed.kind).toBe("focus_control");
  });

  it.each(["retry connection", "reconnect"])("resolves %s to a safe retry_connection action", (text) => {
    const parsed = parseCommand(text);
    expect(parsed.kind).toBe("safe_action");
    if (parsed.kind === "safe_action") expect(parsed.action).toEqual({ kind: "retry_connection" });
  });

  it("resolves an explicitly-named routine to a safe run_routine action", () => {
    const parsed = parseCommand("run the morning briefing");
    expect(parsed.kind).toBe("safe_action");
    if (parsed.kind === "safe_action") {
      expect(parsed.action).toEqual({ kind: "run_routine", routineType: "morning_briefing", routineLabel: "Morning Briefing" });
    }
  });

  it("never executes a routine without it being explicitly named", () => {
    // A bare "run a routine" names nothing specific — must not guess which
    // one, so it falls through rather than resolving to a safe_action.
    const parsed = parseCommand("run a routine");
    expect(parsed.kind).not.toBe("safe_action");
  });
});

describe("parseCommand — confirmation-required actions (never executed by the registry itself)", () => {
  it.each([
    ["disconnect google calendar", { kind: "disconnect_integration", provider: "google_calendar", providerLabel: "Google Calendar" }],
    ["disconnect google health", { kind: "disconnect_integration", provider: "google_health", providerLabel: "Google Health" }],
    ["export data", { kind: "export_data" }],
    ["export everything", { kind: "export_data" }],
  ])("resolves %s to confirm_required with a real, specific action and a warning", (text, expectedAction) => {
    const parsed = parseCommand(text);
    expect(parsed.kind).toBe("confirm_required");
    if (parsed.kind === "confirm_required") {
      expect(parsed.action).toEqual(expectedAction);
      expect(parsed.warning.length).toBeGreaterThan(0);
    }
  });

  it("a proposal-lifecycle phrase (Calendar/memory changes) is never a confirm_required or safe_action — it stays an ordinary question", () => {
    // Creating/updating Calendar events or memories/records always goes
    // through the existing Phase 8 propose -> approve -> execute
    // lifecycle, driven by the model, never a local command shortcut.
    const parsed = parseCommand("create a calendar event for tomorrow at 3pm");
    expect(parsed.kind).not.toBe("confirm_required");
    expect(parsed.kind).not.toBe("safe_action");
    expect(parsed.kind).toBe("none");
  });
});

describe("parseCommand — negation is never misread as its affirmative command (D83/D84 reliability audit)", () => {
  // CONFIRM_ACTIONS/SAFE_ACTIONS match by keyword presence regardless of
  // word order (see the comment above SENSITIVE_CONTROLS) — "don't
  // disconnect google calendar" contains exactly the same keywords as
  // "disconnect google calendar" would otherwise resolve identically,
  // which is a real safety gap for a safe_action specifically: it executes
  // immediately, with no confirmation step, despite the user explicitly
  // saying not to.
  it.each([
    "don't disconnect google calendar",
    "do not disconnect google calendar",
    "never disconnect google calendar",
    "you shouldn't disconnect google calendar",
  ])("never resolves %s to confirm_required", (text) => {
    const parsed = parseCommand(text);
    expect(parsed.kind).not.toBe("confirm_required");
  });

  it.each(["don't sync calendar", "don't sync calendar right now", "do not sync google health"])(
    "never resolves %s to a safe_action",
    (text) => {
      const parsed = parseCommand(text);
      expect(parsed.kind).not.toBe("safe_action");
    },
  );

  it("never resolves a negated export request to confirm_required", () => {
    const parsed = parseCommand("don't export my data");
    expect(parsed.kind).not.toBe("confirm_required");
  });

  it("an un-negated affirmative command is unaffected by the negation check", () => {
    // Confirms the fix is scoped to genuine negation, not a regression in
    // ordinary matching.
    expect(parseCommand("disconnect google calendar").kind).toBe("confirm_required");
    expect(parseCommand("sync calendar").kind).toBe("safe_action");
  });
});

describe("parseCommand — a question about a command never executes it (D83/D84 reliability audit)", () => {
  // Same keyword-presence root cause as negation: "what does sync calendar
  // do" previously ran a real sync immediately, purely from being asked
  // what it does — worse than the negation case, since a plain question
  // carries no explicit refusal cue at all for a human reader either.
  it.each(["what does sync calendar do", "how does syncing google health work", "what happens if I sync calendar"])(
    "never resolves %s to a safe_action",
    (text) => {
      const parsed = parseCommand(text);
      expect(parsed.kind).not.toBe("safe_action");
    },
  );

  it.each([
    "how do I export data",
    "how do I export data?",
    "what happens if I export everything",
    "can you explain what disconnect google calendar does",
    "does disconnect google calendar delete my events?",
  ])("never resolves %s to confirm_required", (text) => {
    const parsed = parseCommand(text);
    expect(parsed.kind).not.toBe("confirm_required");
  });

  it("a trailing question mark alone is enough to suppress an otherwise-matching safe_action", () => {
    expect(parseCommand("sync calendar?").kind).not.toBe("safe_action");
  });

  it("an ordinary affirmative command with no question phrasing is unaffected", () => {
    expect(parseCommand("export data").kind).toBe("confirm_required");
    expect(parseCommand("sync calendar").kind).toBe("safe_action");
  });
});

describe("parseCommand — Mission Control safe actions", () => {
  it.each([
    ["start a focus session", null],
    ["start focus", null],
    ["begin a focus session", null],
    ["focus on this", null],
    ["focus on this for 45 minutes", 45],
    ["start a focus session for 25 minutes", 25],
    ["begin the focus session for 60 mins", 60],
  ])("recognizes %s as focus_start (duration %s)", (text, expectedMinutes) => {
    const parsed = parseCommand(text);
    expect(parsed.kind).toBe("safe_action");
    if (parsed.kind === "safe_action" && parsed.action.kind === "focus_start") {
      expect(parsed.action.durationMinutes).toBe(expectedMinutes);
    } else {
      throw new Error("expected a focus_start safe_action");
    }
  });

  it("ignores an out-of-range spoken duration rather than accepting it verbatim", () => {
    const parsed = parseCommand("focus on this for 500 minutes");
    expect(parsed.kind).toBe("safe_action");
    if (parsed.kind === "safe_action" && parsed.action.kind === "focus_start") {
      expect(parsed.action.durationMinutes).toBeNull();
    } else {
      throw new Error("expected a focus_start safe_action");
    }
  });

  it.each([
    ["pause focus", "focus_pause"],
    ["pause the focus session", "focus_pause"],
    ["pause this session", "focus_pause"],
    ["resume focus", "focus_resume"],
    ["resume the focus session", "focus_resume"],
    ["complete this session", "focus_complete"],
    ["finish focus", "focus_complete"],
    ["complete the mission session", "focus_complete"],
    ["abandon focus session", "focus_abandon"],
    ["abandon this session", "focus_abandon"],
  ])("recognizes %s as %s", (text, expectedActionKind) => {
    const parsed = parseCommand(text);
    expect(parsed.kind).toBe("safe_action");
    if (parsed.kind === "safe_action") expect(parsed.action.kind).toBe(expectedActionKind);
  });

  it.each([
    ["show current mission", "focus_show_current"],
    ["what am i focusing on", "focus_show_current"],
    ["show mission history", "focus_show_history"],
    ["what did i accomplish today?", "focus_show_history"],
    ["what have i completed today", "focus_show_history"],
  ])("recognizes the read-only phrasing %s as %s despite being a question", (text, expectedActionKind) => {
    const parsed = parseCommand(text);
    expect(parsed.kind).toBe("safe_action");
    if (parsed.kind === "safe_action") expect(parsed.action.kind).toBe(expectedActionKind);
  });

  it.each([
    "don't start a focus session",
    "do not start a focus session",
    "never start a focus session",
    "don't pause focus",
    "don't finish this",
    "i'm not asking you to pause",
    "don't abandon this session",
  ])("never resolves negated phrasing %s to a safe_action", (text) => {
    const parsed = parseCommand(text);
    expect(parsed.kind).not.toBe("safe_action");
  });

  it.each([
    "what happens if I finish this?",
    "can Jarvis pause a session?",
    "why is this mission suggested?",
    "what happens if I start a focus session",
    "how does pausing focus work",
  ])("never resolves interrogative phrasing %s to a safe_action", (text) => {
    const parsed = parseCommand(text);
    expect(parsed.kind).not.toBe("safe_action");
  });

  it("an un-negated, non-interrogative Mission Control command is unaffected by the guards above", () => {
    expect(parseCommand("start a focus session").kind).toBe("safe_action");
    expect(parseCommand("pause focus").kind).toBe("safe_action");
    expect(parseCommand("complete this session").kind).toBe("safe_action");
    expect(parseCommand("abandon focus session").kind).toBe("safe_action");
  });
});

describe("parseCommand — Phase 12D Unified Recall (open_recall safe action)", () => {
  it.each([
    ["search jarvis for renew passport", "renew passport", null],
    ["search for renew passport", "renew passport", null],
    ["search my memories for renew passport", "renew passport", null],
    ["look up renew passport", "renew passport", null],
    ["look up renew passport in body", "renew passport", "body"],
    ["search jarvis for coffee shops in Lisbon", "coffee shops in lisbon", null],
  ])("recognizes %s as open_recall (query=%s, domainHint=%s)", (text, expectedQuery, expectedDomain) => {
    const parsed = parseCommand(text);
    expect(parsed.kind).toBe("safe_action");
    if (parsed.kind === "safe_action" && parsed.action.kind === "open_recall") {
      expect(parsed.action.query).toBe(expectedQuery);
      expect(parsed.action.domainHint).toBe(expectedDomain);
    } else {
      throw new Error("expected an open_recall safe_action");
    }
  });

  it("recognizes 'find X in my memories' as open_recall with no domain hint", () => {
    const parsed = parseCommand("find renew passport in my memories");
    expect(parsed.kind).toBe("safe_action");
    if (parsed.kind === "safe_action" && parsed.action.kind === "open_recall") {
      expect(parsed.action.query).toBe("renew passport");
      expect(parsed.action.domainHint).toBeNull();
    } else {
      throw new Error("expected an open_recall safe_action");
    }
  });

  it("recognizes 'find X in <domain>' as open_recall scoped to that domain", () => {
    const parsed = parseCommand("find my symptoms in body");
    expect(parsed.kind).toBe("safe_action");
    if (parsed.kind === "safe_action" && parsed.action.kind === "open_recall") {
      expect(parsed.action.query).toBe("my symptoms");
      expect(parsed.action.domainHint).toBe("body");
    } else {
      throw new Error("expected an open_recall safe_action");
    }
  });

  it("does not treat bare 'find X' (no qualifier) as a command — too common in ordinary conversation", () => {
    const parsed = parseCommand("find the article about tokenizers");
    expect(parsed.kind).not.toBe("safe_action");
  });

  it.each([
    "don't search jarvis for renew passport",
    "do not search for anything",
    "never look up my old messages",
    "don't find my symptoms in body",
  ])("never resolves negated phrasing %s to a safe_action", (text) => {
    const parsed = parseCommand(text);
    expect(parsed.kind).not.toBe("safe_action");
  });

  it.each([
    "what happens if I search jarvis for renew passport?",
    "can Jarvis look up my old messages?",
    "why would I search for that",
  ])("never resolves interrogative phrasing %s to a safe_action", (text) => {
    const parsed = parseCommand(text);
    expect(parsed.kind).not.toBe("safe_action");
  });

  it("recognizes recall_centre navigation aliases", () => {
    const parsed = parseCommand("open recall");
    expect(parsed.kind).toBe("navigate");
    if (parsed.kind === "navigate") expect(parsed.target).toBe("recall_centre");
  });

  it.each(["open research", "show research centre", "research workspace", "research"])(
    "recognizes research_centre navigation phrasing: %s",
    (text) => {
      const parsed = parseCommand(text);
      expect(parsed.kind).toBe("navigate");
      if (parsed.kind === "navigate") expect(parsed.target).toBe("research_centre");
    },
  );

  it("never resolves a research question into an autonomous research action — only navigation", () => {
    // CLAUDE.md's Phase 12E boundary: a spoken/typed phrase may only ever
    // open the Research Centre itself, never create a workspace, add
    // evidence, or generate a brief on its own.
    const parsed = parseCommand("research the best tokenizer for Alpha");
    expect(parsed.kind).not.toBe("safe_action");
    expect(parsed.kind).not.toBe("confirm_required");
  });

  it.each(["open decisions", "show decision room", "review my decisions", "decision room", "decisions"])(
    "recognizes decision_centre navigation phrasing: %s",
    (text) => {
      const parsed = parseCommand(text);
      expect(parsed.kind).toBe("navigate");
      if (parsed.kind === "navigate") expect(parsed.target).toBe("decision_centre");
    },
  );

  it("never resolves a decision-sounding phrase into an autonomous decide/execute action — only navigation", () => {
    // CLAUDE.md's Phase 12F boundary: Jarvis must never finalize or
    // execute a decision on its own — a spoken/typed phrase may only ever
    // open the Decision Room itself.
    const parsed = parseCommand("decide which tokenizer we should use for Alpha");
    expect(parsed.kind).not.toBe("safe_action");
    expect(parsed.kind).not.toBe("confirm_required");
  });
});
