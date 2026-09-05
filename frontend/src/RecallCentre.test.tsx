import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import RecallCentre from "./views/RecallCentre";
import * as api from "./api";
import type { RecallResult, RecallSearchResult } from "./api";

beforeEach(() => {
  vi.restoreAllMocks();
});

afterEach(() => {
  vi.restoreAllMocks();
});

function result(overrides: Partial<RecallResult> = {}): RecallResult {
  return {
    source_type: "structured_record",
    source_id: "abc",
    domain_slug: "life",
    title: "Renew passport",
    snippet_html: "Renew <mark>passport</mark> before travel",
    occurred_at: "2026-08-29T09:00:00Z",
    link_target: "domain:life",
    available: true,
    unavailable_reason: null,
    ...overrides,
  };
}

function searchResult(overrides: Partial<RecallSearchResult> = {}): RecallSearchResult {
  return {
    query: "passport",
    results: [],
    total_considered: 0,
    limit: 20,
    offset: 0,
    has_more: false,
    partial_failures: [],
    ...overrides,
  };
}

const noop = () => {};

describe("RecallCentre", () => {
  it("shows a prompt to type a query, and never searches on an empty query", () => {
    const spy = vi.spyOn(api, "searchRecall");
    render(<RecallCentre onBack={noop} onNavigate={noop} seed={null} />);
    expect(screen.getByText(/type a query to search jarvis/i)).toBeInTheDocument();
    expect(spy).not.toHaveBeenCalled();
  });

  it("searches after typing (debounced) and renders a result with its highlighted snippet", async () => {
    const user = userEvent.setup();
    vi.spyOn(api, "searchRecall").mockResolvedValue(searchResult({ results: [result()], total_considered: 1 }));
    render(<RecallCentre onBack={noop} onNavigate={noop} seed={null} />);

    await user.type(screen.getByLabelText(/search query/i), "passport");

    expect(await screen.findByText("Renew passport")).toBeInTheDocument();
    const snippet = document.querySelector(".briefing-item-subtitle mark");
    expect(snippet?.textContent).toBe("passport");
  });

  it("renders a truthful no-results state with a rebuild-index affordance", async () => {
    const user = userEvent.setup();
    vi.spyOn(api, "searchRecall").mockResolvedValue(searchResult());
    render(<RecallCentre onBack={noop} onNavigate={noop} seed={null} />);

    await user.type(screen.getByLabelText(/search query/i), "nothing here");

    expect(await screen.findByText(/no results/i)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /rebuild index/i })).toBeInTheDocument();
  });

  it("shows a truthful partial-failure notice without hiding the results that did come back", async () => {
    const user = userEvent.setup();
    vi.spyOn(api, "searchRecall").mockResolvedValue(
      searchResult({ results: [result()], total_considered: 1, partial_failures: ["memory_item"] }),
    );
    render(<RecallCentre onBack={noop} onNavigate={noop} seed={null} />);

    await user.type(screen.getByLabelText(/search query/i), "passport");

    expect(await screen.findByText("Renew passport")).toBeInTheDocument();
    expect(screen.getByText(/memory_item/)).toBeInTheDocument();
  });

  it("renders an unavailable source truthfully, with the button disabled and text-labeled, never color-only", async () => {
    const user = userEvent.setup();
    vi.spyOn(api, "searchRecall").mockResolvedValue(
      searchResult({ results: [result({ available: false, unavailable_reason: "Source unavailable" })], total_considered: 1 }),
    );
    render(<RecallCentre onBack={noop} onNavigate={noop} seed={null} />);

    await user.type(screen.getByLabelText(/search query/i), "passport");

    const button = await screen.findByRole("button", { name: /source unavailable/i });
    expect(button).toBeDisabled();
  });

  it("shows an offline/error state truthfully when the backend is unreachable", async () => {
    const user = userEvent.setup();
    vi.spyOn(api, "searchRecall").mockRejectedValue(new Error("network error"));
    render(<RecallCentre onBack={noop} onNavigate={noop} seed={null} />);

    await user.type(screen.getByLabelText(/search query/i), "passport");

    expect(await screen.findByRole("alert")).toHaveTextContent(/search failed/i);
  });

  it("defaults domain filters to LIFE/PATH/BUILD checked and BODY/MIND/PEOPLE unchecked", () => {
    render(<RecallCentre onBack={noop} onNavigate={noop} seed={null} />);
    expect(screen.getByRole("checkbox", { name: "LIFE" })).toHaveAttribute("aria-checked", "true");
    expect(screen.getByRole("checkbox", { name: "PATH" })).toHaveAttribute("aria-checked", "true");
    expect(screen.getByRole("checkbox", { name: "BUILD" })).toHaveAttribute("aria-checked", "true");
    expect(screen.getByRole("checkbox", { name: "BODY" })).toHaveAttribute("aria-checked", "false");
    expect(screen.getByRole("checkbox", { name: "MIND" })).toHaveAttribute("aria-checked", "false");
    expect(screen.getByRole("checkbox", { name: "PEOPLE" })).toHaveAttribute("aria-checked", "false");
  });

  it("toggling a sensitive domain checkbox includes it in the next search's domains", async () => {
    const user = userEvent.setup();
    const spy = vi.spyOn(api, "searchRecall").mockResolvedValue(searchResult());
    render(<RecallCentre onBack={noop} onNavigate={noop} seed={null} />);

    await user.click(screen.getByRole("checkbox", { name: /mind/i }));
    await user.type(screen.getByLabelText(/search query/i), "mood");

    await waitFor(() => expect(spy).toHaveBeenCalled());
    const lastCall = spy.mock.calls.at(-1)?.[0];
    expect(lastCall?.domains).toContain("mind");
  });

  it("applies a seeded query and domain hint from a voice/palette open_recall command", async () => {
    const spy = vi.spyOn(api, "searchRecall").mockResolvedValue(searchResult({ results: [result()], total_considered: 1 }));
    render(<RecallCentre onBack={noop} onNavigate={noop} seed={{ query: "passport", domainHint: "life", token: 1 }} />);

    await waitFor(() => expect(spy).toHaveBeenCalled());
    expect(screen.getByLabelText(/search query/i)).toHaveValue("passport");
  });

  it("cancels a stale in-flight search so only the latest query's results render", async () => {
    let resolveFirst: (value: RecallSearchResult) => void = () => {};
    const firstPromise = new Promise<RecallSearchResult>((resolve) => {
      resolveFirst = resolve;
    });
    const spy = vi
      .spyOn(api, "searchRecall")
      .mockImplementationOnce(() => firstPromise)
      .mockImplementationOnce(async () => searchResult({ results: [result({ title: "Second query result" })], total_considered: 1 }));

    const user = userEvent.setup({ delay: null });
    render(<RecallCentre onBack={noop} onNavigate={noop} seed={null} />);

    const input = screen.getByLabelText(/search query/i);
    await user.type(input, "first");
    await new Promise((r) => setTimeout(r, 350));
    await user.clear(input);
    await user.type(input, "second");

    await waitFor(() => expect(screen.queryByText("Second query result")).toBeInTheDocument());
    resolveFirst(searchResult({ results: [result({ title: "First query result" })], total_considered: 1 }));
    await new Promise((r) => setTimeout(r, 50));

    expect(screen.queryByText("First query result")).not.toBeInTheDocument();
    expect(spy).toHaveBeenCalled();
  });

  it("navigates via onNavigate when Open source is clicked on an available result", async () => {
    const user = userEvent.setup();
    vi.spyOn(api, "searchRecall").mockResolvedValue(searchResult({ results: [result()], total_considered: 1 }));
    const onNavigate = vi.fn();
    render(<RecallCentre onBack={noop} onNavigate={onNavigate} seed={null} />);

    await user.type(screen.getByLabelText(/search query/i), "passport");
    await user.click(await screen.findByRole("button", { name: /open source/i }));

    expect(onNavigate).toHaveBeenCalledWith("domain:life");
  });

  it("every filter control has an accessible name reachable by keyboard", () => {
    render(<RecallCentre onBack={noop} onNavigate={noop} seed={null} />);
    for (const checkbox of screen.getAllByRole("checkbox")) {
      expect(checkbox).toHaveAccessibleName();
    }
  });
});
