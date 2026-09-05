import { useEffect, useMemo, useRef, useState } from "react";
import {
  ApiError,
  abandonDecision,
  addDecisionEvidence,
  addDecisionFactor,
  addDecisionOption,
  addDecisionOutcomeReview,
  addDecisionCriterion,
  createDecision,
  decideDecision,
  draftDecisionCritique,
  fetchDecision,
  fetchDecisionCalibrationSummary,
  fetchDecisions,
  fetchDecisionScoreBreakdown,
  fetchResearchWorkspaces,
  generateDecisionDeterministicBrief,
  getDecisionBrief,
  linkDecisionResearchWorkspace,
  listDecisionBriefs,
  listDecisionAssessments,
  listDecisionCriteria,
  listDecisionEvidence,
  listDecisionFactors,
  listDecisionFinalVersions,
  listDecisionOptions,
  listDecisionOutcomeReviews,
  reopenDecision,
  removeDecisionCriterion,
  resolveDecisionFactor,
  searchDecisionEvidence,
  setDecisionAssessment,
  startEvaluatingDecision,
  supersedeDecision,
  updateDecision,
  updateDecisionOption,
  type Decision,
  type DecisionAssessment,
  type DecisionBriefVersion,
  type DecisionBriefVersionSummary,
  type DecisionCalibrationSummary,
  type DecisionCriterion,
  type DecisionEvidence,
  type DecisionEvidenceStance,
  type DecisionFactor,
  type DecisionFactorKind,
  type DecisionFinalVersion,
  type DecisionOption,
  type DecisionOutcomeReview,
  type DecisionReversibility,
  type DecisionScoreBreakdown,
  type DecisionSourceType,
  type RecallResult,
  type ResearchDomainSlug,
  type ResearchWorkspace,
} from "../api";
import { isNavigateTarget, type NavigateTarget } from "../commands/registry";
import { splitOnCitations } from "../citationText";
import { DOMAIN_SLUG_ORDER } from "../domainOrder";
import DomainGlyph from "../components/DomainGlyph";
import { ConsoleHeader, ConsoleModule, MiniCoreIndicator } from "../components/console/Console";
import { formatDateTime } from "../formatDateTime";

interface DecisionCentreProps {
  onBack: () => void;
  onNavigate: (target: NavigateTarget) => void;
}

const DEFAULT_DOMAINS: ResearchDomainSlug[] = ["life", "path", "build"];
const PAGE_SIZE = 15;
const DEBOUNCE_MS = 300;

const STATUS_LABEL: Record<Decision["status"], string> = {
  draft: "Draft", evaluating: "Evaluating", decided: "Decided", reopened: "Reopened",
  superseded: "Superseded", abandoned: "Abandoned",
};
const STATUS_TONE: Record<Decision["status"], string> = {
  draft: "tone-neutral", evaluating: "tone-active", decided: "tone-ok",
  reopened: "tone-warn", superseded: "tone-neutral", abandoned: "tone-neutral",
};
const STANCE_LABEL: Record<DecisionEvidenceStance, string> = {
  supporting: "Supporting", contradicting: "Contradicting", contextual: "Contextual", unresolved: "Unresolved",
};
const STANCE_TONE: Record<DecisionEvidenceStance, string> = {
  supporting: "tone-ok", contradicting: "tone-warn", contextual: "tone-active", unresolved: "tone-neutral",
};
const FACTOR_KIND_LABEL: Record<DecisionFactorKind, string> = {
  assumption: "Assumption", risk: "Risk", unknown: "Unknown",
};

function formatDate(iso: string | null): string {
  return formatDateTime(iso);
}

function evidenceKey(sourceType: string, sourceId: string): string {
  return `${sourceType}:${sourceId}`;
}

