import { useEffect, useMemo, useRef, useState } from "react";
import {
  ApiError,
  addResearchEvidence,
  addResearchNote,
  archiveResearchNote,
  archiveResearchWorkspace,
  createResearchWorkspace,
  draftBriefWithJarvis,
  fetchResearchWorkspace,
  fetchResearchWorkspaces,
  generateDeterministicBrief,
  getResearchBrief,
  listResearchBriefs,
  listResearchEvidence,
  listResearchNotes,
  removeResearchEvidence,
  reopenResearchWorkspace,
  searchResearchEvidence,
  updateResearchEvidence,
  updateResearchWorkspace,
  type RecallResult,
  type RecallSourceType,
  type ResearchBriefVersion,
  type ResearchBriefVersionSummary,
  type ResearchDomainSlug,
  type ResearchEvidence,
  type ResearchEvidenceClassification,
  type ResearchNote,
  type ResearchWorkspace,
} from "../api";
import { isNavigateTarget, type NavigateTarget } from "../commands/registry";
import { splitOnCitations } from "../citationText";
import { DOMAIN_SLUG_ORDER } from "../domainOrder";
import { SENSITIVE_SLUGS } from "../sensitiveDomains";
import { formatDateTime } from "../formatDateTime";
import DomainGlyph from "../components/DomainGlyph";
import { ConsoleHeader, ConsoleModule, MiniCoreIndicator } from "../components/console/Console";

interface ResearchCentreProps {
  onBack: () => void;
  onNavigate: (target: NavigateTarget) => void;
}

const DEFAULT_DOMAINS: ResearchDomainSlug[] = ["life", "path", "build"];

const CLASSIFICATION_ORDER: ResearchEvidenceClassification[] = [
  "supporting",
  "contradicting",
  "contextual",
  "unresolved",
];

const CLASSIFICATION_LABEL: Record<ResearchEvidenceClassification, string> = {
  supporting: "Supporting",
  contradicting: "Contradicting",
  contextual: "Contextual",
  unresolved: "Unresolved",
};

// Amber (attention), never red (reserved for genuine failure/destructive
// actions) — contradicting evidence is a normal analytical classification,
// not a fault. See CLAUDE.md §20's aesthetics doctrine.
const CLASSIFICATION_TONE: Record<ResearchEvidenceClassification, string> = {
  supporting: "tone-ok",
  contradicting: "tone-warn",
  contextual: "tone-active",
  unresolved: "tone-neutral",
};

const DEBOUNCE_MS = 300;
const PAGE_SIZE = 15;

function evidenceKey(sourceType: string, sourceId: string): string {
  return `${sourceType}:${sourceId}`;
}

function formatDate(iso: string | null): string {
  return formatDateTime(iso);
}


