import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import MemoryCentre from "./views/MemoryCentre";
import * as api from "./api";
import type { MemoryItem } from "./api";

beforeEach(() => {
  vi.restoreAllMocks();
});

afterEach(() => {
  vi.restoreAllMocks();
});

const GLOBAL_MEMORY: MemoryItem = {
  id: "mem-1",
  scope: "global",
  domain_id: null,
  kind: "preference",
  title: "Preferred name",
  status: "active",
  importance: 3,
  confidence: 1,
  sensitivity: "normal",
  event_date: null,
  created_at: "",
  updated_at: "",
  current_version_id: "v1",
  supersedes_id: null,
  superseded_by_id: null,
};

describe("MemoryCentre", () => {
  it("explains local, model-independent storage", async () => {
    vi.spyOn(api, "listMemories").mockResolvedValue([]);
    render(<MemoryCentre onBack={() => {}} />);
    expect(await screen.findByText(/never in Hermes/i)).toBeInTheDocument();
    expect(screen.getByText(/never loses this memory/i)).toBeInTheDocument();
  });

  it("lists existing global memories", async () => {
    vi.spyOn(api, "listMemories").mockResolvedValue([GLOBAL_MEMORY]);
    render(<MemoryCentre onBack={() => {}} />);
    expect(await screen.findByText("Preferred name")).toBeInTheDocument();
  });

  it("creates a new global memory via the Remember form", async () => {
    vi.spyOn(api, "listMemories").mockResolvedValue([]);
    const createSpy = vi.spyOn(api, "createMemory").mockResolvedValue(GLOBAL_MEMORY);
    const user = userEvent.setup();

    render(<MemoryCentre onBack={() => {}} />);
    await screen.findByText(/no global memories yet/i);

    await user.type(screen.getByPlaceholderText("Title"), "Preferred name");
    await user.type(screen.getByPlaceholderText("Content"), "Call him Bernardo.");
    await user.click(screen.getByRole("button", { name: /^remember$/i }));

    expect(createSpy).toHaveBeenCalledWith(
      expect.objectContaining({ scope: "global", title: "Preferred name", content: "Call him Bernardo." }),
    );
  });

  it("saves an onboarding field as a global memory", async () => {
    vi.spyOn(api, "listMemories").mockResolvedValue([]);
    const createSpy = vi.spyOn(api, "createMemory").mockResolvedValue(GLOBAL_MEMORY);
    const user = userEvent.setup();

    render(<MemoryCentre onBack={() => {}} />);
    const input = await screen.findByLabelText("Preferred name");
    await user.type(input, "Bernardo");

    const saveButtons = screen.getAllByRole("button", { name: /^save$/i });
    await user.click(saveButtons[0]);

    expect(createSpy).toHaveBeenCalledWith(
      expect.objectContaining({ title: "Preferred name", content: "Bernardo" }),
    );
  });

  it("searches memories", async () => {
    vi.spyOn(api, "listMemories").mockResolvedValue([]);
    const searchSpy = vi.spyOn(api, "searchMemories").mockResolvedValue([GLOBAL_MEMORY]);
    const user = userEvent.setup();

    render(<MemoryCentre onBack={() => {}} />);
    await screen.findByText(/no global memories yet/i);

    await user.type(screen.getByPlaceholderText("Search memories…"), "name");
    await user.click(screen.getByRole("button", { name: /^search$/i }));

    expect(searchSpy).toHaveBeenCalledWith("name");
    await screen.findByText((_, element) => element?.tagName === "STRONG" && element.textContent === "Preferred name");
  });

  it("returns to the home view", async () => {
    vi.spyOn(api, "listMemories").mockResolvedValue([]);
    const onBack = vi.fn();
    const user = userEvent.setup();
    render(<MemoryCentre onBack={onBack} />);
    await user.click(screen.getByRole("button", { name: /back to jarvis/i }));
    expect(onBack).toHaveBeenCalled();
  });
});