function DecisionCentre({ onBack, onNavigate }: DecisionCentreProps) {
  const [decisions, setDecisions] = useState<Decision[] | null>(null);
  const [listStatus, setListStatus] = useState<Decision["status"] | "all">("all");
  const [listError, setListError] = useState<string | null>(null);
  const [selectedId, setSelectedId] = useState<string | null>(null);

  const [createTitle, setCreateTitle] = useState("");
  const [createDomains, setCreateDomains] = useState<ResearchDomainSlug[]>(DEFAULT_DOMAINS);
  const [createBusy, setCreateBusy] = useState(false);
  const [createError, setCreateError] = useState<string | null>(null);
  const [calibration, setCalibration] = useState<DecisionCalibrationSummary | null>(null);

  useEffect(() => {
    if (selectedId !== null) return;
    setDecisions(null);
    setListError(null);
    fetchDecisions(listStatus === "all" ? undefined : listStatus)
      .then(setDecisions)
      .catch(() => {
        setListError("Could not load decisions. The backend may be unreachable.");
        setDecisions([]);
      });
    fetchDecisionCalibrationSummary().then(setCalibration).catch(() => setCalibration(null));
  }, [listStatus, selectedId]);

  function toggleCreateDomain(slug: ResearchDomainSlug) {
    setCreateDomains((prev) => (prev.includes(slug) ? prev.filter((d) => d !== slug) : [...prev, slug]));
  }

  async function handleCreate(e: React.FormEvent) {
    e.preventDefault();
    if (!createTitle.trim()) return;
    setCreateBusy(true);
    setCreateError(null);
    try {
      const decision = await createDecision({ title: createTitle.trim(), included_domain_slugs: createDomains });
      setCreateTitle("");
      setCreateDomains(DEFAULT_DOMAINS);
      setSelectedId(decision.id);
    } catch {
      setCreateError("Could not create the decision.");
    } finally {
      setCreateBusy(false);
    }
  }

  if (selectedId !== null) {
    return <DecisionDetail decisionId={selectedId} onBackToList={() => setSelectedId(null)} onNavigate={onNavigate} />;
  }

  return (
    <div className="domain-view">
      <button type="button" className="back-button" onClick={onBack}>
        ← Back to Jarvis
      </button>

      <ConsoleHeader
        indicator={<MiniCoreIndicator />}
        eyebrow="Centre"
        title="Decision Room"
        description="Evidence-grounded decisions over everything Jarvis has stored — options and criteria compared transparently, evidence linked from Recall and Research, and a deterministic score you can inspect. Jarvis can critique; only you can decide."
        meta={decisions && decisions.length > 0 ? <span>{decisions.length} decision{decisions.length === 1 ? "" : "s"}</span> : undefined}
      />

      {calibration && calibration.has_enough_data && (
        <ConsoleModule title="Calibration" ariaLabel="Decision calibration summary">
          <p className="notice" role="status">
            Across {calibration.reviewed_count} reviewed decision{calibration.reviewed_count === 1 ? "" : "s"}:{" "}
            {calibration.confidence_appropriate_rate !== null && (
              <>confidence was appropriate {Math.round(calibration.confidence_appropriate_rate * 100)}% of the time. </>
            )}
            {calibration.would_decide_same_rate !== null && (
              <>You'd decide the same again {Math.round(calibration.would_decide_same_rate * 100)}% of the time.</>
            )}
          </p>
        </ConsoleModule>
      )}
      {calibration && !calibration.has_enough_data && (
        <p className="ledger-empty">Calibration summary appears once {calibration.minimum_sample} decisions have been reviewed.</p>
      )}

      <ConsoleModule title="New decision" ariaLabel="Define a decision">
        <form className="message-form-actions" onSubmit={handleCreate}>
          <input
            type="text"
            placeholder="What are you deciding?"
            value={createTitle}
            onChange={(e) => setCreateTitle(e.target.value)}
            aria-label="Decision question"
          />
          <button type="submit" disabled={createBusy || !createTitle.trim()}>
            {createBusy ? "Creating…" : "Create decision"}
          </button>
        </form>
        <fieldset className="mc-domain-picker">
          <legend className="sr-only">Domains this decision may draw evidence from</legend>
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

      <ConsoleModule title="Decisions" ariaLabel="Decision ledger">
        <div className="tab-row">
          {(["all", "draft", "evaluating", "decided", "reopened", "superseded", "abandoned"] as const).map((s) => (
            <label key={s}>
              <input type="radio" name="decision-status-filter" checked={listStatus === s} onChange={() => setListStatus(s)} />
              {s}
            </label>
          ))}
        </div>

        {listError && (
          <p className="error-banner" role="alert">
            {listError}
          </p>
        )}
        {decisions === null && !listError && <p className="ledger-empty">Loading decisions…</p>}
        {decisions !== null && decisions.length === 0 && !listError && (
          <p className="ledger-empty">{listStatus === "all" ? "No decisions yet." : `No ${listStatus} decisions.`}</p>
        )}
        {decisions !== null && decisions.length > 0 && (
          <div className="ledger">
            {decisions.map((d) => (
              <button
                key={d.id}
                type="button"
                className="ledger-row"
                style={{ width: "100%", textAlign: "left", cursor: "pointer" }}
                onClick={() => setSelectedId(d.id)}
              >
                <span className="ledger-row-main">{d.title}</span>
                <span className={`status-chip ${STATUS_TONE[d.status]}`}>{STATUS_LABEL[d.status]}</span>
                <span className="ledger-row-meta">
                  {d.option_count} option{d.option_count === 1 ? "" : "s"} · {d.evidence_count} evidence
                  {d.review_due ? " · Review due" : ""}
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

interface DecisionDetailProps {
  decisionId: string;
  onBackToList: () => void;
  onNavigate: (target: NavigateTarget) => void;
}

type DetailTab = "overview" | "options" | "criteria" | "evidence" | "factors" | "briefs" | "outcome";

function DecisionDetail({ decisionId, onBackToList, onNavigate }: DecisionDetailProps) {
  const [decision, setDecision] = useState<Decision | null>(null);
  const [decisionError, setDecisionError] = useState<string | null>(null);
  const [tab, setTab] = useState<DetailTab>("overview");
  const [busy, setBusy] = useState(false);
  const [actionError, setActionError] = useState<string | null>(null);

  const [options, setOptions] = useState<DecisionOption[] | null>(null);
  const [criteria, setCriteria] = useState<DecisionCriterion[] | null>(null);
  const [evidence, setEvidence] = useState<DecisionEvidence[] | null>(null);
  const [factors, setFactors] = useState<DecisionFactor[] | null>(null);

  const refreshDecision = () =>
    fetchDecision(decisionId)
      .then((d) => {
        setDecision(d);
        setDecisionError(null);
      })
      .catch(() => setDecisionError("Could not load this decision. It may have been removed."));

  const refreshOptions = () => listDecisionOptions(decisionId).then(setOptions).catch(() => setOptions([]));
  const refreshCriteria = () => listDecisionCriteria(decisionId).then(setCriteria).catch(() => setCriteria([]));
  const refreshEvidence = () => listDecisionEvidence(decisionId).then(setEvidence).catch(() => setEvidence([]));
  const refreshFactors = () => listDecisionFactors(decisionId).then(setFactors).catch(() => setFactors([]));

  useEffect(() => {
    setDecision(null);
    setOptions(null);
    setCriteria(null);
    setEvidence(null);
    setFactors(null);
    refreshDecision();
    refreshOptions();
    refreshCriteria();
    refreshEvidence();
    refreshFactors();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [decisionId]);

  async function runLifecycle(action: () => Promise<Decision>) {
    setBusy(true);
    setActionError(null);
    try {
      const updated = await action();
      setDecision(updated);
    } catch (err) {
      setActionError(err instanceof ApiError ? err.message : "That action could not be completed.");
    } finally {
      setBusy(false);
    }
  }

  async function handleSupersede() {
    if (!decision) return;
    setBusy(true);
    setActionError(null);
    try {
      const replacement = await createDecision({
        title: `Revisiting: ${decision.title}`,
        included_domain_slugs: decision.included_domain_slugs,
      });
      await supersedeDecision(decision.id, replacement.id);
      onBackToList();
    } catch (err) {
      setActionError(err instanceof ApiError ? err.message : "Could not supersede this decision with a new one.");
    } finally {
      setBusy(false);
    }
  }

  if (decisionError && !decision) {
    return (
      <div className="domain-view">
        <button type="button" className="back-button" onClick={onBackToList}>
          ← All decisions
        </button>
        <p className="error-banner" role="alert">
          {decisionError}
        </p>
      </div>
    );
  }

  const editable = decision ? ["draft", "evaluating", "reopened"].includes(decision.status) : false;

  return (
    <div className="domain-view">
      <button type="button" className="back-button" onClick={onBackToList}>
        ← All decisions
      </button>

      <ConsoleHeader
        indicator={<MiniCoreIndicator />}
        eyebrow="Decision"
        title={decision?.title ?? "Loading…"}
        meta={
          decision ? (
            <span>
              <span className={`status-chip ${STATUS_TONE[decision.status]}`}>{STATUS_LABEL[decision.status]}</span>
              {" · "}
              {decision.option_count} options · {decision.evidence_count} evidence
              {decision.review_due ? " · Review due" : ""}
            </span>
          ) : undefined
        }
        actions={
          decision && (
            <span className="mission-focus-add-actions">
              {decision.status === "draft" && (
                <button type="button" disabled={busy} onClick={() => runLifecycle(() => startEvaluatingDecision(decision.id))}>
                  Start evaluating
                </button>
              )}
              {(decision.status === "decided" || decision.status === "abandoned") && (
                <button type="button" disabled={busy} onClick={() => runLifecycle(() => reopenDecision(decision.id))}>
                  Reopen
                </button>
              )}
              {decision.status === "decided" && !decision.superseded_by_decision_id && (
                <button type="button" disabled={busy} onClick={handleSupersede}>
                  Supersede with a new decision
                </button>
              )}
              {["draft", "evaluating", "decided", "reopened"].includes(decision.status) && (
                <button
                  type="button"
                  disabled={busy}
                  onClick={() => runLifecycle(() => abandonDecision(decision.id))}
                >
                  Abandon
                </button>
              )}
            </span>
          )
        }
      />

      {actionError && (
        <p className="error-banner" role="alert">
          {actionError}
        </p>
      )}

      {decision?.status === "superseded" && decision.superseded_by_decision_id && (
        <p className="notice" role="status">
          This decision was superseded. It remains a read-only historical record.
        </p>
      )}
      {decision?.status === "abandoned" && (
        <p className="notice" role="status">
          This decision was abandoned{decision.abandoned_reason ? `: ${decision.abandoned_reason}` : "."} Reopen it to make changes again.
        </p>
      )}
      {!editable && decision && decision.status !== "superseded" && decision.status !== "abandoned" && (
        <p className="notice" role="status">
          This decision is decided and read-only. Reopen it to change options, criteria, evidence, or assumptions.
        </p>
      )}

      <section aria-label="Decision section">
        <div className="tab-row">
          {(["overview", "options", "criteria", "evidence", "factors", "briefs", "outcome"] as const).map((t) => (
            <label key={t}>
              <input type="radio" name="decision-tab" checked={tab === t} onChange={() => setTab(t)} />
              {t}
              {t === "options" && options !== null ? <span className="tab-count">{options.length}</span> : null}
              {t === "evidence" && evidence !== null ? <span className="tab-count">{evidence.length}</span> : null}
            </label>
          ))}
        </div>
      </section>

      {decision && tab === "overview" && <OverviewTab decision={decision} editable={editable} onChanged={refreshDecision} onNavigate={onNavigate} />}
      {decision && tab === "options" && (
        <OptionsTab decision={decision} editable={editable} options={options} onChanged={refreshOptions} onDecided={refreshDecision} />
      )}
      {decision && tab === "criteria" && (
        <CriteriaTab decision={decision} editable={editable} options={options} criteria={criteria} onCriteriaChanged={refreshCriteria} />
      )}
      {decision && tab === "evidence" && (
        <EvidenceTab decision={decision} editable={editable} evidence={evidence} onEvidenceChanged={refreshEvidence} onNavigate={onNavigate} />
      )}
      {decision && tab === "factors" && (
        <FactorsTab decision={decision} editable={editable} factors={factors} onFactorsChanged={refreshFactors} />
      )}
      {decision && tab === "briefs" && (
        <BriefsTab decision={decision} onDecisionChanged={refreshDecision} onNavigate={onNavigate} />
      )}
      {decision && tab === "outcome" && <OutcomeTab decision={decision} />}
    </div>
  );
}

// ---------------------------------------------------------------------------

function OverviewTab({
  decision, editable, onChanged, onNavigate,
}: {
  decision: Decision; editable: boolean; onChanged: () => void; onNavigate: (t: NavigateTarget) => void;
}) {
  const [description, setDescription] = useState(decision.description ?? "");
  const [reviewDate, setReviewDate] = useState(decision.review_date ? decision.review_date.slice(0, 10) : "");
  const [costOfDelay, setCostOfDelay] = useState(decision.cost_of_delay_note ?? "");
  const [infoConfidence, setInfoConfidence] = useState<number | "">(decision.info_confidence ?? "");
  const [reversibility, setReversibility] = useState<DecisionReversibility | "">(decision.reversibility ?? "");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const [workspaces, setWorkspaces] = useState<ResearchWorkspace[] | null>(null);
  const [linkBusy, setLinkBusy] = useState(false);

  useEffect(() => {
    fetchResearchWorkspaces().then(setWorkspaces).catch(() => setWorkspaces([]));
  }, []);

  async function handleSave(e: React.FormEvent) {
    e.preventDefault();
    setBusy(true);
    setError(null);
    try {
      await updateDecision(decision.id, {
        description: description.trim() ? description.trim() : null,
        review_date: reviewDate ? new Date(reviewDate).toISOString() : null,
        cost_of_delay_note: costOfDelay.trim() ? costOfDelay.trim() : null,
        info_confidence: infoConfidence === "" ? null : infoConfidence,
        reversibility: reversibility === "" ? null : reversibility,
      });
      onChanged();
    } catch {
      setError("Could not save these details.");
    } finally {
      setBusy(false);
    }
  }

  async function handleLinkWorkspace(workspaceId: string) {
    setLinkBusy(true);
    setError(null);
    try {
      await linkDecisionResearchWorkspace(decision.id, workspaceId || null);
      onChanged();
    } catch {
      setError("Could not link that research workspace.");
    } finally {
      setLinkBusy(false);
    }
  }

  const linkedWorkspace = workspaces?.find((w) => w.id === decision.research_workspace_id) ?? null;

  return (
    <>
      <ConsoleModule title="Details" ariaLabel="Decision details">
        {!editable && <p className="notice">This decision is read-only. Reopen it to change these details.</p>}
        <form className="decision-details-form" onSubmit={handleSave}>
          <textarea
            placeholder="Description (optional)"
            value={description}
            onChange={(e) => setDescription(e.target.value)}
            aria-label="Description"
            rows={2}
            disabled={!editable}
          />
          <label>
            Review date
            <input type="date" value={reviewDate} onChange={(e) => setReviewDate(e.target.value)} aria-label="Review date" disabled={!editable} />
          </label>
          <textarea
            placeholder="Cost of delay (optional)"
            value={costOfDelay}
            onChange={(e) => setCostOfDelay(e.target.value)}
            aria-label="Cost of delay"
            rows={2}
            disabled={!editable}
          />
          <label>
            Confidence in information (1-5)
            <select
              value={infoConfidence}
              onChange={(e) => setInfoConfidence(e.target.value === "" ? "" : Number(e.target.value))}
              aria-label="Confidence in information"
              disabled={!editable}
            >
              <option value="">Not set</option>
              {[1, 2, 3, 4, 5].map((n) => (
                <option key={n} value={n}>
                  {n}
                </option>
              ))}
            </select>
          </label>
          <label>
            Reversibility
            <select
              value={reversibility}
              onChange={(e) => setReversibility(e.target.value as DecisionReversibility | "")}
              aria-label="Reversibility"
              disabled={!editable}
            >
              <option value="">Not set</option>
              <option value="easily_reversible">Easily reversible</option>
              <option value="hard_to_reverse">Hard to reverse</option>
              <option value="irreversible">Irreversible</option>
            </select>
          </label>
          {editable && (
            <button type="submit" disabled={busy}>
              {busy ? "Saving…" : "Save details"}
            </button>
          )}
        </form>
        {error && (
          <p className="error-banner" role="alert">
            {error}
          </p>
        )}
      </ConsoleModule>

      <ConsoleModule title="Linked research workspace" ariaLabel="Linked research workspace">
        <p className="notice" role="status">
          Evidence discovery is scoped to the intersection of this decision's own domains and the linked workspace's domains — never their union.
        </p>
        {editable && (
          <label>
            Research workspace
            <select
              value={decision.research_workspace_id ?? ""}
              onChange={(e) => handleLinkWorkspace(e.target.value)}
              aria-label="Linked research workspace"
              disabled={linkBusy || workspaces === null}
            >
              <option value="">None</option>
              {(workspaces ?? []).map((w) => (
                <option key={w.id} value={w.id}>
                  {w.title}
                </option>
              ))}
            </select>
          </label>
        )}
        {!editable && linkedWorkspace && <p className="message-content">{linkedWorkspace.title}</p>}
        {!editable && !linkedWorkspace && <p className="ledger-empty">No research workspace linked.</p>}
      </ConsoleModule>

      {decision.supersedes_decision_id && (
        <ConsoleModule title="Supersedes" ariaLabel="Superseded decision">
          <button type="button" onClick={() => onNavigate("decision_centre")}>
            View decision this one supersedes
          </button>
        </ConsoleModule>
      )}
      {decision.superseded_by_decision_id && (
        <ConsoleModule title="Superseded by" ariaLabel="Superseding decision">
          <button type="button" onClick={() => onNavigate("decision_centre")}>
            View the decision that superseded this one
          </button>
        </ConsoleModule>
      )}
    </>
  );
}

// ---------------------------------------------------------------------------

function OptionsTab({
  decision, editable, options, onChanged, onDecided,
}: {
  decision: Decision; editable: boolean; options: DecisionOption[] | null; onChanged: () => void; onDecided: () => void;
}) {
  const [name, setName] = useState("");
  const [benefits, setBenefits] = useState("");
  const [costs, setCosts] = useState("");
  const [risks, setRisks] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const [decideOptionId, setDecideOptionId] = useState("");
  const [rationale, setRationale] = useState("");
  const [confidence, setConfidence] = useState(3);
  const [decideBusy, setDecideBusy] = useState(false);
  const [decideError, setDecideError] = useState<string | null>(null);

  async function handleAdd(e: React.FormEvent) {
    e.preventDefault();
    if (!name.trim()) return;
    setBusy(true);
    setError(null);
    try {
      await addDecisionOption(decision.id, { name: name.trim(), benefits: benefits || null, costs: costs || null, risks: risks || null });
      setName("");
      setBenefits("");
      setCosts("");
      setRisks("");
      onChanged();
    } catch {
      setError("Could not add this option.");
    } finally {
      setBusy(false);
    }
  }

  async function handleEliminate(option: DecisionOption) {
    try {
      await updateDecisionOption(decision.id, option.id, { status: option.status === "eliminated" ? "active" : "eliminated" });
      onChanged();
    } catch {
      /* row stays as-is */
    }
  }

  async function handleDecide(e: React.FormEvent) {
    e.preventDefault();
    if (!decideOptionId || !rationale.trim()) return;
    setDecideBusy(true);
    setDecideError(null);
    try {
      await decideDecision(decision.id, { selected_option_id: decideOptionId, rationale: rationale.trim(), decision_confidence: confidence });
      setRationale("");
      onDecided();
      onChanged();
    } catch (err) {
      setDecideError(err instanceof ApiError ? err.message : "Could not record this decision.");
    } finally {
      setDecideBusy(false);
    }
  }

  const canDecide = ["draft", "evaluating", "reopened"].includes(decision.status);
  const activeOptions = (options ?? []).filter((o) => o.status !== "eliminated");

  return (
    <>
      {editable && (
        <ConsoleModule title="Add an option" ariaLabel="Add a decision option">
          <form className="decision-details-form" onSubmit={handleAdd}>
            <input type="text" placeholder="Option name" value={name} onChange={(e) => setName(e.target.value)} aria-label="Option name" />
            <textarea placeholder="Benefits" value={benefits} onChange={(e) => setBenefits(e.target.value)} aria-label="Benefits" rows={2} />
            <textarea placeholder="Costs / trade-offs" value={costs} onChange={(e) => setCosts(e.target.value)} aria-label="Costs" rows={2} />
            <textarea placeholder="Risks" value={risks} onChange={(e) => setRisks(e.target.value)} aria-label="Risks" rows={2} />
            <button type="submit" disabled={busy || !name.trim()}>
              {busy ? "Adding…" : "Add option"}
            </button>
          </form>
          {error && (
            <p className="error-banner" role="alert">
              {error}
            </p>
          )}
        </ConsoleModule>
      )}

      <ConsoleModule title="Options" ariaLabel="Options under consideration">
        {options === null && <p className="ledger-empty">Loading options…</p>}
        {options !== null && options.length === 0 && <p className="ledger-empty">No options yet — add at least one to evaluate this decision.</p>}
        {options !== null && options.length > 0 && (
          <div className="ledger">
            {options.map((o) => (
              <div key={o.id} className="ledger-row" style={{ flexDirection: "column", alignItems: "stretch" }}>
                <div style={{ display: "flex", justifyContent: "space-between", gap: "0.5rem", flexWrap: "wrap" }}>
                  <span className="ledger-row-main">{o.name}</span>
                  <span className={`status-chip ${o.status === "chosen" ? "tone-ok" : o.status === "eliminated" ? "tone-neutral" : "tone-active"}`}>
                    {o.status}
                  </span>
                </div>
                {o.benefits && <p className="message-content">Benefits: {o.benefits}</p>}
                {o.costs && <p className="message-content">Costs: {o.costs}</p>}
                {o.risks && <p className="message-content">Risks: {o.risks}</p>}
                {editable && o.status !== "chosen" && (
                  <div className="ledger-row-actions">
                    <button type="button" onClick={() => handleEliminate(o)}>
                      {o.status === "eliminated" ? "Reactivate" : "Eliminate"}
                    </button>
                  </div>
                )}
              </div>
            ))}
          </div>
        )}
      </ConsoleModule>

      {canDecide && activeOptions.length > 0 && (
        <ConsoleModule title="Record your decision" ariaLabel="Decide">
          <p className="notice" role="status">
            This records your own final decision, separate from any Jarvis critique — Jarvis never decides for you.
          </p>
          <form className="decision-details-form" onSubmit={handleDecide}>
            <label>
              Selected option
              <select value={decideOptionId} onChange={(e) => setDecideOptionId(e.target.value)} aria-label="Selected option">
                <option value="">Choose…</option>
                {activeOptions.map((o) => (
                  <option key={o.id} value={o.id}>
                    {o.name}
                  </option>
                ))}
              </select>
            </label>
            <textarea
              placeholder="Your rationale, in your own words"
              value={rationale}
              onChange={(e) => setRationale(e.target.value)}
              aria-label="Rationale"
              rows={3}
            />
            <label>
              Confidence in this decision (1-5)
              <select value={confidence} onChange={(e) => setConfidence(Number(e.target.value))} aria-label="Decision confidence">
                {[1, 2, 3, 4, 5].map((n) => (
                  <option key={n} value={n}>
                    {n}
                  </option>
                ))}
              </select>
            </label>
            <button type="submit" disabled={decideBusy || !decideOptionId || !rationale.trim()}>
              {decideBusy ? "Recording…" : "Decide"}
            </button>
          </form>
          {decideError && (
            <p className="error-banner" role="alert">
              {decideError}
            </p>
          )}
        </ConsoleModule>
      )}
    </>
  );
}

// ---------------------------------------------------------------------------

function CriteriaTab({
  decision, editable, options, criteria, onCriteriaChanged,
}: {
  decision: Decision; editable: boolean; options: DecisionOption[] | null; criteria: DecisionCriterion[] | null; onCriteriaChanged: () => void;
}) {
  const [name, setName] = useState("");
  const [weight, setWeight] = useState(3);
  const [busy, setBusy] = useState(false);
  const [breakdown, setBreakdown] = useState<DecisionScoreBreakdown | null>(null);
  const [breakdownError, setBreakdownError] = useState<string | null>(null);
  const [assessments, setAssessments] = useState<DecisionAssessment[]>([]);

  const refreshBreakdown = () =>
    fetchDecisionScoreBreakdown(decision.id)
      .then(setBreakdown)
      .catch(() => setBreakdownError("Could not load the score breakdown."));

  const refreshAssessments = () =>
    listDecisionAssessments(decision.id)
      .then(setAssessments)
      .catch(() => setBreakdownError("Could not load existing assessment scores."));

  useEffect(() => {
    refreshBreakdown();
    refreshAssessments();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [decision.id, options, criteria]);

  async function handleAdd(e: React.FormEvent) {
    e.preventDefault();
    if (!name.trim()) return;
    setBusy(true);
    try {
      await addDecisionCriterion(decision.id, { name: name.trim(), weight });
      setName("");
      setWeight(3);
      onCriteriaChanged();
    } catch {
      setBreakdownError("Could not add this criterion.");
    } finally {
      setBusy(false);
    }
  }

  async function handleRemove(criterionId: string) {
    try {
      await removeDecisionCriterion(decision.id, criterionId);
      onCriteriaChanged();
    } catch {
      /* no-op */
    }
  }

  async function handleAssess(optionId: string, criterionId: string, score: number | null) {
    try {
      await setDecisionAssessment(decision.id, { option_id: optionId, criterion_id: criterionId, score });
      refreshBreakdown();
      refreshAssessments();
    } catch {
      /* no-op */
    }
  }

  const activeOptions = (options ?? []).filter((o) => o.status !== "eliminated");
  const scoreByOption = new Map((breakdown?.options ?? []).map((o) => [o.option_id, o]));
  const assessmentByPair = new Map(assessments.map((a) => [`${a.option_id}:${a.criterion_id}`, a]));

  return (
    <>
      {editable && (
        <ConsoleModule title="Add a criterion" ariaLabel="Add an evaluation criterion">
          <form className="message-form-actions" onSubmit={handleAdd}>
            <input type="text" placeholder="Criterion name" value={name} onChange={(e) => setName(e.target.value)} aria-label="Criterion name" />
            <label>
              <span className="sr-only">Importance (1-5)</span>
              <select value={weight} onChange={(e) => setWeight(Number(e.target.value))} aria-label="Importance weight">
                {[1, 2, 3, 4, 5].map((n) => (
                  <option key={n} value={n}>
                    Weight {n}
                  </option>
                ))}
              </select>
            </label>
            <button type="submit" disabled={busy || !name.trim()}>
              Add
            </button>
          </form>
        </ConsoleModule>
      )}

      <ConsoleModule title="Criteria" ariaLabel="Evaluation criteria">
        {criteria === null && <p className="ledger-empty">Loading criteria…</p>}
        {criteria !== null && criteria.length === 0 && <p className="ledger-empty">No criteria yet.</p>}
        {criteria !== null && criteria.length > 0 && (
          <div className="ledger">
            {criteria.map((c) => (
              <div key={c.id} className="ledger-row">
                <span className="ledger-row-main">{c.name}</span>
                <span className="ledger-row-meta">weight {c.weight}</span>
                {editable && (
                  <div className="ledger-row-actions">
                    <button type="button" onClick={() => handleRemove(c.id)}>
                      Remove
                    </button>
                  </div>
                )}
              </div>
            ))}
          </div>
        )}
      </ConsoleModule>

      {activeOptions.length > 0 && criteria !== null && criteria.length > 0 && (
        <ConsoleModule title="Assessment matrix" ariaLabel="Option by criterion assessment">
          <div style={{ overflowX: "auto" }}>
            <table>
              <thead>
                <tr>
                  <th scope="col">Option</th>
                  {criteria.map((c) => (
                    <th scope="col" key={c.id}>
                      {c.name} (×{c.weight})
                    </th>
                  ))}
                  <th scope="col">Total</th>
                </tr>
              </thead>
              <tbody>
                {activeOptions.map((o) => (
                  <tr key={o.id}>
                    <th scope="row">{o.name}</th>
                    {criteria.map((c) => {
                      const existing = assessmentByPair.get(`${o.id}:${c.id}`);
                      const currentValue = existing?.score ?? "";
                      return (
                      <td key={c.id}>
                        <label>
                          <span className="sr-only">
                            {o.name} — {c.name}
                          </span>
                          <select
                            value={currentValue}
                            onChange={(e) => handleAssess(o.id, c.id, e.target.value === "" ? null : Number(e.target.value))}
                            disabled={!editable}
                            aria-label={`Score for ${o.name} on ${c.name}`}
                          >
                            <option value="">unassessed</option>
                            {[1, 2, 3, 4, 5].map((n) => (
                              <option key={n} value={n}>
                                {n}
                              </option>
                            ))}
                          </select>
                        </label>
                      </td>
                      );
                    })}
                    <td>{scoreByOption.get(o.id)?.total_score ?? "—"}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </ConsoleModule>
      )}

      {breakdownError && (
        <p className="error-banner" role="alert">
          {breakdownError}
        </p>
      )}

      {breakdown && (
        <ConsoleModule title="Score breakdown" ariaLabel="Deterministic score breakdown">
          <p className="notice" role="status">
            A plain weighted sum — never a hidden normalization or a claim of objective truth. Verify it against your own judgement.
          </p>
          <div className="ledger">
            {breakdown.options.map((o, idx) => (
              <div key={o.option_id} className="ledger-row">
                <span className="ledger-row-main">
                  {idx === 0 && breakdown.ranked_option_ids[0] === o.option_id ? "🏆 " : ""}
                  {o.option_name}
                </span>
                <span className="ledger-row-meta">
                  {o.total_score} points · {o.assessed_count}/{o.total_criteria} assessed
                  {o.missing_criterion_names.length > 0 ? ` · missing: ${o.missing_criterion_names.join(", ")}` : ""}
                </span>
              </div>
            ))}
          </div>
          {breakdown.tied && (
            <p className="notice" role="status">
              The top options are tied — this comparison alone doesn't favor one over the other.
            </p>
          )}
          {breakdown.incomplete && (
            <p className="notice" role="status">
              Incomplete assessment — some option/criterion combinations have not been scored yet.
            </p>
          )}
          {breakdown.sensitivity_warnings.map((w) => (
            <p key={w.criterion_id} className="error-banner" role="alert">
              {w.explanation}
            </p>
          ))}
        </ConsoleModule>
      )}
    </>
  );
}

// ---------------------------------------------------------------------------

function EvidenceTab({
  decision, editable, evidence, onEvidenceChanged, onNavigate,
}: {
  decision: Decision; editable: boolean; evidence: DecisionEvidence[] | null;
  onEvidenceChanged: () => void; onNavigate: (t: NavigateTarget) => void;
}) {
  const [query, setQuery] = useState("");
  const [results, setResults] = useState<RecallResult[] | null>(null);
  const [partialFailures, setPartialFailures] = useState<string[]>([]);
  const [searchLoading, setSearchLoading] = useState(false);
  const [searchError, setSearchError] = useState<string | null>(null);
  const [addingKey, setAddingKey] = useState<string | null>(null);
  const abortRef = useRef<AbortController | null>(null);

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
      searchDecisionEvidence(decision.id, { q: query.trim(), limit: PAGE_SIZE }, controller.signal)
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
  }, [query, decision.id]);

  const addedKeys = useMemo(() => new Set((evidence ?? []).map((e) => evidenceKey(e.source_type, e.source_id))), [evidence]);

  async function handleAdd(result: RecallResult) {
    const key = evidenceKey(result.source_type, result.source_id);
    setAddingKey(key);
    try {
      await addDecisionEvidence(decision.id, { source_type: result.source_type as DecisionSourceType, source_id: result.source_id });
      onEvidenceChanged();
    } catch {
      setSearchError("Could not add that item as evidence.");
    } finally {
      setAddingKey(null);
    }
  }

  return (
    <>
      <ConsoleModule title="Find evidence" ariaLabel="Search for evidence to link">
        {!editable && <p className="notice">Reopen this decision to add new evidence.</p>}
        <form className="message-form-actions" onSubmit={(e) => e.preventDefault()}>
          <input
            type="text"
            placeholder="Search Jarvis for evidence…"
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            aria-label="Search for evidence"
            disabled={!editable}
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
          <p className="ledger-empty">No results in this decision's included domains.</p>
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
                    <button type="button" className="briefing-strip-button" onClick={() => handleAdd(result)} disabled={already || !editable || addingKey === key}>
                      {already ? "Added" : addingKey === key ? "Adding…" : "Add as evidence"}
                    </button>
                  </div>
                </li>
              );
            })}
          </ul>
        )}
      </ConsoleModule>

      <ConsoleModule title="Evidence" ariaLabel="Linked evidence">
        {evidence === null && <p className="ledger-empty">Loading evidence…</p>}
        {evidence !== null && evidence.length === 0 && <p className="ledger-empty">No evidence linked yet — search above to find some.</p>}
        {evidence !== null && evidence.length > 0 && (
          <div className="ledger">
            {evidence.map((item) => (
              <div key={item.id} className="ledger-row" style={{ flexDirection: "column", alignItems: "stretch" }}>
                <div style={{ display: "flex", justifyContent: "space-between", gap: "0.5rem", flexWrap: "wrap" }}>
                  <span className="ledger-row-main">{item.title_snapshot}</span>
                  <span className={`status-chip ${STANCE_TONE[item.stance]}`}>{STANCE_LABEL[item.stance]}</span>
                </div>
                <p className="message-content">{item.snippet_snapshot}</p>
                <span className="ledger-row-meta">
                  {item.domain_slug ? item.domain_slug.toUpperCase() : "Global"}
                  {item.occurred_at_snapshot ? ` · ${formatDate(item.occurred_at_snapshot)}` : ""}
                  {!item.available && ` · ${item.unavailable_reason ?? "Source unavailable"}`}
                </span>
                <div className="ledger-row-actions">
                  {item.available && isNavigateTarget(item.link_target) && (
                    <button type="button" onClick={() => onNavigate(item.link_target as NavigateTarget)}>
                      Open source
                    </button>
                  )}
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

function FactorsTab({
  decision, editable, factors, onFactorsChanged,
}: {
  decision: Decision; editable: boolean; factors: DecisionFactor[] | null; onFactorsChanged: () => void;
}) {
  const [kind, setKind] = useState<DecisionFactorKind>("assumption");
  const [content, setContent] = useState("");
  const [busy, setBusy] = useState(false);

  async function handleAdd(e: React.FormEvent) {
    e.preventDefault();
    if (!content.trim()) return;
    setBusy(true);
    try {
      await addDecisionFactor(decision.id, { kind, content: content.trim() });
      setContent("");
      onFactorsChanged();
    } finally {
      setBusy(false);
    }
  }

  async function handleResolve(factor: DecisionFactor) {
    try {
      await resolveDecisionFactor(decision.id, factor.id);
      onFactorsChanged();
    } catch {
      /* no-op */
    }
  }

  return (
    <>
      {editable && (
        <ConsoleModule title="Add an assumption, risk, or unknown" ariaLabel="Add a factor">
          <form className="decision-details-form" onSubmit={handleAdd}>
            <label>
              <span className="sr-only">Kind</span>
              <select value={kind} onChange={(e) => setKind(e.target.value as DecisionFactorKind)} aria-label="Factor kind">
                <option value="assumption">Assumption</option>
                <option value="risk">Risk</option>
                <option value="unknown">Unknown</option>
              </select>
            </label>
            <textarea value={content} onChange={(e) => setContent(e.target.value)} aria-label="Factor content" rows={2} placeholder="What are you assuming, risking, or unsure about?" />
            <button type="submit" disabled={busy || !content.trim()}>
              Add
            </button>
          </form>
        </ConsoleModule>
      )}

      <ConsoleModule title="Assumptions, risks, and unknowns" ariaLabel="Factor register">
        {factors === null && <p className="ledger-empty">Loading…</p>}
        {factors !== null && factors.length === 0 && <p className="ledger-empty">Nothing recorded yet.</p>}
        {factors !== null && factors.length > 0 && (
          <div className="ledger">
            {factors.map((f) => (
              <div key={f.id} className="ledger-row">
                <span className={`status-chip ${f.kind === "risk" ? "tone-warn" : "tone-neutral"}`}>{FACTOR_KIND_LABEL[f.kind]}</span>
                <span className="ledger-row-main message-content">{f.content}</span>
                <span className="ledger-row-meta">{f.status === "resolved" ? `Resolved${f.resolution_note ? `: ${f.resolution_note}` : ""}` : "Open"}</span>
                {f.status === "open" && (
                  <div className="ledger-row-actions">
                    <button type="button" onClick={() => handleResolve(f)}>
                      Resolve
                    </button>
                  </div>
                )}
              </div>
            ))}
          </div>
        )}
      </ConsoleModule>
    </>
  );
}

// ---------------------------------------------------------------------------

function BriefsTab({
  decision, onDecisionChanged, onNavigate,
}: {
  decision: Decision; onDecisionChanged: () => void; onNavigate: (t: NavigateTarget) => void;
}) {
  const [versions, setVersions] = useState<DecisionBriefVersionSummary[] | null>(null);
  const [selected, setSelected] = useState<DecisionBriefVersion | null>(null);
  const [selectedError, setSelectedError] = useState<string | null>(null);
  const [generating, setGenerating] = useState(false);
  const [critiquing, setCritiquing] = useState(false);
  const [actionError, setActionError] = useState<string | null>(null);
  const editable = ["draft", "evaluating", "reopened"].includes(decision.status);
  const noOptions = decision.option_count === 0;

  const refreshVersions = () => listDecisionBriefs(decision.id).then(setVersions).catch(() => setVersions([]));

  useEffect(() => {
    setVersions(null);
    setSelected(null);
    refreshVersions();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [decision.id]);

  async function openVersion(id: string) {
    setSelectedError(null);
    try {
      setSelected(await getDecisionBrief(decision.id, id));
    } catch {
      setSelectedError("Could not load this brief version.");
    }
  }

  async function handleGenerate() {
    setGenerating(true);
    setActionError(null);
    try {
      const version = await generateDecisionDeterministicBrief(decision.id);
      await refreshVersions();
      onDecisionChanged();
      setSelected(version);
    } catch (err) {
      setActionError(err instanceof ApiError ? err.message : "Could not generate the decision brief.");
    } finally {
      setGenerating(false);
    }
  }

  async function handleCritique() {
    setCritiquing(true);
    setActionError(null);
    try {
      const version = await draftDecisionCritique(decision.id);
      await refreshVersions();
      onDecisionChanged();
      setSelected(version);
    } catch (err) {
      if (err instanceof ApiError && err.status === 502) {
        setActionError("Jarvis model is currently unavailable — the deterministic brief above still works without it.");
      } else if (err instanceof ApiError) {
        setActionError(err.message);
      } else {
        setActionError("Could not reach Jarvis to challenge this decision.");
      }
    } finally {
      setCritiquing(false);
    }
  }

  return (
    <>
      <ConsoleModule title="Generate a brief" ariaLabel="Generate a decision brief">
        {!editable && <p className="notice">This decision is read-only — briefs can still be generated for reference.</p>}
        {noOptions && <p className="notice">Add at least one option first.</p>}
        <div className="mission-focus-add-actions">
          <button type="button" onClick={handleGenerate} disabled={generating || noOptions}>
            {generating ? "Generating…" : "Generate decision brief"}
          </button>
          <button type="button" onClick={handleCritique} disabled={critiquing || noOptions}>
            {critiquing ? "Asking Jarvis…" : "Ask Jarvis to challenge this decision"}
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
              <button key={v.id} type="button" className="ledger-row" style={{ width: "100%", textAlign: "left", cursor: "pointer" }} onClick={() => openVersion(v.id)}>
                <span className="ledger-row-main">
                  v{v.version_number} — {v.source === "model" ? "Jarvis model-generated critique" : "Decision brief"}
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

function BriefDetail({ version, onNavigate }: { version: DecisionBriefVersion; onNavigate: (t: NavigateTarget) => void }) {
  const citationByNumber = useMemo(() => {
    const map = new Map<number, (typeof version.citations)[number]>();
    for (const c of version.citations) map.set(c.number, c);
    return map;
  }, [version.citations]);

  let parsed: Record<string, unknown> = {};
  try {
    parsed = JSON.parse(version.sections_json);
  } catch {
    parsed = {};
  }
  const sections = (parsed.sections as Array<Record<string, unknown>>) ?? [];
  const missingInfoWarnings = (parsed.missing_info_warnings as string[] | undefined) ?? [];

  return (
    <ConsoleModule title={version.source === "model" ? "Jarvis model-generated critique" : "Decision brief"} ariaLabel="Brief detail">
      {version.source === "model" && (
        <p className="notice" role="status">
          Jarvis model-generated critique — synthesized only from this decision's own content and selected evidence. It never decides for you.
        </p>
      )}
      {version.status === "invalid_citations" && version.validation_issues.length > 0 && (
        <p className="error-banner" role="alert">
          {version.validation_issues.join(" ")}
        </p>
      )}
      {missingInfoWarnings.map((w, i) => (
        <p key={i} className="notice" role="status">
          {w}
        </p>
      ))}

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
                  <span key={runIdx} className={citation ? "status-chip tone-active" : "status-chip tone-warn"} title={citation ? citation.title_snapshot : "This citation does not match any evidence in this decision"}>
                    {run.text}
                  </span>
                );
              })}
            </p>
          );
        }
        if (kind === "score_breakdown") {
          const options = (section.options as Array<Record<string, unknown>>) ?? [];
          return (
            <div key={idx}>
              <h3 className="console-section-label">Score breakdown</h3>
              <ul>
                {options.map((o, oi) => (
                  <li key={oi} className="message-content">
                    {String(o.option_name)}: {String(o.total_score)} points
                  </li>
                ))}
              </ul>
            </div>
          );
        }
        if (kind === "options" || kind === "criteria" || kind === "general_evidence" || kind === "factors") {
          return (
            <div key={idx}>
              <h3 className="console-section-label">{String(section.heading ?? kind)}</h3>
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

// ---------------------------------------------------------------------------

function OutcomeTab({ decision }: { decision: Decision }) {
  const [finalVersions, setFinalVersions] = useState<DecisionFinalVersion[] | null>(null);
  const [reviews, setReviews] = useState<DecisionOutcomeReview[] | null>(null);
  const [whatHappened, setWhatHappened] = useState("");
  const [achieved, setAchieved] = useState<"" | "yes" | "no">("");
  const [confidenceOk, setConfidenceOk] = useState<"" | "yes" | "no">("");
  const [sameAgain, setSameAgain] = useState<"" | "yes" | "no">("");
  const [lessons, setLessons] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    listDecisionFinalVersions(decision.id).then(setFinalVersions).catch(() => setFinalVersions([]));
    listDecisionOutcomeReviews(decision.id).then(setReviews).catch(() => setReviews([]));
  }, [decision.id]);

  const canReview = finalVersions !== null && finalVersions.length > 0;

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    if (!whatHappened.trim()) return;
    setBusy(true);
    setError(null);
    try {
      const toBool = (v: "" | "yes" | "no") => (v === "" ? null : v === "yes");
      const review = await addDecisionOutcomeReview(decision.id, {
        what_happened: whatHappened.trim(),
        intended_outcome_achieved: toBool(achieved),
        confidence_was_appropriate: toBool(confidenceOk),
        would_decide_same_again: toBool(sameAgain),
        lessons_learned: lessons || null,
      });
      setReviews((prev) => [review, ...(prev ?? [])]);
      setWhatHappened("");
      setLessons("");
      setAchieved("");
      setConfidenceOk("");
      setSameAgain("");
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Could not save this outcome review.");
    } finally {
      setBusy(false);
    }
  }

  return (
    <>
      <ConsoleModule title="Decision history" ariaLabel="Final decision history">
        {finalVersions === null && <p className="ledger-empty">Loading…</p>}
        {finalVersions !== null && finalVersions.length === 0 && <p className="ledger-empty">This decision has not been decided yet.</p>}
        {finalVersions !== null && finalVersions.length > 0 && (
          <div className="ledger">
            {finalVersions.map((v) => (
              <div key={v.id} className="ledger-row" style={{ flexDirection: "column", alignItems: "stretch" }}>
                <span className="ledger-row-main">
                  v{v.version_number}: {v.selected_option_name} (confidence {v.decision_confidence}/5)
                </span>
                <p className="message-content">{v.rationale}</p>
                <span className="ledger-row-meta">{formatDate(v.decided_at)} · read-only historical record</span>
              </div>
            ))}
          </div>
        )}
      </ConsoleModule>

      {canReview && (
        <ConsoleModule title="Add an outcome review" ariaLabel="Review the real-world outcome">
          <p className="notice" role="status">
            This never changes the original decision or rationale — it is a separate, additive record.
          </p>
          <form className="decision-details-form" onSubmit={handleSubmit}>
            <textarea value={whatHappened} onChange={(e) => setWhatHappened(e.target.value)} aria-label="What happened" placeholder="What happened?" rows={3} />
            <label>
              Intended outcome achieved?
              <select value={achieved} onChange={(e) => setAchieved(e.target.value as typeof achieved)} aria-label="Intended outcome achieved">
                <option value="">Not sure</option>
                <option value="yes">Yes</option>
                <option value="no">No</option>
              </select>
            </label>
            <label>
              Was confidence appropriate?
              <select value={confidenceOk} onChange={(e) => setConfidenceOk(e.target.value as typeof confidenceOk)} aria-label="Was confidence appropriate">
                <option value="">Not sure</option>
                <option value="yes">Yes</option>
                <option value="no">No</option>
              </select>
            </label>
            <label>
              Would you decide the same again?
              <select value={sameAgain} onChange={(e) => setSameAgain(e.target.value as typeof sameAgain)} aria-label="Would decide the same again">
                <option value="">Not sure</option>
                <option value="yes">Yes</option>
                <option value="no">No</option>
              </select>
            </label>
            <textarea value={lessons} onChange={(e) => setLessons(e.target.value)} aria-label="Lessons learned" placeholder="Lessons learned (optional)" rows={2} />
            <button type="submit" disabled={busy || !whatHappened.trim()}>
              {busy ? "Saving…" : "Save outcome review"}
            </button>
          </form>
          {error && (
            <p className="error-banner" role="alert">
              {error}
            </p>
          )}
        </ConsoleModule>
      )}

      <ConsoleModule title="Past reviews" ariaLabel="Outcome review history">
        {reviews === null && <p className="ledger-empty">Loading…</p>}
        {reviews !== null && reviews.length === 0 && <p className="ledger-empty">No outcome reviews yet.</p>}
        {reviews !== null && reviews.length > 0 && (
          <div className="ledger">
            {reviews.map((r) => (
              <div key={r.id} className="ledger-row" style={{ flexDirection: "column", alignItems: "stretch" }}>
                <p className="message-content">{r.what_happened}</p>
                {r.lessons_learned && <p className="message-content">Lessons: {r.lessons_learned}</p>}
                <span className="ledger-row-meta">{formatDate(r.reviewed_at)}</span>
              </div>
            ))}
          </div>
        )}
      </ConsoleModule>
    </>
  );
}

export default DecisionCentre;