function ResearchCentre({ onBack, onNavigate }: ResearchCentreProps) {
  const [workspaces, setWorkspaces] = useState<ResearchWorkspace[] | null>(null);
  const [listStatus, setListStatus] = useState<"active" | "archived">("active");
  const [listError, setListError] = useState<string | null>(null);
  const [selectedId, setSelectedId] = useState<string | null>(null);

  const [createTitle, setCreateTitle] = useState("");
  const [createDomains, setCreateDomains] = useState<ResearchDomainSlug[]>(DEFAULT_DOMAINS);
  const [createBusy, setCreateBusy] = useState(false);
  const [createError, setCreateError] = useState<string | null>(null);

  const loadWorkspaces = useMemo(
    () => (status: "active" | "archived") => {
      setWorkspaces(null);
      setListError(null);
      fetchResearchWorkspaces(status)
        .then(setWorkspaces)
        .catch(() => {
          setListError("Could not load research workspaces. The backend may be unreachable.");
          setWorkspaces([]);
        });
    },
    [],
  );

  useEffect(() => {
    if (selectedId === null) loadWorkspaces(listStatus);
  }, [listStatus, selectedId, loadWorkspaces]);

  function toggleCreateDomain(slug: ResearchDomainSlug) {
    setCreateDomains((prev) => (prev.includes(slug) ? prev.filter((d) => d !== slug) : [...prev, slug]));
  }

  async function handleCreate(e: React.FormEvent) {
    e.preventDefault();
    if (!createTitle.trim()) return;
    setCreateBusy(true);
    setCreateError(null);
    try {
      const workspace = await createResearchWorkspace({ title: createTitle.trim(), included_domain_slugs: createDomains });
      setCreateTitle("");
      setCreateDomains(DEFAULT_DOMAINS);
      setSelectedId(workspace.id);
    } catch {
      setCreateError("Could not create the workspace.");
    } finally {
      setCreateBusy(false);
    }
  }

  if (selectedId !== null) {
    return (
      <ResearchWorkspaceDetail
        workspaceId={selectedId}
        onBackToList={() => {
          setSelectedId(null);
        }}
        onNavigate={onNavigate}
      />
    );
  }

  return (
    <div className="domain-view">
      <button type="button" className="back-button" onClick={onBack}>
        ← Back to Jarvis
      </button>

      <ConsoleHeader
        indicator={<MiniCoreIndicator />}
        eyebrow="Centre"
        title="Research"
        description="Source-grounded research workspaces over everything Jarvis has stored — evidence collected through Recall, classified, and assembled into a cited brief. Never unrestricted web research, never an autonomous agent."
        meta={workspaces && workspaces.length > 0 ? <span>{workspaces.length} workspace{workspaces.length === 1 ? "" : "s"}</span> : undefined}
      />

      <ConsoleModule title="New workspace" ariaLabel="Create a research workspace">
        <form className="message-form-actions" onSubmit={handleCreate}>
          <input
            type="text"
            placeholder="Research question or topic…"
            value={createTitle}
            onChange={(e) => setCreateTitle(e.target.value)}
            aria-label="Research question or topic"
          />
          <button type="submit" disabled={createBusy || !createTitle.trim()}>
            {createBusy ? "Creating…" : "Create workspace"}
          </button>
        </form>
        <fieldset className="mc-domain-picker">
          <legend className="sr-only">Domains this workspace may draw evidence from</legend>
          <span role="group" aria-label="Included domains">
            {DOMAIN_SLUG_ORDER.map((slug) => (
              <button
                key={slug}
                type="button"
                role="checkbox"
                aria-checked={createDomains.includes(slug)}
                className={`briefing-item-control${createDomains.includes(slug) ? " mc-duration-selected" : ""}`}
                onClick={() => toggleCreateDomain(slug)}
              >
                <DomainGlyph slug={slug} />
                {slug.toUpperCase()}
              </button>
            ))}
          </span>
        </fieldset>
        {createError && (
          <p className="error-banner" role="alert">
            {createError}
          </p>
        )}
      </ConsoleModule>

      <ConsoleModule title="Workspaces" ariaLabel="Research workspaces">
        <div className="tab-row">
          {(["active", "archived"] as const).map((s) => (
            <label key={s}>
              <input type="radio" name="workspace-status-filter" checked={listStatus === s} onChange={() => setListStatus(s)} />
              {s}
            </label>
          ))}
        </div>

        {listError && (
          <p className="error-banner" role="alert">
            {listError}
          </p>
        )}
        {workspaces === null && !listError && <p className="ledger-empty">Loading workspaces…</p>}
        {workspaces !== null && workspaces.length === 0 && !listError && (
          <p className="ledger-empty">
            {listStatus === "active" ? "No active research workspaces yet." : "No archived research workspaces."}
          </p>
        )}
        {workspaces !== null && workspaces.length > 0 && (
          <div className="ledger">
            {workspaces.map((ws) => (
              <button
                key={ws.id}
                type="button"
                className="ledger-row"
                style={{ width: "100%", textAlign: "left", cursor: "pointer" }}
                onClick={() => setSelectedId(ws.id)}
              >
                <span className="ledger-row-main">{ws.title}</span>
                <span className="ledger-row-meta">
                  {ws.evidence_count} evidence · {ws.note_count} note{ws.note_count === 1 ? "" : "s"}
                  {ws.latest_brief_version ? ` · v${ws.latest_brief_version} brief` : ""}
                </span>
              </button>
            ))}
          </div>
        )}
      </ConsoleModule>
    </div>
  );
}

