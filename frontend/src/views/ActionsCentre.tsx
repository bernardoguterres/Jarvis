import { useCallback, useEffect, useState } from "react";
import {
  approveActionProposal,
  denyActionProposal,
  executeActionProposal,
  fetchMissionFocus,
  getActionProposal,
  listActionProposals,
  type ActionAuditEvent,
  type ActionProposal,
  type ActionStatus,
  type MissionFocusPin,
} from "../api";
import AddToMissionFocusButton from "../components/AddToMissionFocusButton";
import StatusChip, { type ChipTone } from "../components/StatusChip";
import { ConsoleHeader, ConsoleModule, MiniCoreIndicator, TechnicalDetails } from "../components/console/Console";
import { formatDateTime } from "../formatDateTime";

// Phase 12C: only genuinely unresolved proposals are offered "Add to
// Mission Focus" — a settled one (succeeded/denied/expired/failed) is
// already visible in its own history and isn't an ongoing concern to
// keep on a watchlist.
const MISSION_FOCUS_ELIGIBLE_STATUSES: ActionStatus[] = ["proposed", "approved"];

const STATUS_TONE: Record<ActionStatus, ChipTone> = {
  proposed: "warn",
  approved: "active",
  executing: "active",
  succeeded: "ok",
  denied: "neutral",
  expired: "neutral",
  failed: "error",
};

const TIMELINE_TONE: Record<string, string> = {
  proposed: "warn",
  approved: "active",
  executing: "active",
  succeeded: "ok",
  denied: "neutral",
  expired: "neutral",
  failed: "error",
};

const PENDING_STATUSES: ActionStatus[] = ["proposed", "approved", "executing"];

interface ActionsCentreProps {
  onBack: () => void;
}

const STATUS_FILTERS: Array<ActionStatus | "all"> = [
  "all",
  "proposed",
  "approved",
  "executing",
  "succeeded",
  "denied",
  "expired",
  "failed",
];

