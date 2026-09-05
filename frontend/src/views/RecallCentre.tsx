import { useEffect, useRef, useState } from "react";
import {
  rebuildRecallIndex,
  searchRecall,
  type RecallResult,
  type RecallSourceType,
} from "../api";
import { isNavigateTarget, type NavigateTarget } from "../commands/registry";
import { DOMAIN_SLUG_ORDER, type DomainSlug } from "../domainOrder";
import DomainGlyph from "../components/DomainGlyph";
import { ConsoleHeader, ConsoleModule, MiniCoreIndicator } from "../components/console/Console";
import { formatDateTime } from "../formatDateTime";

interface RecallCentreProps {
  onBack: () => void;
  onNavigate: (target: NavigateTarget) => void;
  /** Set only when Recall was opened via a voice/palette "search Jarvis
   * for X" command (App.tsx's `executeSafeAction`) — pre-seeds the query
   * and optional domain scope. `token` changes on every command so this
   * re-applies even if the exact same query is searched twice in a row;
   * every other entry point (Systems menu, palette's static action, the
   * keyboard shortcut) passes `null`, which leaves Recall at its own
   * ordinary empty-query defaults. */
  seed: { query: string; domainHint: string | null; token: number } | null;
}

// BODY/MIND/PEOPLE require explicit inclusion — CLAUDE.md's Recall
// durable rule, identical to the Home briefing's own structural default.
// Omitting `domains` entirely from the request would already default to
// this same set server-side, but naming it here explicitly keeps the
// checkbox UI and the actual request in obvious agreement.
const DEFAULT_DOMAINS: DomainSlug[] = ["life", "path", "build"];

const SOURCE_TYPE_GROUPS: Array<{ label: string; types: RecallSourceType[] }> = [
  { label: "Conversations", types: ["conversation", "message"] },
  { label: "Memory", types: ["memory_item"] },
  { label: "Records & summaries", types: ["structured_record", "domain_summary"] },
  { label: "Documents", types: ["document", "document_chunk"] },
  { label: "Calendar", types: ["calendar_event"] },
  { label: "Actions", types: ["action_proposal"] },
  { label: "Routines", types: ["routine_run"] },
  { label: "Mission Control", types: ["mission_control_session"] },
];
const ALL_SOURCE_TYPES: RecallSourceType[] = SOURCE_TYPE_GROUPS.flatMap((g) => g.types);

const SOURCE_TYPE_LABELS: Record<RecallSourceType, string> = {
  conversation: "Conversation",
  message: "Message",
  memory_item: "Memory",
  structured_record: "Record",
  domain_summary: "Domain summary",
  document: "Document",
  document_chunk: "Document",
  calendar_event: "Calendar event",
  action_proposal: "Action",
  routine_run: "Routine run",
  mission_control_session: "Focus session",
};

const PAGE_SIZE = 20;
const DEBOUNCE_MS = 300;

function formatOccurredAt(iso: string | null): string | null {
  if (!iso) return null;
  return formatDateTime(iso);
}

