import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import ResearchCentre from "./views/ResearchCentre";
import * as api from "./api";
import type { RecallResult, RecallSearchResult, ResearchBriefVersion, ResearchEvidence, ResearchNote, ResearchWorkspace } from "./api";

beforeEach(() => {
  vi.restoreAllMocks();
});

afterEach(() => {
  vi.restoreAllMocks();
});

const noop = () => {};

function workspace(overrides: Partial<ResearchWorkspace> = {}): ResearchWorkspace {
  return {
    id: "ws-1",
    title: "Tokenizer choice for Alpha",
    domain_slug: null,
    included_domain_slugs: ["life", "path", "build"],
    status: "active",
    evidence_count: 0,
    note_count: 0,
    latest_brief_version: null,
    created_at: "2026-08-29T09:00:00Z",
    updated_at: "2026-08-29T09:00:00Z",
    archived_at: null,
    ...overrides,
  };
}

function evidenceItem(overrides: Partial<ResearchEvidence> = {}): ResearchEvidence {
  return {
    id: "ev-1",
    workspace_id: "ws-1",
    source_type: "message",
    source_id: "msg-1",
    domain_slug: "build",
    title_snapshot: "Tokenizer research",
    snippet_snapshot: "BPE handles rare words well.",
    occurred_at_snapshot: "2026-08-29T09:00:00Z",
    classification: "supporting",
    note: null,
    status: "active",
    available: true,
    unavailable_reason: null,
    link_target: "domain:build",
    added_at: "2026-08-29T09:00:00Z",
    updated_at: "2026-08-29T09:00:00Z",
    ...overrides,
  };
}

function recallResult(overrides: Partial<RecallResult> = {}): RecallResult {
  return {
    source_type: "message",
    source_id: "msg-1",
    domain_slug: "build",
    title: "Tokenizer research",
    snippet_html: "BPE handles <mark>rare</mark> words well.",
    occurred_at: "2026-08-29T09:00:00Z",
    link_target: "domain:build",
    available: true,
    unavailable_reason: null,
    ...overrides,
  };
}

function recallSearchResult(overrides: Partial<RecallSearchResult> = {}): RecallSearchResult {
  return {
    query: "tokenizer",
    results: [],
    total_considered: 0,
    limit: 15,
    offset: 0,
    has_more: false,
    partial_failures: [],
    ...overrides,
  };
}

function noteItem(overrides: Partial<ResearchNote> = {}): ResearchNote {
  return {
    id: "note-1",
    workspace_id: "ws-1",
    content: "BPE seems standard.",
    linked_evidence_ids: [],
    status: "active",
    created_at: "2026-08-29T09:00:00Z",
    updated_at: "2026-08-29T09:00:00Z",
    ...overrides,
  };
}

function briefVersion(overrides: Partial<ResearchBriefVersion> = {}): ResearchBriefVersion {
  return {
    id: "brief-1",
    workspace_id: "ws-1",
    version_number: 1,
    source: "deterministic",
    status: "ok",
    title: "Tokenizer choice for Alpha — evidence outline",
    sections_json: JSON.stringify([
      {
        kind: "evidence_group",
        classification: "supporting",
        heading: "Supporting evidence",
        items: [{ citation_number: 1, title: "Tokenizer research", excerpt: "BPE handles rare words well.", note: null }],
      },
    ]),
    citations: [
      {
        number: 1,
        evidence_id: "ev-1",
        source_type: "message",
        source_id: "msg-1",
        domain_slug: "build",
        title_snapshot: "Tokenizer research",
        snippet_snapshot: "BPE handles rare words well.",
        available: true,
        unavailable_reason: null,
        link_target: "domain:build",
      },
    ],
    validation_issues: [],
    model_meta: null,
    generated_at: "2026-08-29T09:05:00Z",
    created_at: "2026-08-29T09:05:00Z",
    ...overrides,
  };
}

function mockDetailFetches(ws: ResearchWorkspace, evidence: ResearchEvidence[] = [], notes: ResearchNote[] = []) {
  vi.spyOn(api, "fetchResearchWorkspace").mockResolvedValue(ws);
  vi.spyOn(api, "listResearchEvidence").mockResolvedValue(evidence);
  vi.spyOn(api, "listResearchNotes").mockResolvedValue(notes);
  vi.spyOn(api, "listResearchBriefs").mockResolvedValue([]);
}

