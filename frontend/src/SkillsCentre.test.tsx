import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import SkillsCentre from "./views/SkillsCentre";
import * as api from "./api";
import type { ActionProposal, Domain, Skill, SkillVersion } from "./api";

const DOMAINS: Domain[] = [
  { id: "1", slug: "body", name: "BODY", description: "Fitness.", created_at: "", updated_at: "" },
];

beforeEach(() => {
  vi.restoreAllMocks();
});

afterEach(() => {
  vi.restoreAllMocks();
});

function makeSkill(overrides: Partial<Skill> = {}): Skill {
  return {
    id: "skill-1",
    slug: "test-skill",
    name: "Test skill",
    description: "A test skill.",
    domain_id: null,
    invocation_phrases: [],
    status: "draft",
    created_by: "user",
    current_version_id: "v1",
    created_at: "2026-01-01T00:00:00Z",
    updated_at: "2026-01-01T00:00:00Z",
    ...overrides,
  };
}

function makeVersion(overrides: Partial<SkillVersion> = {}): SkillVersion {
  return {
    id: "v1",
    skill_id: "skill-1",
    version_number: 1,
    name: "Test skill",
    description: "A test skill.",
    workflow_steps: [{ capability_id: "memory.create", description: "Log a fact" }],
    change_reason: null,
    created_at: "2026-01-01T00:00:00Z",
    ...overrides,
  };
}

describe("SkillsCentre", () => {
  it("lists draft skills by default and creates a new draft", async () => {
    const user = userEvent.setup();
    vi.spyOn(api, "fetchDomains").mockResolvedValue(DOMAINS);
    vi.spyOn(api, "listSkills").mockResolvedValue([makeSkill()]);
    const createSpy = vi.spyOn(api, "createSkill").mockResolvedValue(makeSkill({ id: "skill-2", slug: "new-one" }));

    render(<SkillsCentre onBack={() => {}} />);
    expect(await screen.findByText("Test skill")).toBeInTheDocument();

    await user.type(screen.getByPlaceholderText(/slug/i), "new-one");
    await user.type(screen.getByPlaceholderText(/^name$/i), "New skill");
    await user.type(screen.getByPlaceholderText(/description/i), "d");
    await user.click(screen.getByRole("button", { name: /create draft/i }));

    await waitFor(() => expect(createSpy).toHaveBeenCalled());
    expect(createSpy.mock.calls[0][0]).toMatchObject({ slug: "new-one", name: "New skill" });
  });

  it("reviews a skill, activates it, and invokes it, creating proposals", async () => {
    const user = userEvent.setup();
    const version = makeVersion();
    let current = makeSkill({ domain_id: "1" });

    vi.spyOn(api, "fetchDomains").mockResolvedValue(DOMAINS);
    vi.spyOn(api, "listSkills").mockImplementation(async () => [current]);
    vi.spyOn(api, "getSkill").mockImplementation(async () => ({ skill: current, versions: [version] }));
    vi.spyOn(api, "activateSkill").mockImplementation(async () => {
      current = { ...current, status: "active" };
      return current;
    });

    const proposal: ActionProposal = {
      id: "prop-1",
      capability_id: "memory.create",
      domain_id: "1",
      permission_level: "confirm",
      arguments: {},
      reason: "r",
      expected_effect: "e",
      payload_digest: "d",
      status: "proposed",
      source: "skill:skill-1:v1",
      confirmation_token: null,
      confirmation_expires_at: null,
      result: null,
      error_summary: null,
      created_at: "t",
      updated_at: "t",
    };
    const invokeSpy = vi.spyOn(api, "invokeSkill").mockResolvedValue({ proposals: [proposal] });

    render(<SkillsCentre onBack={() => {}} />);
    await screen.findByText("Test skill");

    await user.click(screen.getByRole("button", { name: /^review$/i }));
    await waitFor(() => expect(document.body.textContent).toContain("Log a fact"));

    await user.click(screen.getAllByRole("button", { name: /^activate$/i })[0]);
    await waitFor(() => expect(document.body.textContent).toContain("Invoke this skill"));

    const invokeForm = await screen.findByRole("button", { name: /invoke/i });
    await user.click(invokeForm);
    await waitFor(() => expect(invokeSpy).toHaveBeenCalledWith("skill-1", { step_arguments: [] }));
    expect(await screen.findByText(/Created 1 action proposal/)).toBeInTheDocument();
  });

  it("edit demotes an active skill to draft in the UI flow", async () => {
    const user = userEvent.setup();
    const skill = makeSkill({ status: "active" });
    const version = makeVersion();

    vi.spyOn(api, "fetchDomains").mockResolvedValue(DOMAINS);
    vi.spyOn(api, "listSkills").mockResolvedValue([skill]);
    vi.spyOn(api, "getSkill").mockResolvedValue({ skill, versions: [version] });
    const editSpy = vi.spyOn(api, "editSkill").mockResolvedValue({ ...skill, status: "draft" });

    render(<SkillsCentre onBack={() => {}} />);
    // Switch to the "active" tab to see this skill.
    await user.click(screen.getByRole("radio", { name: "active" }));
    await screen.findByText("Test skill");

    await user.click(screen.getByRole("button", { name: /^review$/i }));
    await waitFor(() => expect(document.body.textContent).toContain("Log a fact"));

    await user.click(screen.getByRole("button", { name: /edit \(new version\)/i }));
    await user.click(screen.getByRole("button", { name: /save as new version/i }));

    await waitFor(() => expect(editSpy).toHaveBeenCalled());
  });
});
