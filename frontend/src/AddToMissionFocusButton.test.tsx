import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import AddToMissionFocusButton from "./components/AddToMissionFocusButton";
import * as api from "./api";

beforeEach(() => {
  vi.restoreAllMocks();
});

afterEach(() => {
  vi.restoreAllMocks();
});

describe("AddToMissionFocusButton (Phase 12C)", () => {
  it("shows 'Add to Mission Focus' when not pinned", () => {
    render(<AddToMissionFocusButton sourceType="life_task" sourceId="t1" onChanged={() => {}} />);
    expect(screen.getByRole("button", { name: /add to mission focus/i })).toBeInTheDocument();
  });

  it("expands to a form requiring a next action, and pins on submit", async () => {
    const user = userEvent.setup();
    const createSpy = vi.spyOn(api, "createMissionFocusPin").mockResolvedValue({
      id: "pin-1", source_type: "life_task", source_id: "t1", domain_slug: "life", rank: 1,
      next_action: "Book slot", target_at: null, blocker: null, status: "active", pinned_at: "", unpinned_at: null,
      title: "Renew passport", subtitle: null, link_target: "domain:life", available: true, resolved: false, change_state: "new",
    });
    const onChanged = vi.fn();

    render(<AddToMissionFocusButton sourceType="life_task" sourceId="t1" onChanged={onChanged} />);
    await user.click(screen.getByRole("button", { name: /add to mission focus/i }));

    const input = screen.getByPlaceholderText(/what's the next concrete step/i);
    await user.type(input, "Book slot");
    await user.click(screen.getByRole("button", { name: /^pin to mission focus$/i }));

    await waitFor(() => expect(createSpy).toHaveBeenCalledWith({ source_type: "life_task", source_id: "t1", next_action: "Book slot" }));
    await waitFor(() => expect(onChanged).toHaveBeenCalled());
  });

  it("shows a truthful error (e.g. limit reached) instead of silently failing", async () => {
    const user = userEvent.setup();
    vi.spyOn(api, "createMissionFocusPin").mockRejectedValue(new Error("Mission Focus already has 5 active pins."));

    render(<AddToMissionFocusButton sourceType="life_task" sourceId="t1" onChanged={() => {}} />);
    await user.click(screen.getByRole("button", { name: /add to mission focus/i }));
    await user.type(screen.getByPlaceholderText(/what's the next concrete step/i), "x");
    await user.click(screen.getByRole("button", { name: /^pin to mission focus$/i }));

    expect(await screen.findByText(/already has 5 active pins/i)).toBeInTheDocument();
  });

  it("cancel collapses the form without pinning", async () => {
    const user = userEvent.setup();
    const createSpy = vi.spyOn(api, "createMissionFocusPin");
    render(<AddToMissionFocusButton sourceType="life_task" sourceId="t1" onChanged={() => {}} />);
    await user.click(screen.getByRole("button", { name: /add to mission focus/i }));
    await user.click(screen.getByRole("button", { name: /^cancel$/i }));

    expect(screen.getByRole("button", { name: /add to mission focus/i })).toBeInTheDocument();
    expect(createSpy).not.toHaveBeenCalled();
  });

  it("shows the truthful pinned state and rank when already pinned", () => {
    render(
      <AddToMissionFocusButton
        sourceType="life_task"
        sourceId="t1"
        existingPin={{
          id: "pin-1", source_type: "life_task", source_id: "t1", domain_slug: "life", rank: 2,
          next_action: "Book slot", target_at: null, blocker: null, status: "active", pinned_at: "", unpinned_at: null,
          title: "Renew passport", subtitle: null, link_target: "domain:life", available: true, resolved: false, change_state: "ongoing",
        }}
        onChanged={() => {}}
      />,
    );
    expect(screen.getByText("PINNED #2")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /remove from focus/i })).toBeInTheDocument();
  });

  it("Remove from focus unpins and never touches the source directly", async () => {
    const user = userEvent.setup();
    const unpinSpy = vi.spyOn(api, "unpinMissionFocusPin").mockResolvedValue({
      id: "pin-1", source_type: "life_task", source_id: "t1", domain_slug: "life", rank: 2,
      next_action: "Book slot", target_at: null, blocker: null, status: "unpinned", pinned_at: "", unpinned_at: "",
      title: "Renew passport", subtitle: null, link_target: "domain:life", available: true, resolved: false, change_state: null,
    });
    const onChanged = vi.fn();
    render(
      <AddToMissionFocusButton
        sourceType="life_task"
        sourceId="t1"
        existingPin={{
          id: "pin-1", source_type: "life_task", source_id: "t1", domain_slug: "life", rank: 2,
          next_action: "Book slot", target_at: null, blocker: null, status: "active", pinned_at: "", unpinned_at: null,
          title: "Renew passport", subtitle: null, link_target: "domain:life", available: true, resolved: false, change_state: "ongoing",
        }}
        onChanged={onChanged}
      />,
    );
    await user.click(screen.getByRole("button", { name: /remove from focus/i }));
    await waitFor(() => expect(unpinSpy).toHaveBeenCalledWith("pin-1"));
    await waitFor(() => expect(onChanged).toHaveBeenCalled());
  });
});
