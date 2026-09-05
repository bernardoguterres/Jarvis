import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import DecisionCentre from "./views/DecisionCentre";
import * as api from "./api";
import type {
  Decision,
  DecisionAssessment,
  DecisionBriefVersion,
  DecisionCriterion,
  DecisionEvidence,
  DecisionFactor,
  DecisionFinalVersion,
  DecisionOption,
  DecisionOutcomeReview,
  DecisionScoreBreakdown,
  RecallResult,
  RecallSearchResult,
  ResearchWorkspace,
} from "./api";

beforeEach(() => {
  vi.restoreAllMocks();
});

afterEach(() => {
  vi.restoreAllMocks();
});

const noop = () => {};

function decision(overrides: Partial<Decision> = {}): Decision {
  return {
    id: "dec-1",
    title: "Which tokenizer for Alpha?",
    description: null,
    domain_slug: null,
    research_workspace_id: null,
    included_domain_slugs: ["life", "path", "build"],
    effective_domain_slugs: ["life", "path", "build"],
    status: "draft",
    review_date: null,
    cost_of_delay_note: null,
    info_confidence: null,
    reversibility: null,
    supersedes_decision_id: null,
    superseded_by_decision_id: null,
    abandoned_at: null,
    abandoned_reason: null,
    option_count: 0,
    criterion_count: 0,
    evidence_count: 0,
    latest_brief_version: null,
    is_decided: false,
    review_due: false,
    created_at: "2026-08-29T09:00:00Z",
    updated_at: "2026-08-29T09:00:00Z",
    ...overrides,
  };
}

function option(overrides: Partial<DecisionOption> = {}): DecisionOption {
  return {
    id: "opt-1",
    decision_id: "dec-1",
    name: "BPE",
    description: null,
    benefits: "Handles rare words well.",
    costs: null,
    risks: null,
    reversibility: null,
    status: "active",
    rank: 0,
    created_at: "2026-08-29T09:00:00Z",
    updated_at: "2026-08-29T09:00:00Z",
    ...overrides,
  };
}

function criterion(overrides: Partial<DecisionCriterion> = {}): DecisionCriterion {
  return {
    id: "crit-1",
    decision_id: "dec-1",
    name: "Cost",
    description: null,
    weight: 3,
    rank: 0,
    created_at: "2026-08-29T09:00:00Z",
    updated_at: "2026-08-29T09:00:00Z",
    ...overrides,
  };
}