describe("ResearchCentre — workspace list", () => {
  it("shows a loading state, then an empty state with no workspaces", async () => {
    vi.spyOn(api, "fetchResearchWorkspaces").mockResolvedValue([]);
    render(<ResearchCentre onBack={noop} onNavigate={noop} />);
    expect(await screen.findByText(/no active research workspaces yet/i)).toBeInTheDocument();
  });

  it("shows a truthful error state when the backend is unreachable", async () => {
    vi.spyOn(api, "fetchResearchWorkspaces").mockRejectedValue(new Error("network error"));
    render(<ResearchCentre onBack={noop} onNavigate={noop} />);
    expect(await screen.findByRole("alert")).toHaveTextContent(/could not load research workspaces/i);
  });

  it("renders existing workspaces in a ledger", async () => {
    vi.spyOn(api, "fetchResearchWorkspaces").mockResolvedValue([workspace({ evidence_count: 3, note_count: 1 })]);
    render(<ResearchCentre onBack={noop} onNavigate={noop} />);
    expect(await screen.findByText("Tokenizer choice for Alpha")).toBeInTheDocument();
    expect(screen.getByText(/3 evidence · 1 note/i)).toBeInTheDocument();
  });

  it("creates a workspace and opens its detail view", async () => {
    const user = userEvent.setup();
    vi.spyOn(api, "fetchResearchWorkspaces").mockResolvedValue([]);
    const createSpy = vi.spyOn(api, "createResearchWorkspace").mockResolvedValue(workspace());
    mockDetailFetches(workspace());

    render(<ResearchCentre onBack={noop} onNavigate={noop} />);
    await user.type(await screen.findByLabelText(/research question or topic/i), "Tokenizer choice for Alpha");
    await user.click(screen.getByRole("button", { name: /create workspace/i }));

    await waitFor(() => expect(createSpy).toHaveBeenCalledWith(
      expect.objectContaining({ title: "Tokenizer choice for Alpha", included_domain_slugs: ["life", "path", "build"] }),
    ));
    expect(await screen.findByText(/all workspaces/i)).toBeInTheDocument();
  });

  it("toggling a sensitive domain in the create form includes it in the create request", async () => {
    const user = userEvent.setup();
    vi.spyOn(api, "fetchResearchWorkspaces").mockResolvedValue([]);
    const createSpy = vi.spyOn(api, "createResearchWorkspace").mockResolvedValue(workspace());
    mockDetailFetches(workspace());

    render(<ResearchCentre onBack={noop} onNavigate={noop} />);
    await user.click(await screen.findByRole("checkbox", { name: /mind/i }));
    await user.type(screen.getByLabelText(/research question or topic/i), "Mood patterns");
    await user.click(screen.getByRole("button", { name: /create workspace/i }));

    await waitFor(() => expect(createSpy).toHaveBeenCalled());
    expect(createSpy.mock.calls[0][0].included_domain_slugs).toContain("mind");
  });

  it("every domain-picker checkbox has an accessible name reachable by keyboard", async () => {
    vi.spyOn(api, "fetchResearchWorkspaces").mockResolvedValue([]);
    render(<ResearchCentre onBack={noop} onNavigate={noop} />);
    await screen.findByText(/no active research workspaces/i);
    for (const checkbox of screen.getAllByRole("checkbox")) {
      expect(checkbox).toHaveAccessibleName();
    }
  });
});