function ActionsCentre({ onBack }: ActionsCentreProps) {
  const [proposals, setProposals] = useState<ActionProposal[]>([]);
  const [statusFilter, setStatusFilter] = useState<ActionStatus | "all">("all");
  const [error, setError] = useState<string | null>(null);
  const [expandedId, setExpandedId] = useState<string | null>(null);
  const [auditEvents, setAuditEvents] = useState<Record<string, ActionAuditEvent[]>>({});
  const [busyId, setBusyId] = useState<string | null>(null);
  const [missionFocusPins, setMissionFocusPins] = useState<MissionFocusPin[]>([]);

  const refresh = useCallback(async () => {
    try {
      const data = await listActionProposals(
        statusFilter === "all" ? {} : { status: statusFilter },
      );
      setProposals(data);
    } catch {
      setError("Could not load action proposals.");
    }
    try {
      const state = await fetchMissionFocus();
      setMissionFocusPins(state.active_pins ?? []);
    } catch {
      setMissionFocusPins([]);
    }
  }, [statusFilter]);

  useEffect(() => {
    refresh();
  }, [refresh]);

  async function handleApprove(proposal: ActionProposal) {
    setBusyId(proposal.id);
    setError(null);
    try {
      await approveActionProposal(proposal.id, proposal.payload_digest);
      await refresh();
    } catch {
      setError("Could not approve this action.");
    } finally {
      setBusyId(null);
    }
  }

  async function handleDeny(proposal: ActionProposal) {
    setBusyId(proposal.id);
    setError(null);
    try {
      await denyActionProposal(proposal.id);
      await refresh();
    } catch {
      setError("Could not deny this action.");
    } finally {
      setBusyId(null);
    }
  }

  async function handleExecute(proposal: ActionProposal) {
    if (!proposal.confirmation_token) return;
    setBusyId(proposal.id);
    setError(null);
    try {
      await executeActionProposal(proposal.id, proposal.confirmation_token);
      await refresh();
    } catch {
      setError("Could not execute this action — the confirmation may have expired or already been used.");
    } finally {
      setBusyId(null);
    }
  }

  async function handleToggleHistory(proposal: ActionProposal) {
    if (expandedId === proposal.id) {
      setExpandedId(null);
      return;
    }
    if (!auditEvents[proposal.id]) {
      try {
        const detail = await getActionProposal(proposal.id);
        setAuditEvents((prev) => ({ ...prev, [proposal.id]: detail.audit_events }));
      } catch {
        setError("Could not load audit history for this action.");
        return;
      }
    }
    setExpandedId(proposal.id);
  }

  const pending = proposals.filter((p) => PENDING_STATUSES.includes(p.status));
  const settled = proposals.filter((p) => !PENDING_STATUSES.includes(p.status));

  function renderProposal(proposal: ActionProposal) {
    const rowTone =
      proposal.status === "proposed" ? "is-pending" : proposal.status === "approved" ? "is-approved" : "is-settled";
    return (
      <li key={proposal.id} className={`memory-card queue-item ${rowTone}`}>
        <p>
          <strong>{proposal.capability_id}</strong> · <StatusChip label={proposal.status} tone={STATUS_TONE[proposal.status]} />
          {proposal.domain_id && <> · domain-scoped</>}
        </p>

        <div className="ledger" style={{ margin: "0.4rem 0" }}>
          <div className="ledger-row">
            <span className="ledger-row-meta">Effect</span>
            <span className="ledger-row-main">{proposal.expected_effect}</span>
          </div>
          <div className="ledger-row">
            <span className="ledger-row-meta">Reason</span>
            <span className="ledger-row-main message-content">{proposal.reason}</span>
          </div>
          <div className="ledger-row">
            <span className="ledger-row-meta">Source</span>
            <span className="ledger-row-main message-content">{proposal.source}</span>
          </div>
        </div>

        <TechnicalDetails summary="Arguments">
          <pre>{JSON.stringify(proposal.arguments, null, 2)}</pre>
        </TechnicalDetails>

        {proposal.error_summary && <p className="error-banner">{proposal.error_summary}</p>}

        <div className="message-form-actions">
          {proposal.status === "proposed" && (
            <>
              <button
                type="button"
                className="primary"
                disabled={busyId === proposal.id}
                onClick={() => handleApprove(proposal)}
              >
                Approve
              </button>
              <button
                type="button"
                className="danger"
                disabled={busyId === proposal.id}
                onClick={() => handleDeny(proposal)}
              >
                Deny
              </button>
            </>
          )}
          {proposal.status === "approved" && (
            <button
              type="button"
              className="primary"
              disabled={busyId === proposal.id}
              onClick={() => handleExecute(proposal)}
            >
              Execute
            </button>
          )}
          <button type="button" onClick={() => handleToggleHistory(proposal)}>
            {expandedId === proposal.id ? "Hide audit history" : "Audit history"}
          </button>
          {MISSION_FOCUS_ELIGIBLE_STATUSES.includes(proposal.status) && (
            <AddToMissionFocusButton
              sourceType="action_proposal"
              sourceId={proposal.id}
              existingPin={missionFocusPins.find((p) => p.source_type === "action_proposal" && p.source_id === proposal.id)}
              onChanged={refresh}
            />
          )}
        </div>
        {expandedId === proposal.id && auditEvents[proposal.id] && (
          <ul className="timeline" style={{ marginTop: "0.6rem" }}>
            {auditEvents[proposal.id].map((event) => (
              <li key={event.id} className={`timeline-item tone-${TIMELINE_TONE[event.event_type] ?? "neutral"}`}>
                {formatDateTime(event.created_at)} — {event.event_type}
                {event.detail ? `: ${event.detail}` : ""}
              </li>
            ))}
          </ul>
        )}
      </li>
    );
  }

  return (
    <div className="domain-view">
      <button type="button" className="back-button" onClick={onBack}>
        ← Back to Jarvis
      </button>

      <ConsoleHeader
        indicator={<MiniCoreIndicator active={pending.some((p) => p.status === "executing")} />}
        eyebrow="Centre"
        title="Actions Centre"
        description="Every mutation Jarvis itself proposes — never one you make directly through the UI — appears here for review, approval, and audit. Nothing executes without your explicit approval of the exact proposed action."
        meta={
          proposals.length > 0 ? (
            <span>
              {pending.length} pending · {settled.length} resolved
            </span>
          ) : undefined
        }
      />

      {error && (
        <p className="error-banner" role="alert">
          {error}
        </p>
      )}

      <section aria-label="Filter by status">
        <div className="tab-row">
          {STATUS_FILTERS.map((s) => (
            <label key={s}>
              <input
                type="radio"
                name="status-filter"
                checked={statusFilter === s}
                onChange={() => setStatusFilter(s)}
              />
              {s}
            </label>
          ))}
        </div>
      </section>

      <ConsoleModule title="Pending review" ariaLabel="Action proposals" live={pending.length > 0}>
        <ul className="memory-list">
          {pending.map((proposal) => renderProposal(proposal))}
          {pending.length === 0 && <li className="empty-hint">No proposals awaiting review.</li>}
        </ul>
      </ConsoleModule>

      {(statusFilter !== "all" || settled.length > 0) && (
        <ConsoleModule title="History" ariaLabel="Action history">
          <ul className="memory-list">
            {settled.map((proposal) => renderProposal(proposal))}
            {settled.length === 0 && <li className="empty-hint">No resolved proposals in this filter.</li>}
          </ul>
        </ConsoleModule>
      )}
    </div>
  );
}

export default ActionsCentre;