// ---------------------------------------------------------------------------

interface ResearchWorkspaceDetailProps {
  workspaceId: string;
  onBackToList: () => void;
  onNavigate: (target: NavigateTarget) => void;
}

type DetailTab = "evidence" | "notes" | "briefs";

function ResearchWorkspaceDetail({ workspaceId, onBackToList, onNavigate }: ResearchWorkspaceDetailProps) {
  const [workspace, setWorkspace] = useState<ResearchWorkspace | null>(null);
  const [workspaceError, setWorkspaceError] = useState<string | null>(null);
  const [tab, setTab] = useState<DetailTab>("evidence");
  const [busy, setBusy] = useState(false);

  const [evidence, setEvidence] = useState<ResearchEvidence[] | null>(null);
  const [notes, setNotes] = useState<ResearchNote[] | null>(null);

  const refreshWorkspace = () =>
    fetchResearchWorkspace(workspaceId)
      .then((w) => {
        setWorkspace(w);
        setWorkspaceError(null);
      })
      .catch(() => setWorkspaceError("Could not load this workspace. It may have been removed."));

  const refreshEvidence = () =>
    listResearchEvidence(workspaceId)
      .then(setEvidence)
      .catch(() => setEvidence([]));

  const refreshNotes = () =>
    listResearchNotes(workspaceId)
      .then(setNotes)
      .catch(() => setNotes([]));

  useEffect(() => {
    setWorkspace(null);
    setEvidence(null);
    setNotes(null);
    refreshWorkspace();
    refreshEvidence();
    refreshNotes();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [workspaceId]);

  async function handleArchiveToggle() {
    if (!workspace) return;
    setBusy(true);
    try {
      const updated = workspace.status === "active" ? await archiveResearchWorkspace(workspace.id) : await reopenResearchWorkspace(workspace.id);
      setWorkspace(updated);
    } catch {
      setWorkspaceError("Could not update this workspace's status.");
    } finally {
      setBusy(false);
    }
  }

  async function toggleWorkspaceDomain(slug: ResearchDomainSlug) {
    if (!workspace) return;
    const next = workspace.included_domain_slugs.includes(slug)
      ? workspace.included_domain_slugs.filter((d) => d !== slug)
      : [...workspace.included_domain_slugs, slug];
    try {
      const updated = await updateResearchWorkspace(workspace.id, { included_domain_slugs: next });
      setWorkspace(updated);
    } catch {
      setWorkspaceError("Could not update this workspace's domain policy.");
    }
  }

  if (workspaceError && !workspace) {
    return (
      <div className="domain-view">
        <button type="button" className="back-button" onClick={onBackToList}>
          ← All workspaces
        </button>
        <p className="error-banner" role="alert">
          {workspaceError}
        </p>
      </div>
    );
  }

  const isArchived = workspace?.status === "archived";

  return (
    <div className="domain-view">
      <button type="button" className="back-button" onClick={onBackToList}>
        ← All workspaces
      </button>

      <ConsoleHeader
        indicator={<MiniCoreIndicator />}
        eyebrow="Research workspace"
        title={workspace?.title ?? "Loading…"}
        meta={
          workspace ? (
            <span>
              {workspace.evidence_count} evidence · {workspace.note_count} notes · {workspace.status}
            </span>
          ) : undefined
        }
        actions={
          workspace && (
            <button type="button" onClick={handleArchiveToggle} disabled={busy}>
              {workspace.status === "active" ? "Archive workspace" : "Reopen workspace"}
            </button>
          )
        }
      />

      {isArchived && (
        <p className="notice" role="status">
          This workspace is archived — evidence, notes, and past briefs remain visible, but adding new evidence or generating a
          new brief requires reopening it first.
        </p>
      )}

      {workspace && (
        <ConsoleModule title="Domain policy" ariaLabel="Included domains">
          <fieldset className="mc-domain-picker">
            <legend className="sr-only">Domains evidence may be added from</legend>
            <span role="group" aria-label="Included domains">
              {DOMAIN_SLUG_ORDER.map((slug) => (
                <button
                  key={slug}
                  type="button"
                  role="checkbox"
                  aria-checked={workspace.included_domain_slugs.includes(slug)}
                  className={`briefing-item-control${workspace.included_domain_slugs.includes(slug) ? " mc-duration-selected" : ""}`}
                  onClick={() => toggleWorkspaceDomain(slug)}
                  disabled={isArchived}
                >
                  <DomainGlyph slug={slug} />
                  {slug.toUpperCase()}
                  {SENSITIVE_SLUGS.has(slug) && <span className="sr-only"> (sensitive)</span>}
                </button>
              ))}
            </span>
          </fieldset>
        </ConsoleModule>
      )}

      <section aria-label="Workspace section">
        <div className="tab-row">
          {(["evidence", "notes", "briefs"] as const).map((t) => (
            <label key={t}>
              <input type="radio" name="research-tab" checked={tab === t} onChange={() => setTab(t)} />
              {t}
              {t === "evidence" && evidence !== null ? <span className="tab-count">{evidence.length}</span> : null}
              {t === "notes" && notes !== null ? <span className="tab-count">{notes.length}</span> : null}
            </label>
          ))}
        </div>
      </section>

      {workspace && tab === "evidence" && (
        <EvidenceTab
          workspace={workspace}
          evidence={evidence}
          onEvidenceChanged={refreshEvidence}
          onWorkspaceChanged={refreshWorkspace}
          onNavigate={onNavigate}
        />
      )}
      {workspace && tab === "notes" && (
        <NotesTab workspace={workspace} notes={notes} evidence={evidence} onNotesChanged={refreshNotes} />
      )}
      {workspace && tab === "briefs" && (
        <BriefsTab workspace={workspace} onWorkspaceChanged={refreshWorkspace} onNavigate={onNavigate} />
      )}
    </div>
  );
}

// ---------------------------------------------------------------------------

interface EvidenceTabProps {
  workspace: ResearchWorkspace;
  evidence: ResearchEvidence[] | null;
  onEvidenceChanged: () => void;
  onWorkspaceChanged: () => void;
  onNavigate: (target: NavigateTarget) => void;
}

function EvidenceTab({ workspace, evidence, onEvidenceChanged, onNavigate }: EvidenceTabProps) {
  const [query, setQuery] = useState("");
  const [results, setResults] = useState<RecallResult[] | null>(null);
  const [partialFailures, setPartialFailures] = useState<string[]>([]);
  const [searchLoading, setSearchLoading] = useState(false);
  const [searchError, setSearchError] = useState<string | null>(null);
  const [addingKey, setAddingKey] = useState<string | null>(null);
  const abortRef = useRef<AbortController | null>(null);
  const isArchived = workspace.status === "archived";

  useEffect(() => {
    if (!query.trim()) {
      setResults(null);
      setSearchError(null);
      setPartialFailures([]);
      return;
    }
    let cancelled = false;
    const timeoutId = window.setTimeout(() => {
      abortRef.current?.abort();
      const controller = new AbortController();
      abortRef.current = controller;
      setSearchLoading(true);
      setSearchError(null);
      searchResearchEvidence(workspace.id, { q: query.trim(), limit: PAGE_SIZE }, controller.signal)
        .then((data) => {
          if (cancelled) return;
          setResults(data.results);
          setPartialFailures(data.partial_failures);
        })
        .catch((err: unknown) => {
          if (cancelled) return;
          if (err instanceof DOMException && err.name === "AbortError") return;
          setSearchError("Search failed. The backend may be unreachable.");
          setResults(null);
        })
        .finally(() => {
          if (!cancelled) setSearchLoading(false);
        });
    }, DEBOUNCE_MS);
    return () => {
      cancelled = true;
      window.clearTimeout(timeoutId);
    };
  }, [query, workspace.id]);

  const addedKeys = useMemo(
    () => new Set((evidence ?? []).map((e) => evidenceKey(e.source_type, e.source_id))),
    [evidence],
  );

  async function handleAdd(result: RecallResult) {
    const key = evidenceKey(result.source_type, result.source_id);
    setAddingKey(key);
    try {
      await addResearchEvidence(workspace.id, { source_type: result.source_type as RecallSourceType, source_id: result.source_id });
      onEvidenceChanged();
    } catch {
      setSearchError("Could not add that item as evidence.");
    } finally {
      setAddingKey(null);
    }
  }

  async function handleClassify(item: ResearchEvidence, classification: ResearchEvidenceClassification) {
    try {
      await updateResearchEvidence(workspace.id, item.id, { classification });
      onEvidenceChanged();
    } catch {
      /* the row simply keeps its previous classification on failure */
    }
  }

  async function handleRemove(item: ResearchEvidence) {
    try {
      await removeResearchEvidence(workspace.id, item.id);
      onEvidenceChanged();
    } catch {
      /* no-op — row stays as-is, user can retry */
    }
  }

  return (
    <>
      <ConsoleModule title="Find evidence" ariaLabel="Search for evidence to add">
        {isArchived && <p className="notice">Reopen this workspace to add new evidence.</p>}
        <form className="message-form-actions" onSubmit={(e) => e.preventDefault()}>
          <input
            type="text"
            placeholder="Search Jarvis for evidence…"
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            aria-label="Search for evidence"
            disabled={isArchived}
          />
        </form>
        {searchError && (
          <p className="error-banner" role="alert">
            {searchError}
          </p>
        )}
        {partialFailures.length > 0 && (
          <p className="notice" role="status">
            Some sources did not respond this search: {partialFailures.join(", ")}.
          </p>
        )}
        {searchLoading && <p className="ledger-empty">Searching…</p>}
        {!searchLoading && query.trim() && results !== null && results.length === 0 && (
          <p className="ledger-empty">No results in this workspace's included domains.</p>
        )}
        {results !== null && results.length > 0 && (
          <ul className="briefing-strip-list">
            {results.map((result) => {
              const key = evidenceKey(result.source_type, result.source_id);
              const already = addedKeys.has(key);
              return (
                <li key={key} className="briefing-item-row">
                  <div className="briefing-item tone-neutral">
                    {result.domain_slug && (
                      <span className="mc-candidate-glyph" aria-hidden="true">
                        <DomainGlyph slug={result.domain_slug} />
                      </span>
                    )}
                    <span className="briefing-item-body">
                      <span className="briefing-item-title">{result.title}</span>
                      <span className="briefing-item-subtitle" dangerouslySetInnerHTML={{ __html: result.snippet_html }} />
                    </span>
                    <button
                      type="button"
                      className="briefing-strip-button"
                      onClick={() => handleAdd(result)}
                      disabled={already || isArchived || addingKey === key}
                    >
                      {already ? "Added" : addingKey === key ? "Adding…" : "Add as evidence"}
                    </button>
                  </div>
                </li>
              );
            })}
          </ul>
        )}
      </ConsoleModule>

      <ConsoleModule title="Evidence" ariaLabel="Collected evidence">
        {evidence === null && <p className="ledger-empty">Loading evidence…</p>}
        {evidence !== null && evidence.length === 0 && (
          <p className="ledger-empty">No evidence added yet — search above to find some.</p>
        )}
        {evidence !== null && evidence.length > 0 && (
          <div className="ledger">
            {evidence.map((item) => (
              <div key={item.id} className="ledger-row" style={{ flexDirection: "column", alignItems: "stretch" }}>
                <div style={{ display: "flex", justifyContent: "space-between", gap: "0.5rem", flexWrap: "wrap" }}>
                  <span className="ledger-row-main">{item.title_snapshot}</span>
                  <span className={`status-chip ${CLASSIFICATION_TONE[item.classification]}`}>
                    {CLASSIFICATION_LABEL[item.classification]}
                  </span>
                </div>
                <p className="message-content" style={{ margin: "0.3rem 0" }}>
                  {item.snippet_snapshot}
                </p>
                <span className="ledger-row-meta">
                  {item.domain_slug ? item.domain_slug.toUpperCase() : "Global"}
                  {item.occurred_at_snapshot ? ` · ${formatDate(item.occurred_at_snapshot)}` : ""}
                  {!item.available && ` · ${item.unavailable_reason ?? "Source unavailable"}`}
                </span>
                <div className="ledger-row-actions" style={{ flexWrap: "wrap" }}>
                  <label>
                    <span className="sr-only">Classification for {item.title_snapshot}</span>
                    <select
                      value={item.classification}
                      onChange={(e) => handleClassify(item, e.target.value as ResearchEvidenceClassification)}
                      aria-label={`Classification for ${item.title_snapshot}`}
                    >
                      {CLASSIFICATION_ORDER.map((c) => (
                        <option key={c} value={c}>
                          {CLASSIFICATION_LABEL[c]}
                        </option>
                      ))}
                    </select>
                  </label>
                  {item.available && isNavigateTarget(item.link_target) && (
                    <button type="button" onClick={() => onNavigate(item.link_target as NavigateTarget)}>
                      Open source
                    </button>
                  )}
                  <button type="button" onClick={() => handleRemove(item)}>
                    Remove
                  </button>
                </div>
              </div>
            ))}
          </div>
        )}
      </ConsoleModule>
    </>
  );
}

// ---------------------------------------------------------------------------

interface NotesTabProps {
  workspace: ResearchWorkspace;
  notes: ResearchNote[] | null;
  evidence: ResearchEvidence[] | null;
  onNotesChanged: () => void;
}

function NotesTab({ workspace, notes, evidence, onNotesChanged }: NotesTabProps) {
  const [content, setContent] = useState("");
  const [linked, setLinked] = useState<string[]>([]);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const isArchived = workspace.status === "archived";

  function toggleLinked(id: string) {
    setLinked((prev) => (prev.includes(id) ? prev.filter((x) => x !== id) : [...prev, id]));
  }

  async function handleAdd(e: React.FormEvent) {
    e.preventDefault();
    if (!content.trim()) return;
    setBusy(true);
    setError(null);
    try {
      await addResearchNote(workspace.id, { content: content.trim(), linked_evidence_ids: linked });
      setContent("");
      setLinked([]);
      onNotesChanged();
    } catch {
      setError("Could not add this note.");
    } finally {
      setBusy(false);
    }
  }

  async function handleArchive(note: ResearchNote) {
    try {
      await archiveResearchNote(workspace.id, note.id);
      onNotesChanged();
    } catch {
      /* row stays as-is; user can retry */
    }
  }

  return (
    <>
      <ConsoleModule title="Add a note" ariaLabel="Add a note or provisional claim">
        {isArchived && <p className="notice">Reopen this workspace to add new notes.</p>}
        <form onSubmit={handleAdd}>
          <textarea
            value={content}
            onChange={(e) => setContent(e.target.value)}
            placeholder="Your own note or provisional claim — never generated by Jarvis…"
            aria-label="Note content"
            rows={3}
            disabled={isArchived}
          />
          {evidence && evidence.length > 0 && (
            <fieldset>
              <legend>Link to evidence (optional)</legend>
              {evidence.map((item) => (
                <label key={item.id} style={{ display: "block" }}>
                  <input
                    type="checkbox"
                    checked={linked.includes(item.id)}
                    onChange={() => toggleLinked(item.id)}
                    disabled={isArchived}
                  />
                  {item.title_snapshot}
                </label>
              ))}
            </fieldset>
          )}
          <button type="submit" disabled={busy || !content.trim() || isArchived}>
            {busy ? "Saving…" : "Add note"}
          </button>
        </form>
        {error && (
          <p className="error-banner" role="alert">
            {error}
          </p>
        )}
      </ConsoleModule>

      <ConsoleModule title="Notes" ariaLabel="Notes and provisional claims">
        {notes === null && <p className="ledger-empty">Loading notes…</p>}
        {notes !== null && notes.length === 0 && <p className="ledger-empty">No notes yet.</p>}
        {notes !== null && notes.length > 0 && (
          <div className="ledger">
            {notes.map((note) => (
              <div key={note.id} className="ledger-row" style={{ flexDirection: "column", alignItems: "stretch" }}>
                <span className="ledger-row-main message-content">{note.content}</span>
                {note.linked_evidence_ids.length > 0 && (
                  <span className="ledger-row-meta">Linked to {note.linked_evidence_ids.length} evidence item(s)</span>
                )}
                <div className="ledger-row-actions">
                  <button type="button" onClick={() => handleArchive(note)}>
                    Archive
                  </button>
                </div>
              </div>
            ))}
          </div>
        )}
      </ConsoleModule>
    </>
  );
}

// ---------------------------------------------------------------------------

interface BriefsTabProps {
  workspace: ResearchWorkspace;
  onWorkspaceChanged: () => void;
  onNavigate: (target: NavigateTarget) => void;
}

function BriefsTab({ workspace, onWorkspaceChanged, onNavigate }: BriefsTabProps) {
  const [versions, setVersions] = useState<ResearchBriefVersionSummary[] | null>(null);
  const [selected, setSelected] = useState<ResearchBriefVersion | null>(null);
  const [selectedError, setSelectedError] = useState<string | null>(null);
  const [generating, setGenerating] = useState(false);
  const [drafting, setDrafting] = useState(false);
  const [actionError, setActionError] = useState<string | null>(null);
  const isArchived = workspace.status === "archived";
  const noEvidence = workspace.evidence_count === 0;

  const refreshVersions = () =>
    listResearchBriefs(workspace.id)
      .then(setVersions)
      .catch(() => setVersions([]));

  useEffect(() => {
    setVersions(null);
    setSelected(null);
    refreshVersions();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [workspace.id]);

  async function openVersion(id: string) {
    setSelectedError(null);
    try {
      const version = await getResearchBrief(workspace.id, id);
      setSelected(version);
    } catch {
      setSelectedError("Could not load this brief version.");
    }
  }

  async function handleGenerateDeterministic() {
    setGenerating(true);
    setActionError(null);
    try {
      const version = await generateDeterministicBrief(workspace.id);
      await refreshVersions();
      onWorkspaceChanged();
      setSelected(version);
    } catch (err) {
      setActionError(err instanceof ApiError ? err.message : "Could not generate the evidence outline.");
    } finally {
      setGenerating(false);
    }
  }

  async function handleDraftWithJarvis() {
    setDrafting(true);
    setActionError(null);
    try {
      const version = await draftBriefWithJarvis(workspace.id);
      await refreshVersions();
      onWorkspaceChanged();
      setSelected(version);
    } catch (err) {
      if (err instanceof ApiError && err.status === 502) {
        setActionError("Jarvis model is currently unavailable — the deterministic outline above still works without it.");
      } else if (err instanceof ApiError) {
        setActionError(err.message);
      } else {
        setActionError("Could not reach Jarvis to draft this brief.");
      }
    } finally {
      setDrafting(false);
    }
  }

  return (
    <>
      <ConsoleModule title="Generate a brief" ariaLabel="Generate a research brief">
        {isArchived && <p className="notice">Reopen this workspace to generate a new brief version.</p>}
        {noEvidence && !isArchived && <p className="notice">Add at least one piece of evidence first.</p>}
        <div className="mission-focus-add-actions">
          <button type="button" onClick={handleGenerateDeterministic} disabled={generating || isArchived || noEvidence}>
            {generating ? "Generating…" : "Generate evidence outline"}
          </button>
          <button type="button" onClick={handleDraftWithJarvis} disabled={drafting || isArchived || noEvidence}>
            {drafting ? "Drafting…" : "Draft with Jarvis"}
          </button>
        </div>
        {actionError && (
          <p className="error-banner" role="alert">
            {actionError}
          </p>
        )}
      </ConsoleModule>

      <ConsoleModule title="Brief versions" ariaLabel="Brief version history">
        {versions === null && <p className="ledger-empty">Loading briefs…</p>}
        {versions !== null && versions.length === 0 && <p className="ledger-empty">No briefs generated yet.</p>}
        {versions !== null && versions.length > 0 && (
          <div className="ledger">
            {versions.map((v) => (
              <button
                key={v.id}
                type="button"
                className="ledger-row"
                style={{ width: "100%", textAlign: "left", cursor: "pointer" }}
                onClick={() => openVersion(v.id)}
              >
                <span className="ledger-row-main">
                  v{v.version_number} — {v.source === "model" ? "Jarvis model-generated draft" : "Evidence outline"}
                </span>
                <span className="ledger-row-meta">
                  {formatDate(v.generated_at)}
                  {v.status === "invalid_citations" ? " · has a flagged citation" : ""}
                </span>
              </button>
            ))}
          </div>
        )}
      </ConsoleModule>

      {selectedError && (
        <p className="error-banner" role="alert">
          {selectedError}
        </p>
      )}

      {selected && <BriefDetail version={selected} onNavigate={onNavigate} />}
    </>
  );
}

// ---------------------------------------------------------------------------

function BriefDetail({ version, onNavigate }: { version: ResearchBriefVersion; onNavigate: (t: NavigateTarget) => void }) {
  const citationByNumber = useMemo(() => {
    const map = new Map<number, (typeof version.citations)[number]>();
    for (const c of version.citations) map.set(c.number, c);
    return map;
  }, [version.citations]);

  let sections: Array<Record<string, unknown>> = [];
  try {
    sections = JSON.parse(version.sections_json);
  } catch {
    sections = [];
  }

  return (
    <ConsoleModule
      title={version.source === "model" ? "Jarvis model-generated draft" : "Evidence outline"}
      ariaLabel="Brief detail"
    >
      {version.source === "model" && (
        <p className="notice" role="status">
          Jarvis model-generated draft — synthesized only from this workspace's selected evidence. Verify every citation.
        </p>
      )}
      {version.status === "invalid_citations" && version.validation_issues.length > 0 && (
        <p className="error-banner" role="alert">
          {version.validation_issues.join(" ")}
        </p>
      )}

      {sections.map((section, idx) => {
        const kind = section.kind as string;
        if (kind === "model_text") {
          const text = String(section.text ?? "");
          return (
            <p key={idx} className="message-content">
              {splitOnCitations(text).map((run, runIdx) => {
                if (run.citationNumber === null) return <span key={runIdx}>{run.text}</span>;
                const citation = citationByNumber.get(run.citationNumber);
                return (
                  <span
                    key={runIdx}
                    className={citation ? "status-chip tone-active" : "status-chip tone-warn"}
                    title={citation ? citation.title_snapshot : "This citation does not match any evidence in this workspace"}
                  >
                    {run.text}
                  </span>
                );
              })}
            </p>
          );
        }
        if (kind === "evidence_group") {
          const items = (section.items as Array<Record<string, unknown>>) ?? [];
          return (
            <div key={idx}>
              <h3 className="console-section-label">{String(section.heading)}</h3>
              <ul>
                {items.map((item, itemIdx) => (
                  <li key={itemIdx} className="message-content">
                    [{String(item.citation_number)}] {String(item.title)} — {String(item.excerpt)}
                  </li>
                ))}
              </ul>
            </div>
          );
        }
        if (kind === "notes") {
          const items = (section.items as Array<Record<string, unknown>>) ?? [];
          return (
            <div key={idx}>
              <h3 className="console-section-label">{String(section.heading)}</h3>
              <ul>
                {items.map((item, itemIdx) => (
                  <li key={itemIdx} className="message-content">
                    {String(item.content)}
                  </li>
                ))}
              </ul>
            </div>
          );
        }
        return null;
      })}

      <h3 className="console-section-label">Citations</h3>
      {version.citations.length === 0 && <p className="ledger-empty">No citations in this version.</p>}
      {version.citations.length > 0 && (
        <div className="ledger">
          {version.citations.map((c) => (
            <div key={c.number} className="ledger-row">
              <span className="ledger-row-main">
                [{c.number}] {c.title_snapshot}
              </span>
              <span className="ledger-row-meta">
                {c.domain_slug ? c.domain_slug.toUpperCase() : "Global"}
                {!c.available && ` · ${c.unavailable_reason ?? "Source unavailable"}`}
              </span>
              <div className="ledger-row-actions">
                {c.available && isNavigateTarget(c.link_target) && (
                  <button type="button" onClick={() => onNavigate(c.link_target as NavigateTarget)}>
                    Open source
                  </button>
                )}
              </div>
            </div>
          ))}
        </div>
      )}
    </ConsoleModule>
  );
}

export default ResearchCentre;