describe("ResearchCentre — workspace detail: evidence", () => {
  it("searches for evidence, shows a no-results state, and a partial-failure notice", async () => {
    const user = userEvent.setup();
    vi.spyOn(api, "fetchResearchWorkspaces").mockResolvedValue([workspace()]);
    mockDetailFetches(workspace());
    vi.spyOn(api, "searchResearchEvidence").mockResolvedValue(
      recallSearchResult({ partial_failures: ["memory_item"] }),
    );

    render(<ResearchCentre onBack={noop} onNavigate={noop} />);
    await user.click(await screen.findByText("Tokenizer choice for Alpha"));
    await user.type(await screen.findByPlaceholderText(/search jarvis for evidence/i), "tokenizer");

    expect(await screen.findByText(/no results in this workspace/i)).toBeInTheDocument();
    expect(screen.getByText(/memory_item/)).toBeInTheDocument();
  });

  it("adds a search result as evidence and marks it Added", async () => {
    const user = userEvent.setup();
    vi.spyOn(api, "fetchResearchWorkspaces").mockResolvedValue([workspace()]);
    mockDetailFetches(workspace());
    vi.spyOn(api, "searchResearchEvidence").mockResolvedValue(recallSearchResult({ results: [recallResult()] }));
    const addSpy = vi.spyOn(api, "addResearchEvidence").mockResolvedValue(evidenceItem());

    render(<ResearchCentre onBack={noop} onNavigate={noop} />);
    await user.click(await screen.findByText("Tokenizer choice for Alpha"));
    await user.type(await screen.findByPlaceholderText(/search jarvis for evidence/i), "tokenizer");
    await user.click(await screen.findByRole("button", { name: /add as evidence/i }));

    await waitFor(() =>
      expect(addSpy).toHaveBeenCalledWith("ws-1", { source_type: "message", source_id: "msg-1" }),
    );
  });

  it("renders the evidence ledger with a classification select and an unavailable source truthfully", async () => {
    const user = userEvent.setup();
    vi.spyOn(api, "fetchResearchWorkspaces").mockResolvedValue([workspace({ evidence_count: 1 })]);
    mockDetailFetches(
      workspace({ evidence_count: 1 }),
      [evidenceItem({ available: false, unavailable_reason: "Source unavailable" })],
    );

    render(<ResearchCentre onBack={noop} onNavigate={noop} />);
    await user.click(await screen.findByText("Tokenizer choice for Alpha"));

    expect(await screen.findByText("Tokenizer research")).toBeInTheDocument();
    expect(screen.getByText(/source unavailable/i)).toBeInTheDocument();
    expect(screen.getByRole("combobox", { name: /classification for tokenizer research/i })).toBeInTheDocument();
  });

  it("changing the classification select calls updateResearchEvidence", async () => {
    const user = userEvent.setup();
    vi.spyOn(api, "fetchResearchWorkspaces").mockResolvedValue([workspace({ evidence_count: 1 })]);
    mockDetailFetches(workspace({ evidence_count: 1 }), [evidenceItem()]);
    const updateSpy = vi.spyOn(api, "updateResearchEvidence").mockResolvedValue(evidenceItem({ classification: "contradicting" }));

    render(<ResearchCentre onBack={noop} onNavigate={noop} />);
    await user.click(await screen.findByText("Tokenizer choice for Alpha"));
    const select = await screen.findByRole("combobox", { name: /classification for tokenizer research/i });
    await user.selectOptions(select, "contradicting");

    await waitFor(() => expect(updateSpy).toHaveBeenCalledWith("ws-1", "ev-1", { classification: "contradicting" }));
  });

  it("removes evidence via the Remove button", async () => {
    const user = userEvent.setup();
    vi.spyOn(api, "fetchResearchWorkspaces").mockResolvedValue([workspace({ evidence_count: 1 })]);
    mockDetailFetches(workspace({ evidence_count: 1 }), [evidenceItem()]);
    const removeSpy = vi.spyOn(api, "removeResearchEvidence").mockResolvedValue(evidenceItem({ status: "removed" }));

    render(<ResearchCentre onBack={noop} onNavigate={noop} />);
    await user.click(await screen.findByText("Tokenizer choice for Alpha"));
    await user.click(await screen.findByRole("button", { name: /^remove$/i }));

    await waitFor(() => expect(removeSpy).toHaveBeenCalledWith("ws-1", "ev-1"));
  });
});

describe("ResearchCentre — workspace detail: notes", () => {
  it("adds a note and renders it in the notes ledger", async () => {
    const user = userEvent.setup();
    vi.spyOn(api, "fetchResearchWorkspaces").mockResolvedValue([workspace()]);
    mockDetailFetches(workspace());
    const addNoteSpy = vi.spyOn(api, "addResearchNote").mockResolvedValue(noteItem());

    render(<ResearchCentre onBack={noop} onNavigate={noop} />);
    await user.click(await screen.findByText("Tokenizer choice for Alpha"));
    await user.click(screen.getByRole("radio", { name: /notes/i }));
    await user.type(await screen.findByLabelText(/note content/i), "BPE seems standard.");
    await user.click(screen.getByRole("button", { name: /add note/i }));

    await waitFor(() => expect(addNoteSpy).toHaveBeenCalledWith("ws-1", { content: "BPE seems standard.", linked_evidence_ids: [] }));
  });

  it("archives a note via the Archive button", async () => {
    const user = userEvent.setup();
    vi.spyOn(api, "fetchResearchWorkspaces").mockResolvedValue([workspace()]);
    mockDetailFetches(workspace(), [], [noteItem()]);
    const archiveSpy = vi.spyOn(api, "archiveResearchNote").mockResolvedValue(noteItem({ status: "archived" }));

    render(<ResearchCentre onBack={noop} onNavigate={noop} />);
    await user.click(await screen.findByText("Tokenizer choice for Alpha"));
    await user.click(screen.getByRole("radio", { name: /notes/i }));
    await user.click(await screen.findByRole("button", { name: /^archive$/i }));

    await waitFor(() => expect(archiveSpy).toHaveBeenCalledWith("ws-1", "note-1"));
  });
});