function RecallCentre({ onBack, onNavigate, seed }: RecallCentreProps) {
  const [query, setQuery] = useState("");
  const [domains, setDomains] = useState<DomainSlug[]>(DEFAULT_DOMAINS);
  const [sourceTypes, setSourceTypes] = useState<RecallSourceType[]>(ALL_SOURCE_TYPES);
  const [offset, setOffset] = useState(0);
  const [results, setResults] = useState<RecallResult[] | null>(null);
  const [totalConsidered, setTotalConsidered] = useState(0);
  const [hasMore, setHasMore] = useState(false);
  const [partialFailures, setPartialFailures] = useState<string[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [rebuilding, setRebuilding] = useState(false);
  const [rebuildMessage, setRebuildMessage] = useState<string | null>(null);
  const inputRef = useRef<HTMLInputElement | null>(null);
  const abortRef = useRef<AbortController | null>(null);

  useEffect(() => {
    inputRef.current?.focus();
  }, []);

  // Apply a command-seeded query/domain exactly once per token, never on
  // an ordinary re-render — a fresh seed always resets to page 0.
  useEffect(() => {
    if (!seed) return;
    setQuery(seed.query);
    if (seed.domainHint) {
      setDomains([seed.domainHint as DomainSlug]);
    }
    setOffset(0);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [seed?.token]);

  // Debounced, cancel-stale-response search. A plain `cancelled` flag
  // (the same pattern GeneralConversation.tsx already uses for its own
  // async effects) covers unmount/re-trigger; the AbortController on top
  // of it also cancels the actual in-flight HTTP request rather than
  // just ignoring its result, so a slow first keystroke can never
  // overwrite a fast later one even if it resolves after it.
  useEffect(() => {
    if (!query.trim()) {
      setResults(null);
      setError(null);
      setPartialFailures([]);
      setTotalConsidered(0);
      setHasMore(false);
      return;
    }

    let cancelled = false;
    const timeoutId = window.setTimeout(() => {
      abortRef.current?.abort();
      const controller = new AbortController();
      abortRef.current = controller;
      setLoading(true);
      setError(null);
      searchRecall(
        {
          q: query.trim(),
          domains,
          sourceTypes,
          limit: PAGE_SIZE,
          offset,
        },
        controller.signal,
      )
        .then((data) => {
          if (cancelled) return;
          setResults(data.results);
          setTotalConsidered(data.total_considered);
          setHasMore(data.has_more);
          setPartialFailures(data.partial_failures);
        })
        .catch((err: unknown) => {
          if (cancelled) return;
          if (err instanceof DOMException && err.name === "AbortError") return;
          setError("Search failed. The backend may be unreachable.");
          setResults(null);
        })
        .finally(() => {
          if (!cancelled) setLoading(false);
        });
    }, DEBOUNCE_MS);

    return () => {
      cancelled = true;
      window.clearTimeout(timeoutId);
    };
  }, [query, domains, sourceTypes, offset]);

  function toggleDomain(slug: DomainSlug) {
    setOffset(0);
    setDomains((prev) => (prev.includes(slug) ? prev.filter((d) => d !== slug) : [...prev, slug]));
  }

  function toggleSourceGroup(types: RecallSourceType[]) {
    setOffset(0);
    setSourceTypes((prev) => {
      const allSelected = types.every((t) => prev.includes(t));
      return allSelected ? prev.filter((t) => !types.includes(t)) : [...new Set([...prev, ...types])];
    });
  }

  async function handleRebuild() {
    setRebuilding(true);
    setRebuildMessage(null);
    try {
      const result = await rebuildRecallIndex();
      setRebuildMessage(`Rebuilt the index: ${result.indexed_count} item${result.indexed_count === 1 ? "" : "s"} indexed.`);
      setOffset(0);
    } catch {
      setRebuildMessage("Could not rebuild the index.");
    } finally {
      setRebuilding(false);
    }
  }

  function handleOpenSource(result: RecallResult) {
    if (isNavigateTarget(result.link_target)) {
      onNavigate(result.link_target);
    }
  }

  return (
    <div className="domain-view">
      <button type="button" className="back-button" onClick={onBack}>
        ← Back to Jarvis
      </button>

      <ConsoleHeader
        indicator={<MiniCoreIndicator />}
        eyebrow="Centre"
        title="Recall"
        description="Deterministic local search across everything Jarvis has stored — never a model call, never a summary, never a command. Retrieved text is always inert, displayed data."
        meta={
          results !== null && (
            <span>
              {totalConsidered} result{totalConsidered === 1 ? "" : "s"}
            </span>
          )
        }
      />

      <ConsoleModule title="Search" ariaLabel="Search Jarvis">
        <form className="message-form-actions" onSubmit={(e) => e.preventDefault()}>
          <input
            ref={inputRef}
            type="text"
            placeholder="Search Jarvis…"
            value={query}
            onChange={(e) => {
              setQuery(e.target.value);
              setOffset(0);
            }}
            aria-label="Search query"
          />
        </form>
      </ConsoleModule>

      <ConsoleModule title="Domains" ariaLabel="Domain filter">
        <fieldset className="mc-domain-picker">
          <legend className="sr-only">Which domains to search</legend>
          <span role="group" aria-label="Domains">
            {DOMAIN_SLUG_ORDER.map((slug) => (
              <button
                key={slug}
                type="button"
                role="checkbox"
                aria-checked={domains.includes(slug)}
                className={`briefing-item-control${domains.includes(slug) ? " mc-duration-selected" : ""}`}
                onClick={() => toggleDomain(slug)}
              >
                <DomainGlyph slug={slug} />
                {slug.toUpperCase()}
              </button>
            ))}
          </span>
        </fieldset>
      </ConsoleModule>

      <ConsoleModule title="Source types" ariaLabel="Source type filter">
        <span role="group" aria-label="Source types" className="mc-duration-picker">
          {SOURCE_TYPE_GROUPS.map((group) => {
            const allSelected = group.types.every((t) => sourceTypes.includes(t));
            return (
              <button
                key={group.label}
                type="button"
                role="checkbox"
                aria-checked={allSelected}
                className={`briefing-item-control${allSelected ? " mc-duration-selected" : ""}`}
                onClick={() => toggleSourceGroup(group.types)}
              >
                {group.label}
              </button>
            );
          })}
        </span>
      </ConsoleModule>

      {error && (
        <p className="error-banner" role="alert">
          {error}
        </p>
      )}

      {partialFailures.length > 0 && (
        <p className="notice" role="status">
          Some results may be missing — the following sources did not respond this search: {partialFailures.join(", ")}.
        </p>
      )}

      <ConsoleModule title="Results" ariaLabel="Search results">
        <div aria-live="polite">
          {loading && <p className="ledger-empty">Searching…</p>}
          {!loading && !query.trim() && <p className="ledger-empty">Type a query to search Jarvis.</p>}
          {!loading && query.trim() && results !== null && results.length === 0 && !error && (
            <p className="ledger-empty">
              No results.{" "}
              <button type="button" className="action-note" onClick={handleRebuild} disabled={rebuilding}>
                {rebuilding ? "Rebuilding…" : "Rebuild index"}
              </button>
            </p>
          )}
        </div>

        {results !== null && results.length > 0 && (
          <ul className="briefing-strip-list">
            {results.map((result) => {
              const occurred = formatOccurredAt(result.occurred_at);
              return (
                <li key={`${result.source_type}:${result.source_id}`} className="briefing-item-row">
                  <div className="briefing-item tone-neutral">
                    {result.domain_slug && (
                      <span className="mc-candidate-glyph" aria-hidden="true">
                        <DomainGlyph slug={result.domain_slug} />
                      </span>
                    )}
                    <span className="briefing-item-body">
                      <span className="briefing-item-title">{result.title}</span>
                      <span
                        className="briefing-item-subtitle"
                        // Already HTML-escaped with <mark> highlight spans
                        // by the backend (recall_service.make_snippet_html)
                        // — rendered verbatim, never re-escaped.
                        dangerouslySetInnerHTML={{ __html: result.snippet_html }}
                      />
                      <span className="briefing-item-freshness">
                        {SOURCE_TYPE_LABELS[result.source_type]}
                        {occurred ? ` · ${occurred}` : ""}
                        {result.domain_slug ? ` · ${result.domain_slug.toUpperCase()}` : " · Global"}
                      </span>
                    </span>
                    <button
                      type="button"
                      className="briefing-strip-button"
                      onClick={() => handleOpenSource(result)}
                      disabled={!result.available || !isNavigateTarget(result.link_target)}
                    >
                      {result.available ? "Open source" : result.unavailable_reason ?? "Source unavailable"}
                    </button>
                  </div>
                </li>
              );
            })}
          </ul>
        )}

        {results !== null && results.length > 0 && (
          <span className="mission-focus-add-actions">
            <button type="button" onClick={() => setOffset((o) => Math.max(0, o - PAGE_SIZE))} disabled={offset === 0}>
              Previous
            </button>
            <button type="button" onClick={() => setOffset((o) => o + PAGE_SIZE)} disabled={!hasMore}>
              Next
            </button>
          </span>
        )}

        {rebuildMessage && (
          <p className="notice" role="status">
            {rebuildMessage}
          </p>
        )}
      </ConsoleModule>
    </div>
  );
}

export default RecallCentre;