function evidenceItem(overrides: Partial<DecisionEvidence> = {}): DecisionEvidence {
  return {
    id: "ev-1",
    decision_id: "dec-1",
    source_type: "message",
    source_id: "msg-1",
    research_evidence_id: null,
    linked_option_id: null,
    domain_slug: "build",
    title_snapshot: "Tokenizer research",
    snippet_snapshot: "BPE handles rare words well.",
    occurred_at_snapshot: "2026-08-29T09:00:00Z",
    stance: "supporting",
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

function factor(overrides: Partial<DecisionFactor> = {}): DecisionFactor {
  return {
    id: "fac-1",
    decision_id: "dec-1",
    kind: "risk",
    content: "Vendor could deprecate the library.",
    linked_option_id: null,
    status: "open",
    resolution_note: null,
    resolved_at: null,
    created_at: "2026-08-29T09:00:00Z",
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

function scoreBreakdown(overrides: Partial<DecisionScoreBreakdown> = {}): DecisionScoreBreakdown {
  return {
    options: [
      { option_id: "opt-1", option_name: "BPE", total_score: 9, assessed_count: 1, total_criteria: 1, missing_criterion_ids: [], missing_criterion_names: [] },
    ],
    ranked_option_ids: ["opt-1"],
    tied: false,
    sensitivity_warnings: [],
    incomplete: false,
    ...overrides,
  };
}

function briefVersion(overrides: Partial<DecisionBriefVersion> = {}): DecisionBriefVersion {
  return {
    id: "brief-1",
    decision_id: "dec-1",
    version_number: 1,
    source: "deterministic",
    status: "ok",
    title: "Which tokenizer for Alpha? — decision brief",
    sections_json: JSON.stringify({ sections: [{ kind: "score_breakdown", options: [{ option_name: "BPE", total_score: 9 }] }], missing_info_warnings: [] }),
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

function finalVersion(overrides: Partial<DecisionFinalVersion> = {}): DecisionFinalVersion {
  return {
    id: "final-1",
    decision_id: "dec-1",
    version_number: 1,
    selected_option_id: "opt-1",
    selected_option_name: "BPE",
    rationale: "Best balance of cost and coverage.",
    decision_confidence: 4,
    decided_at: "2026-08-29T09:10:00Z",
    created_at: "2026-08-29T09:10:00Z",
    ...overrides,
  };
}

function outcomeReview(overrides: Partial<DecisionOutcomeReview> = {}): DecisionOutcomeReview {
  return {
    id: "review-1",
    decision_id: "dec-1",
    decision_final_version_id: "final-1",
    what_happened: "Worked well in production.",
    intended_outcome_achieved: true,
    confidence_was_appropriate: true,
    would_decide_same_again: true,
    lessons_learned: null,
    reviewed_at: "2026-09-15T09:00:00Z",
    created_at: "2026-09-15T09:00:00Z",
    ...overrides,
  };
}

function researchWorkspace(overrides: Partial<ResearchWorkspace> = {}): ResearchWorkspace {
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

function mockDetailFetches(
  d: Decision,
  opts: {
    options?: DecisionOption[]; criteria?: DecisionCriterion[]; evidence?: DecisionEvidence[]; factors?: DecisionFactor[];
    assessments?: DecisionAssessment[];
  } = {},
) {
  vi.spyOn(api, "fetchDecision").mockResolvedValue(d);
  vi.spyOn(api, "listDecisionOptions").mockResolvedValue(opts.options ?? []);
  vi.spyOn(api, "listDecisionCriteria").mockResolvedValue(opts.criteria ?? []);
  vi.spyOn(api, "listDecisionEvidence").mockResolvedValue(opts.evidence ?? []);
  vi.spyOn(api, "listDecisionFactors").mockResolvedValue(opts.factors ?? []);
  vi.spyOn(api, "listDecisionAssessments").mockResolvedValue(opts.assessments ?? []);
  vi.spyOn(api, "fetchDecisionScoreBreakdown").mockResolvedValue(scoreBreakdown({ options: [] }));
  vi.spyOn(api, "fetchResearchWorkspaces").mockResolvedValue([]);
}

describe("DecisionCentre — decision list", () => {
  it("shows a loading state, then an empty state with no decisions", async () => {
    vi.spyOn(api, "fetchDecisions").mockResolvedValue([]);
    vi.spyOn(api, "fetchDecisionCalibrationSummary").mockResolvedValue({
      reviewed_count: 0, minimum_sample: 5, has_enough_data: false,
      confidence_appropriate_rate: null, would_decide_same_rate: null, outcome_achieved_rate: null,
    });
    render(<DecisionCentre onBack={noop} onNavigate={noop} />);
    expect(await screen.findByText(/no decisions yet/i)).toBeInTheDocument();
  });

  it("shows a truthful error state when the backend is unreachable", async () => {
    vi.spyOn(api, "fetchDecisions").mockRejectedValue(new Error("network error"));
    vi.spyOn(api, "fetchDecisionCalibrationSummary").mockRejectedValue(new Error("network error"));
    render(<DecisionCentre onBack={noop} onNavigate={noop} />);
    expect(await screen.findByRole("alert")).toHaveTextContent(/could not load decisions/i);
  });

  it("renders existing decisions in a ledger with status and counts", async () => {
    vi.spyOn(api, "fetchDecisions").mockResolvedValue([decision({ option_count: 2, evidence_count: 3, status: "evaluating" })]);
    vi.spyOn(api, "fetchDecisionCalibrationSummary").mockResolvedValue({
      reviewed_count: 0, minimum_sample: 5, has_enough_data: false,
      confidence_appropriate_rate: null, would_decide_same_rate: null, outcome_achieved_rate: null,
    });
    render(<DecisionCentre onBack={noop} onNavigate={noop} />);
    expect(await screen.findByText("Which tokenizer for Alpha?")).toBeInTheDocument();
    expect(screen.getByText(/2 options · 3 evidence/i)).toBeInTheDocument();
    expect(screen.getByText("Evaluating")).toBeInTheDocument();
  });

  it("shows the calibration summary once enough decisions have been reviewed", async () => {
    vi.spyOn(api, "fetchDecisions").mockResolvedValue([]);
    vi.spyOn(api, "fetchDecisionCalibrationSummary").mockResolvedValue({
      reviewed_count: 6, minimum_sample: 5, has_enough_data: true,
      confidence_appropriate_rate: 0.8, would_decide_same_rate: 0.9, outcome_achieved_rate: 0.7,
    });
    render(<DecisionCentre onBack={noop} onNavigate={noop} />);
    expect(await screen.findByText(/confidence was appropriate 80% of the time/i)).toBeInTheDocument();
    expect(screen.getByText(/you'd decide the same again 90% of the time/i)).toBeInTheDocument();
  });

  it("creates a decision and opens its detail view", async () => {
    const user = userEvent.setup();
    vi.spyOn(api, "fetchDecisions").mockResolvedValue([]);
    vi.spyOn(api, "fetchDecisionCalibrationSummary").mockResolvedValue({
      reviewed_count: 0, minimum_sample: 5, has_enough_data: false,
      confidence_appropriate_rate: null, would_decide_same_rate: null, outcome_achieved_rate: null,
    });
    const createSpy = vi.spyOn(api, "createDecision").mockResolvedValue(decision());
    mockDetailFetches(decision());
    vi.spyOn(api, "listDecisionBriefs").mockResolvedValue([]);

    render(<DecisionCentre onBack={noop} onNavigate={noop} />);
    await user.type(await screen.findByLabelText(/decision question/i), "Which tokenizer for Alpha?");
    await user.click(screen.getByRole("button", { name: /^create decision$/i }));

    await waitFor(() => expect(createSpy).toHaveBeenCalledWith(
      expect.objectContaining({ title: "Which tokenizer for Alpha?", included_domain_slugs: ["life", "path", "build"] }),
    ));
    expect(await screen.findByRole("button", { name: /all decisions/i })).toBeInTheDocument();
  });

  it("every domain-picker checkbox has an accessible name reachable by keyboard", async () => {
    vi.spyOn(api, "fetchDecisions").mockResolvedValue([]);
    vi.spyOn(api, "fetchDecisionCalibrationSummary").mockResolvedValue({
      reviewed_count: 0, minimum_sample: 5, has_enough_data: false,
      confidence_appropriate_rate: null, would_decide_same_rate: null, outcome_achieved_rate: null,
    });
    render(<DecisionCentre onBack={noop} onNavigate={noop} />);
    await screen.findByText(/no decisions yet/i);
    for (const checkbox of screen.getAllByRole("checkbox")) {
      expect(checkbox).toHaveAccessibleName();
    }
  });
});

describe("DecisionCentre — options and deciding", () => {
  async function openDecision(user: ReturnType<typeof userEvent.setup>, d: Decision, opts: Parameters<typeof mockDetailFetches>[1] = {}) {
    vi.spyOn(api, "fetchDecisions").mockResolvedValue([d]);
    vi.spyOn(api, "fetchDecisionCalibrationSummary").mockResolvedValue({
      reviewed_count: 0, minimum_sample: 5, has_enough_data: false,
      confidence_appropriate_rate: null, would_decide_same_rate: null, outcome_achieved_rate: null,
    });
    mockDetailFetches(d, opts);
    vi.spyOn(api, "listDecisionBriefs").mockResolvedValue([]);
    render(<DecisionCentre onBack={noop} onNavigate={noop} />);
    await user.click(await screen.findByText(d.title));
  }

  it("adds an option via the options tab", async () => {
    const user = userEvent.setup();
    await openDecision(user, decision());
    const addSpy = vi.spyOn(api, "addDecisionOption").mockResolvedValue(option());

    await user.click(screen.getByRole("radio", { name: /^options/i }));
    await user.type(await screen.findByLabelText(/option name/i), "BPE");
    await user.click(screen.getByRole("button", { name: /^add option$/i }));

    await waitFor(() => expect(addSpy).toHaveBeenCalledWith("dec-1", expect.objectContaining({ name: "BPE" })));
  });

  it("eliminates an option via its row action", async () => {
    const user = userEvent.setup();
    await openDecision(user, decision({ option_count: 1 }), { options: [option()] });
    const updateSpy = vi.spyOn(api, "updateDecisionOption").mockResolvedValue(option({ status: "eliminated" }));

    await user.click(screen.getByRole("radio", { name: /^options/i }));
    await user.click(await screen.findByRole("button", { name: /^eliminate$/i }));

    await waitFor(() => expect(updateSpy).toHaveBeenCalledWith("dec-1", "opt-1", { status: "eliminated" }));
  });

  it("records a decision via the decide form", async () => {
    const user = userEvent.setup();
    await openDecision(user, decision({ status: "evaluating", option_count: 1 }), { options: [option()] });
    const decideSpy = vi.spyOn(api, "decideDecision").mockResolvedValue(decision({ status: "decided" }));

    await user.click(screen.getByRole("radio", { name: /^options/i }));
    await user.selectOptions(await screen.findByLabelText(/selected option/i), "opt-1");
    await user.type(screen.getByLabelText(/^rationale$/i), "Best balance of cost and coverage.");
    await user.click(screen.getByRole("button", { name: /^decide$/i }));

    await waitFor(() => expect(decideSpy).toHaveBeenCalledWith("dec-1", {
      selected_option_id: "opt-1", rationale: "Best balance of cost and coverage.", decision_confidence: 3,
    }));
  });

  it("does not show the decide form for a decision that is already decided", async () => {
    const user = userEvent.setup();
    await openDecision(user, decision({ status: "decided", option_count: 1 }), { options: [option({ status: "chosen" })] });

    await user.click(screen.getByRole("radio", { name: /^options/i }));
    await screen.findByText("BPE");
    expect(screen.queryByLabelText(/selected option/i)).not.toBeInTheDocument();
  });
});

describe("DecisionCentre — criteria and scoring", () => {
  it("adds a criterion and shows the score breakdown", async () => {
    const user = userEvent.setup();
    vi.spyOn(api, "fetchDecisions").mockResolvedValue([decision({ option_count: 1 })]);
    vi.spyOn(api, "fetchDecisionCalibrationSummary").mockResolvedValue({
      reviewed_count: 0, minimum_sample: 5, has_enough_data: false,
      confidence_appropriate_rate: null, would_decide_same_rate: null, outcome_achieved_rate: null,
    });
    mockDetailFetches(decision({ option_count: 1 }), { options: [option()], criteria: [criterion()] });
    vi.spyOn(api, "listDecisionBriefs").mockResolvedValue([]);
    vi.spyOn(api, "fetchDecisionScoreBreakdown").mockResolvedValue(scoreBreakdown());
    const addSpy = vi.spyOn(api, "addDecisionCriterion").mockResolvedValue(criterion());

    render(<DecisionCentre onBack={noop} onNavigate={noop} />);
    await user.click(await screen.findByText("Which tokenizer for Alpha?"));
    await user.click(screen.getByRole("radio", { name: /^criteria$/i }));
    await user.type(await screen.findByLabelText(/criterion name/i), "Cost");
    await user.click(screen.getByRole("button", { name: /^add$/i }));

    await waitFor(() => expect(addSpy).toHaveBeenCalledWith("dec-1", { name: "Cost", weight: 3 }));
    expect(await screen.findByText(/9 points/i)).toBeInTheDocument();
  });

  it("sets an assessment score from the matrix and refreshes the breakdown", async () => {
    const user = userEvent.setup();
    vi.spyOn(api, "fetchDecisions").mockResolvedValue([decision({ option_count: 1 })]);
    vi.spyOn(api, "fetchDecisionCalibrationSummary").mockResolvedValue({
      reviewed_count: 0, minimum_sample: 5, has_enough_data: false,
      confidence_appropriate_rate: null, would_decide_same_rate: null, outcome_achieved_rate: null,
    });
    mockDetailFetches(decision({ option_count: 1 }), { options: [option()], criteria: [criterion()] });
    vi.spyOn(api, "listDecisionBriefs").mockResolvedValue([]);
    vi.spyOn(api, "fetchDecisionScoreBreakdown").mockResolvedValue(scoreBreakdown({ options: [] }));
    const assessSpy = vi.spyOn(api, "setDecisionAssessment").mockResolvedValue({
      id: "assess-1", option_id: "opt-1", criterion_id: "crit-1", score: 3, note: null,
      created_at: "2026-08-29T09:00:00Z", updated_at: "2026-08-29T09:00:00Z",
    });

    render(<DecisionCentre onBack={noop} onNavigate={noop} />);
    await user.click(await screen.findByText("Which tokenizer for Alpha?"));
    await user.click(screen.getByRole("radio", { name: /^criteria$/i }));
    const select = await screen.findByRole("combobox", { name: /score for bpe on cost/i });
    await user.selectOptions(select, "3");

    await waitFor(() => expect(assessSpy).toHaveBeenCalledWith("dec-1", { option_id: "opt-1", criterion_id: "crit-1", score: 3 }));
  });

  it("pre-fills the assessment matrix from existing scores instead of always showing unassessed", async () => {
    const user = userEvent.setup();
    vi.spyOn(api, "fetchDecisions").mockResolvedValue([decision({ option_count: 1 })]);
    vi.spyOn(api, "fetchDecisionCalibrationSummary").mockResolvedValue({
      reviewed_count: 0, minimum_sample: 5, has_enough_data: false,
      confidence_appropriate_rate: null, would_decide_same_rate: null, outcome_achieved_rate: null,
    });
    const existingAssessment: DecisionAssessment = {
      id: "assess-1", option_id: "opt-1", criterion_id: "crit-1", score: 4, note: null,
      created_at: "2026-08-29T09:00:00Z", updated_at: "2026-08-29T09:00:00Z",
    };
    mockDetailFetches(decision({ option_count: 1 }), { options: [option()], criteria: [criterion()], assessments: [existingAssessment] });
    vi.spyOn(api, "listDecisionBriefs").mockResolvedValue([]);

    render(<DecisionCentre onBack={noop} onNavigate={noop} />);
    await user.click(await screen.findByText("Which tokenizer for Alpha?"));
    await user.click(screen.getByRole("radio", { name: /^criteria$/i }));

    const select = await screen.findByRole("combobox", { name: /score for bpe on cost/i });
    await waitFor(() => expect(select).toHaveValue("4"));
  });

  it("shows a tied warning and sensitivity warnings when present", async () => {
    const user = userEvent.setup();
    vi.spyOn(api, "fetchDecisions").mockResolvedValue([decision({ option_count: 2 })]);
    vi.spyOn(api, "fetchDecisionCalibrationSummary").mockResolvedValue({
      reviewed_count: 0, minimum_sample: 5, has_enough_data: false,
      confidence_appropriate_rate: null, would_decide_same_rate: null, outcome_achieved_rate: null,
    });
    mockDetailFetches(decision({ option_count: 2 }), { options: [option(), option({ id: "opt-2", name: "WordPiece" })], criteria: [criterion()] });
    vi.spyOn(api, "listDecisionBriefs").mockResolvedValue([]);
    vi.spyOn(api, "fetchDecisionScoreBreakdown").mockResolvedValue(scoreBreakdown({
      options: [
        { option_id: "opt-1", option_name: "BPE", total_score: 9, assessed_count: 1, total_criteria: 1, missing_criterion_ids: [], missing_criterion_names: [] },
        { option_id: "opt-2", option_name: "WordPiece", total_score: 9, assessed_count: 1, total_criteria: 1, missing_criterion_ids: [], missing_criterion_names: [] },
      ],
      ranked_option_ids: ["opt-1", "opt-2"],
      tied: true,
      sensitivity_warnings: [{ criterion_id: "crit-1", criterion_name: "Cost", explanation: "Changing Cost by one point would change the ranking." }],
    }));

    render(<DecisionCentre onBack={noop} onNavigate={noop} />);
    await user.click(await screen.findByText("Which tokenizer for Alpha?"));
    await user.click(screen.getByRole("radio", { name: /^criteria$/i }));

    expect(await screen.findByText(/the top options are tied/i)).toBeInTheDocument();
    expect(screen.getByText(/changing cost by one point/i)).toBeInTheDocument();
  });
});

describe("DecisionCentre — evidence", () => {
  it("searches for evidence, shows a no-results state, and a partial-failure notice", async () => {
    const user = userEvent.setup();
    vi.spyOn(api, "fetchDecisions").mockResolvedValue([decision()]);
    vi.spyOn(api, "fetchDecisionCalibrationSummary").mockResolvedValue({
      reviewed_count: 0, minimum_sample: 5, has_enough_data: false,
      confidence_appropriate_rate: null, would_decide_same_rate: null, outcome_achieved_rate: null,
    });
    mockDetailFetches(decision());
    vi.spyOn(api, "listDecisionBriefs").mockResolvedValue([]);
    vi.spyOn(api, "searchDecisionEvidence").mockResolvedValue(recallSearchResult({ partial_failures: ["memory_item"] }));

    render(<DecisionCentre onBack={noop} onNavigate={noop} />);
    await user.click(await screen.findByText("Which tokenizer for Alpha?"));
    await user.click(screen.getByRole("radio", { name: /^evidence/i }));
    await user.type(await screen.findByPlaceholderText(/search jarvis for evidence/i), "tokenizer");

    expect(await screen.findByText(/no results in this decision's included domains/i)).toBeInTheDocument();
    expect(screen.getByText(/memory_item/)).toBeInTheDocument();
  });

  it("adds a search result as evidence and marks it Added", async () => {
    const user = userEvent.setup();
    vi.spyOn(api, "fetchDecisions").mockResolvedValue([decision()]);
    vi.spyOn(api, "fetchDecisionCalibrationSummary").mockResolvedValue({
      reviewed_count: 0, minimum_sample: 5, has_enough_data: false,
      confidence_appropriate_rate: null, would_decide_same_rate: null, outcome_achieved_rate: null,
    });
    mockDetailFetches(decision());
    vi.spyOn(api, "listDecisionBriefs").mockResolvedValue([]);
    vi.spyOn(api, "searchDecisionEvidence").mockResolvedValue(recallSearchResult({ results: [recallResult()] }));
    const addSpy = vi.spyOn(api, "addDecisionEvidence").mockResolvedValue(evidenceItem());

    render(<DecisionCentre onBack={noop} onNavigate={noop} />);
    await user.click(await screen.findByText("Which tokenizer for Alpha?"));
    await user.click(screen.getByRole("radio", { name: /^evidence/i }));
    await user.type(await screen.findByPlaceholderText(/search jarvis for evidence/i), "tokenizer");
    await user.click(await screen.findByRole("button", { name: /add as evidence/i }));

    await waitFor(() => expect(addSpy).toHaveBeenCalledWith("dec-1", { source_type: "message", source_id: "msg-1" }));
  });

  it("renders linked evidence with stance and an unavailable source truthfully", async () => {
    const user = userEvent.setup();
    vi.spyOn(api, "fetchDecisions").mockResolvedValue([decision({ evidence_count: 1 })]);
    vi.spyOn(api, "fetchDecisionCalibrationSummary").mockResolvedValue({
      reviewed_count: 0, minimum_sample: 5, has_enough_data: false,
      confidence_appropriate_rate: null, would_decide_same_rate: null, outcome_achieved_rate: null,
    });
    mockDetailFetches(decision({ evidence_count: 1 }), { evidence: [evidenceItem({ available: false, unavailable_reason: "Source unavailable" })] });
    vi.spyOn(api, "listDecisionBriefs").mockResolvedValue([]);

    render(<DecisionCentre onBack={noop} onNavigate={noop} />);
    await user.click(await screen.findByText("Which tokenizer for Alpha?"));
    await user.click(screen.getByRole("radio", { name: /^evidence/i }));

    expect(await screen.findByText("Tokenizer research")).toBeInTheDocument();
    expect(screen.getByText("Supporting")).toBeInTheDocument();
    expect(screen.getByText(/source unavailable/i)).toBeInTheDocument();
  });
});

describe("DecisionCentre — factors", () => {
  it("adds a factor and resolves it", async () => {
    const user = userEvent.setup();
    vi.spyOn(api, "fetchDecisions").mockResolvedValue([decision()]);
    vi.spyOn(api, "fetchDecisionCalibrationSummary").mockResolvedValue({
      reviewed_count: 0, minimum_sample: 5, has_enough_data: false,
      confidence_appropriate_rate: null, would_decide_same_rate: null, outcome_achieved_rate: null,
    });
    mockDetailFetches(decision(), { factors: [factor()] });
    vi.spyOn(api, "listDecisionBriefs").mockResolvedValue([]);
    const addSpy = vi.spyOn(api, "addDecisionFactor").mockResolvedValue(factor());
    const resolveSpy = vi.spyOn(api, "resolveDecisionFactor").mockResolvedValue(factor({ status: "resolved", resolution_note: "Mitigated." }));

    render(<DecisionCentre onBack={noop} onNavigate={noop} />);
    await user.click(await screen.findByText("Which tokenizer for Alpha?"));
    await user.click(screen.getByRole("radio", { name: /^factors$/i }));
    await user.type(await screen.findByLabelText(/factor content/i), "Vendor could deprecate the library.");
    await user.click(screen.getByRole("button", { name: /^add$/i }));
    await waitFor(() => expect(addSpy).toHaveBeenCalledWith("dec-1", { kind: "assumption", content: "Vendor could deprecate the library." }));

    await user.click(await screen.findByRole("button", { name: /^resolve$/i }));
    await waitFor(() => expect(resolveSpy).toHaveBeenCalledWith("dec-1", "fac-1"));
  });
});

describe("DecisionCentre — briefs", () => {
  it("generates a deterministic brief and renders its score breakdown", async () => {
    const user = userEvent.setup();
    vi.spyOn(api, "fetchDecisions").mockResolvedValue([decision({ option_count: 1 })]);
    vi.spyOn(api, "fetchDecisionCalibrationSummary").mockResolvedValue({
      reviewed_count: 0, minimum_sample: 5, has_enough_data: false,
      confidence_appropriate_rate: null, would_decide_same_rate: null, outcome_achieved_rate: null,
    });
    mockDetailFetches(decision({ option_count: 1 }), { options: [option()] });
    vi.spyOn(api, "listDecisionBriefs").mockResolvedValue([]);
    vi.spyOn(api, "generateDecisionDeterministicBrief").mockResolvedValue(briefVersion());

    render(<DecisionCentre onBack={noop} onNavigate={noop} />);
    await user.click(await screen.findByText("Which tokenizer for Alpha?"));
    await user.click(screen.getByRole("radio", { name: /^briefs$/i }));
    await user.click(await screen.findByRole("button", { name: /generate decision brief/i }));

    expect(await screen.findByText("Score breakdown")).toBeInTheDocument();
    expect(screen.getByText(/bpe: 9 points/i)).toBeInTheDocument();
  });

  it("shows a distinct model-unavailable state when the critique fails with a 502", async () => {
    const user = userEvent.setup();
    vi.spyOn(api, "fetchDecisions").mockResolvedValue([decision({ option_count: 1 })]);
    vi.spyOn(api, "fetchDecisionCalibrationSummary").mockResolvedValue({
      reviewed_count: 0, minimum_sample: 5, has_enough_data: false,
      confidence_appropriate_rate: null, would_decide_same_rate: null, outcome_achieved_rate: null,
    });
    mockDetailFetches(decision({ option_count: 1 }), { options: [option()] });
    vi.spyOn(api, "listDecisionBriefs").mockResolvedValue([]);
    vi.spyOn(api, "draftDecisionCritique").mockRejectedValue(new api.ApiError(502, "Jarvis could not draft this critique."));

    render(<DecisionCentre onBack={noop} onNavigate={noop} />);
    await user.click(await screen.findByText("Which tokenizer for Alpha?"));
    await user.click(screen.getByRole("radio", { name: /^briefs$/i }));
    await user.click(await screen.findByRole("button", { name: /ask jarvis to challenge this decision/i }));

    expect(await screen.findByRole("alert")).toHaveTextContent(/jarvis model is currently unavailable/i);
  });

  it("shows a visible validation-error state for a critique with a flagged citation", async () => {
    const user = userEvent.setup();
    vi.spyOn(api, "fetchDecisions").mockResolvedValue([decision({ option_count: 1 })]);
    vi.spyOn(api, "fetchDecisionCalibrationSummary").mockResolvedValue({
      reviewed_count: 0, minimum_sample: 5, has_enough_data: false,
      confidence_appropriate_rate: null, would_decide_same_rate: null, outcome_achieved_rate: null,
    });
    mockDetailFetches(decision({ option_count: 1 }), { options: [option()] });
    vi.spyOn(api, "listDecisionBriefs").mockResolvedValue([
      { id: "brief-2", version_number: 2, source: "model", status: "invalid_citations", generated_at: "2026-08-29T09:10:00Z" },
    ]);
    vi.spyOn(api, "getDecisionBrief").mockResolvedValue(
      briefVersion({
        id: "brief-2",
        version_number: 2,
        source: "model",
        status: "invalid_citations",
        validation_issues: ["Citation [7] does not correspond to any evidence supplied to the model and was not linked."],
        sections_json: JSON.stringify({ sections: [{ kind: "model_text", text: "A claim [1]. A hallucinated claim [7]." }] }),
        model_meta: { provider: "hermes", model: "openai-codex/gpt-5.6-terra", latency_ms: 900, evidence_ids_used: ["ev-1"] },
      }),
    );

    render(<DecisionCentre onBack={noop} onNavigate={noop} />);
    await user.click(await screen.findByText("Which tokenizer for Alpha?"));
    await user.click(screen.getByRole("radio", { name: /^briefs$/i }));
    await user.click(await screen.findByText(/v2 — jarvis model-generated critique/i));

    expect(await screen.findByRole("alert")).toHaveTextContent(/does not correspond to any evidence/i);
  });

  it("disables brief generation and shows a notice when there are no options yet", async () => {
    const user = userEvent.setup();
    vi.spyOn(api, "fetchDecisions").mockResolvedValue([decision()]);
    vi.spyOn(api, "fetchDecisionCalibrationSummary").mockResolvedValue({
      reviewed_count: 0, minimum_sample: 5, has_enough_data: false,
      confidence_appropriate_rate: null, would_decide_same_rate: null, outcome_achieved_rate: null,
    });
    mockDetailFetches(decision());
    vi.spyOn(api, "listDecisionBriefs").mockResolvedValue([]);

    render(<DecisionCentre onBack={noop} onNavigate={noop} />);
    await user.click(await screen.findByText("Which tokenizer for Alpha?"));
    await user.click(screen.getByRole("radio", { name: /^briefs$/i }));

    expect(await screen.findByText(/add at least one option first/i)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /generate decision brief/i })).toBeDisabled();
    expect(screen.getByRole("button", { name: /ask jarvis to challenge this decision/i })).toBeDisabled();
  });
});

describe("DecisionCentre — outcome review", () => {
  it("shows decision history and adds an outcome review", async () => {
    const user = userEvent.setup();
    vi.spyOn(api, "fetchDecisions").mockResolvedValue([decision({ status: "decided" })]);
    vi.spyOn(api, "fetchDecisionCalibrationSummary").mockResolvedValue({
      reviewed_count: 0, minimum_sample: 5, has_enough_data: false,
      confidence_appropriate_rate: null, would_decide_same_rate: null, outcome_achieved_rate: null,
    });
    mockDetailFetches(decision({ status: "decided" }));
    vi.spyOn(api, "listDecisionBriefs").mockResolvedValue([]);
    vi.spyOn(api, "listDecisionFinalVersions").mockResolvedValue([finalVersion()]);
    vi.spyOn(api, "listDecisionOutcomeReviews").mockResolvedValue([]);
    const addReviewSpy = vi.spyOn(api, "addDecisionOutcomeReview").mockResolvedValue(outcomeReview());

    render(<DecisionCentre onBack={noop} onNavigate={noop} />);
    await user.click(await screen.findByText("Which tokenizer for Alpha?"));
    await user.click(screen.getByRole("radio", { name: /^outcome$/i }));

    expect(await screen.findByText(/best balance of cost and coverage/i)).toBeInTheDocument();
    await user.type(screen.getByLabelText(/what happened/i), "Worked well in production.");
    await user.click(screen.getByRole("button", { name: /save outcome review/i }));

    await waitFor(() => expect(addReviewSpy).toHaveBeenCalledWith("dec-1", expect.objectContaining({ what_happened: "Worked well in production." })));
  });

  it("does not show the review form before any decision has been made", async () => {
    const user = userEvent.setup();
    vi.spyOn(api, "fetchDecisions").mockResolvedValue([decision()]);
    vi.spyOn(api, "fetchDecisionCalibrationSummary").mockResolvedValue({
      reviewed_count: 0, minimum_sample: 5, has_enough_data: false,
      confidence_appropriate_rate: null, would_decide_same_rate: null, outcome_achieved_rate: null,
    });
    mockDetailFetches(decision());
    vi.spyOn(api, "listDecisionBriefs").mockResolvedValue([]);
    vi.spyOn(api, "listDecisionFinalVersions").mockResolvedValue([]);
    vi.spyOn(api, "listDecisionOutcomeReviews").mockResolvedValue([]);

    render(<DecisionCentre onBack={noop} onNavigate={noop} />);
    await user.click(await screen.findByText("Which tokenizer for Alpha?"));
    await user.click(screen.getByRole("radio", { name: /^outcome$/i }));

    expect(await screen.findByText(/this decision has not been decided yet/i)).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /save outcome review/i })).not.toBeInTheDocument();
  });
});

describe("DecisionCentre — lifecycle and overview", () => {
  it("starts evaluating a draft decision", async () => {
    const user = userEvent.setup();
    vi.spyOn(api, "fetchDecisions").mockResolvedValue([decision()]);
    vi.spyOn(api, "fetchDecisionCalibrationSummary").mockResolvedValue({
      reviewed_count: 0, minimum_sample: 5, has_enough_data: false,
      confidence_appropriate_rate: null, would_decide_same_rate: null, outcome_achieved_rate: null,
    });
    mockDetailFetches(decision());
    vi.spyOn(api, "listDecisionBriefs").mockResolvedValue([]);
    const startSpy = vi.spyOn(api, "startEvaluatingDecision").mockResolvedValue(decision({ status: "evaluating" }));

    render(<DecisionCentre onBack={noop} onNavigate={noop} />);
    await user.click(await screen.findByText("Which tokenizer for Alpha?"));
    await user.click(await screen.findByRole("button", { name: /start evaluating/i }));

    await waitFor(() => expect(startSpy).toHaveBeenCalledWith("dec-1"));
  });

  it("reopens a decided decision", async () => {
    const user = userEvent.setup();
    vi.spyOn(api, "fetchDecisions").mockResolvedValue([decision({ status: "decided" })]);
    vi.spyOn(api, "fetchDecisionCalibrationSummary").mockResolvedValue({
      reviewed_count: 0, minimum_sample: 5, has_enough_data: false,
      confidence_appropriate_rate: null, would_decide_same_rate: null, outcome_achieved_rate: null,
    });
    mockDetailFetches(decision({ status: "decided" }));
    vi.spyOn(api, "listDecisionBriefs").mockResolvedValue([]);
    const reopenSpy = vi.spyOn(api, "reopenDecision").mockResolvedValue(decision({ status: "reopened" }));

    render(<DecisionCentre onBack={noop} onNavigate={noop} />);
    await user.click(await screen.findByText("Which tokenizer for Alpha?"));
    await user.click(await screen.findByRole("button", { name: /^reopen$/i }));

    await waitFor(() => expect(reopenSpy).toHaveBeenCalledWith("dec-1"));
  });

  it("abandons a decision with a reason", async () => {
    const user = userEvent.setup();
    vi.spyOn(api, "fetchDecisions").mockResolvedValue([decision()]);
    vi.spyOn(api, "fetchDecisionCalibrationSummary").mockResolvedValue({
      reviewed_count: 0, minimum_sample: 5, has_enough_data: false,
      confidence_appropriate_rate: null, would_decide_same_rate: null, outcome_achieved_rate: null,
    });
    mockDetailFetches(decision());
    vi.spyOn(api, "listDecisionBriefs").mockResolvedValue([]);
    const abandonSpy = vi.spyOn(api, "abandonDecision").mockResolvedValue(decision({ status: "abandoned" }));

    render(<DecisionCentre onBack={noop} onNavigate={noop} />);
    await user.click(await screen.findByText("Which tokenizer for Alpha?"));
    await user.click(await screen.findByRole("button", { name: /^abandon$/i }));

    await waitFor(() => expect(abandonSpy).toHaveBeenCalledWith("dec-1"));
  });

  it("shows a read-only notice for a superseded decision", async () => {
    const user = userEvent.setup();
    const superseded = decision({ status: "superseded", superseded_by_decision_id: "dec-2" });
    vi.spyOn(api, "fetchDecisions").mockResolvedValue([superseded]);
    vi.spyOn(api, "fetchDecisionCalibrationSummary").mockResolvedValue({
      reviewed_count: 0, minimum_sample: 5, has_enough_data: false,
      confidence_appropriate_rate: null, would_decide_same_rate: null, outcome_achieved_rate: null,
    });
    mockDetailFetches(superseded);
    vi.spyOn(api, "listDecisionBriefs").mockResolvedValue([]);

    render(<DecisionCentre onBack={noop} onNavigate={noop} />);
    await user.click(await screen.findByText("Which tokenizer for Alpha?"));

    expect(await screen.findByText(/this decision was superseded/i)).toBeInTheDocument();
  });

  it("saves overview details and links a research workspace", async () => {
    const user = userEvent.setup();
    vi.spyOn(api, "fetchDecisions").mockResolvedValue([decision()]);
    vi.spyOn(api, "fetchDecisionCalibrationSummary").mockResolvedValue({
      reviewed_count: 0, minimum_sample: 5, has_enough_data: false,
      confidence_appropriate_rate: null, would_decide_same_rate: null, outcome_achieved_rate: null,
    });
    mockDetailFetches(decision());
    vi.spyOn(api, "listDecisionBriefs").mockResolvedValue([]);
    vi.spyOn(api, "fetchResearchWorkspaces").mockResolvedValue([researchWorkspace()]);
    const updateSpy = vi.spyOn(api, "updateDecision").mockResolvedValue(decision({ cost_of_delay_note: "Delays cost a sprint." }));
    const linkSpy = vi.spyOn(api, "linkDecisionResearchWorkspace").mockResolvedValue(decision({ research_workspace_id: "ws-1" }));

    render(<DecisionCentre onBack={noop} onNavigate={noop} />);
    await user.click(await screen.findByText("Which tokenizer for Alpha?"));
    await user.type(await screen.findByLabelText(/cost of delay/i), "Delays cost a sprint.");
    await user.click(screen.getByRole("button", { name: /save details/i }));
    await waitFor(() => expect(updateSpy).toHaveBeenCalledWith("dec-1", expect.objectContaining({ cost_of_delay_note: "Delays cost a sprint." })));

    await user.selectOptions(await screen.findByRole("combobox", { name: /linked research workspace/i }), "ws-1");
    await waitFor(() => expect(linkSpy).toHaveBeenCalledWith("dec-1", "ws-1"));
  });

  it("navigates via onNavigate when Open source is clicked on an available citation", async () => {
    const user = userEvent.setup();
    vi.spyOn(api, "fetchDecisions").mockResolvedValue([decision({ option_count: 1 })]);
    vi.spyOn(api, "fetchDecisionCalibrationSummary").mockResolvedValue({
      reviewed_count: 0, minimum_sample: 5, has_enough_data: false,
      confidence_appropriate_rate: null, would_decide_same_rate: null, outcome_achieved_rate: null,
    });
    mockDetailFetches(decision({ option_count: 1 }), { options: [option()] });
    vi.spyOn(api, "listDecisionBriefs").mockResolvedValue([]);
    vi.spyOn(api, "generateDecisionDeterministicBrief").mockResolvedValue(briefVersion());
    const onNavigate = vi.fn();

    render(<DecisionCentre onBack={noop} onNavigate={onNavigate} />);
    await user.click(await screen.findByText("Which tokenizer for Alpha?"));
    await user.click(screen.getByRole("radio", { name: /^briefs$/i }));
    await user.click(await screen.findByRole("button", { name: /generate decision brief/i }));
    await user.click(await screen.findByRole("button", { name: /open source/i }));

    expect(onNavigate).toHaveBeenCalledWith("domain:build");
  });

  it("goes back to the decision list via the back button", async () => {
    const user = userEvent.setup();
    vi.spyOn(api, "fetchDecisions").mockResolvedValue([decision()]);
    vi.spyOn(api, "fetchDecisionCalibrationSummary").mockResolvedValue({
      reviewed_count: 0, minimum_sample: 5, has_enough_data: false,
      confidence_appropriate_rate: null, would_decide_same_rate: null, outcome_achieved_rate: null,
    });
    mockDetailFetches(decision());
    vi.spyOn(api, "listDecisionBriefs").mockResolvedValue([]);

    render(<DecisionCentre onBack={noop} onNavigate={noop} />);
    await user.click(await screen.findByText("Which tokenizer for Alpha?"));
    await user.click(await screen.findByRole("button", { name: /all decisions/i }));

    expect(await screen.findByRole("button", { name: /^create decision$/i })).toBeInTheDocument();
  });
});