describe("ResearchCentre — workspace detail: briefs", () => {
  it("generates a deterministic outline and renders its citations", async () => {
    const user = userEvent.setup();
    vi.spyOn(api, "fetchResearchWorkspaces").mockResolvedValue([workspace({ evidence_count: 1 })]);
    mockDetailFetches(workspace({ evidence_count: 1 }), [evidenceItem()]);
    vi.spyOn(api, "generateDeterministicBrief").mockResolvedValue(briefVersion());

    render(<ResearchCentre onBack={noop} onNavigate={noop} />);
    await user.click(await screen.findByText("Tokenizer choice for Alpha"));
    await user.click(screen.getByRole("radio", { name: /briefs/i }));
    await user.click(await screen.findByRole("button", { name: /generate evidence outline/i }));

    expect(await screen.findByText("Supporting evidence")).toBeInTheDocument();
    expect(screen.getAllByText(/\[1\] Tokenizer research/).length).toBeGreaterThan(0);
  });

  it("shows a distinct model-unavailable state when Draft with Jarvis fails with a 502", async () => {
    const user = userEvent.setup();
    vi.spyOn(api, "fetchResearchWorkspaces").mockResolvedValue([workspace({ evidence_count: 1 })]);
    mockDetailFetches(workspace({ evidence_count: 1 }), [evidenceItem()]);
    vi.spyOn(api, "draftBriefWithJarvis").mockRejectedValue(new api.ApiError(502, "Jarvis could not draft this brief."));

    render(<ResearchCentre onBack={noop} onNavigate={noop} />);
    await user.click(await screen.findByText("Tokenizer choice for Alpha"));
    await user.click(screen.getByRole("radio", { name: /briefs/i }));
    await user.click(await screen.findByRole("button", { name: /draft with jarvis/i }));

    expect(await screen.findByRole("alert")).toHaveTextContent(/jarvis model is currently unavailable/i);
  });

  it("shows a visible validation-error state for a brief with a flagged citation", async () => {
    const user = userEvent.setup();
    vi.spyOn(api, "fetchResearchWorkspaces").mockResolvedValue([workspace({ evidence_count: 1 })]);
    mockDetailFetches(workspace({ evidence_count: 1 }), [evidenceItem()]);
    vi.spyOn(api, "listResearchBriefs").mockResolvedValue([
      { id: "brief-2", version_number: 2, source: "model", status: "invalid_citations", generated_at: "2026-08-29T09:10:00Z" },
    ]);
    vi.spyOn(api, "getResearchBrief").mockResolvedValue(
      briefVersion({
        id: "brief-2",
        version_number: 2,
        source: "model",
        status: "invalid_citations",
        validation_issues: ["Citation [7] does not correspond to any evidence supplied to the model and was not linked."],
        sections_json: JSON.stringify([{ kind: "model_text", heading: "Jarvis model-generated draft", text: "A claim [1]. A hallucinated claim [7]." }]),
        model_meta: { provider: "hermes", model: "openai-codex/gpt-5.6-terra", latency_ms: 900, evidence_ids_used: ["ev-1"] },
      }),
    );

    render(<ResearchCentre onBack={noop} onNavigate={noop} />);
    await user.click(await screen.findByText("Tokenizer choice for Alpha"));
    await user.click(screen.getByRole("radio", { name: /briefs/i }));
    await user.click(await screen.findByText(/v2 — jarvis model-generated draft/i));

    expect(await screen.findByRole("alert")).toHaveTextContent(/does not correspond to any evidence/i);
    expect(screen.getAllByText(/jarvis model-generated draft/i).length).toBeGreaterThan(0);
  });

  it("disables brief generation and shows a notice when there is no evidence yet", async () => {
    vi.spyOn(api, "fetchResearchWorkspaces").mockResolvedValue([workspace()]);
    mockDetailFetches(workspace());

    const user = userEvent.setup();
    render(<ResearchCentre onBack={noop} onNavigate={noop} />);
    await user.click(await screen.findByText("Tokenizer choice for Alpha"));
    await user.click(screen.getByRole("radio", { name: /briefs/i }));

    expect(await screen.findByText(/add at least one piece of evidence first/i)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /generate evidence outline/i })).toBeDisabled();
    expect(screen.getByRole("button", { name: /draft with jarvis/i })).toBeDisabled();
  });
});

describe("ResearchCentre — archived workspace", () => {
  it("shows a read-only notice and disables mutating controls for an archived workspace", async () => {
    const user = userEvent.setup();
    const archived = workspace({ status: "archived", archived_at: "2026-08-29T09:00:00Z", evidence_count: 1 });
    vi.spyOn(api, "fetchResearchWorkspaces").mockResolvedValue([archived]);
    mockDetailFetches(archived, [evidenceItem()]);

    render(<ResearchCentre onBack={noop} onNavigate={noop} />);
    await user.click(await screen.findByText("Tokenizer choice for Alpha"));

    expect(await screen.findByText(/this workspace is archived/i)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /reopen workspace/i })).toBeInTheDocument();
    expect(screen.getByPlaceholderText(/search jarvis for evidence/i)).toBeDisabled();
  });

  it("reopens an archived workspace via the Reopen button", async () => {
    const user = userEvent.setup();
    const archived = workspace({ status: "archived", archived_at: "2026-08-29T09:00:00Z" });
    vi.spyOn(api, "fetchResearchWorkspaces").mockResolvedValue([archived]);
    mockDetailFetches(archived);
    const reopenSpy = vi.spyOn(api, "reopenResearchWorkspace").mockResolvedValue(workspace({ status: "active" }));

    render(<ResearchCentre onBack={noop} onNavigate={noop} />);
    await user.click(await screen.findByText("Tokenizer choice for Alpha"));
    await user.click(await screen.findByRole("button", { name: /reopen workspace/i }));

    await waitFor(() => expect(reopenSpy).toHaveBeenCalledWith("ws-1"));
  });
});

describe("ResearchCentre — navigation and accessibility", () => {
  it("navigates via onNavigate when Open source is clicked on an available citation", async () => {
    const user = userEvent.setup();
    vi.spyOn(api, "fetchResearchWorkspaces").mockResolvedValue([workspace({ evidence_count: 1 })]);
    mockDetailFetches(workspace({ evidence_count: 1 }), [evidenceItem()]);
    vi.spyOn(api, "generateDeterministicBrief").mockResolvedValue(briefVersion());
    const onNavigate = vi.fn();

    render(<ResearchCentre onBack={noop} onNavigate={onNavigate} />);
    await user.click(await screen.findByText("Tokenizer choice for Alpha"));
    await user.click(screen.getByRole("radio", { name: /briefs/i }));
    await user.click(await screen.findByRole("button", { name: /generate evidence outline/i }));
    await user.click(await screen.findByRole("button", { name: /open source/i }));

    expect(onNavigate).toHaveBeenCalledWith("domain:build");
  });

  it("every evidence-tab control has an accessible name reachable by keyboard", async () => {
    vi.spyOn(api, "fetchResearchWorkspaces").mockResolvedValue([workspace({ evidence_count: 1 })]);
    mockDetailFetches(workspace({ evidence_count: 1 }), [evidenceItem()]);
    const user = userEvent.setup();

    render(<ResearchCentre onBack={noop} onNavigate={noop} />);
    await user.click(await screen.findByText("Tokenizer choice for Alpha"));
    await screen.findByText("Tokenizer research");

    for (const control of [...screen.getAllByRole("checkbox"), ...screen.getAllByRole("combobox")]) {
      expect(control).toHaveAccessibleName();
    }
  });

  it("goes back to the workspace list via the back button", async () => {
    const user = userEvent.setup();
    vi.spyOn(api, "fetchResearchWorkspaces").mockResolvedValue([workspace()]);
    mockDetailFetches(workspace());

    render(<ResearchCentre onBack={noop} onNavigate={noop} />);
    await user.click(await screen.findByText("Tokenizer choice for Alpha"));
    await user.click(await screen.findByRole("button", { name: /all workspaces/i }));

    expect(await screen.findByRole("button", { name: /create workspace/i })).toBeInTheDocument();
  });
});
