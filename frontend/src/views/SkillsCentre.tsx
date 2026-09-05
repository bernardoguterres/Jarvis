import { useCallback, useEffect, useState, type FormEvent } from "react";
import {
  activateSkill,
  archiveSkill,
  createSkill,
  editSkill,
  fetchDomains,
  getSkill,
  invokeSkill,
  listSkills,
  type ActionProposal,
  type Domain,
  type Skill,
  type SkillStatus,
  type SkillVersion,
} from "../api";
import StatusChip, { type ChipTone } from "../components/StatusChip";
import { ConsoleHeader, ConsoleModule, MiniCoreIndicator, TechnicalDetails } from "../components/console/Console";
import { formatDateTime } from "../formatDateTime";

const SKILL_STATUS_TONE: Record<SkillStatus, ChipTone> = {
  draft: "warn",
  active: "ok",
  archived: "neutral",
};

interface SkillsCentreProps {
  onBack: () => void;
}

const STATUS_TABS: SkillStatus[] = ["draft", "active", "archived"];

function SkillsCentre({ onBack }: SkillsCentreProps) {
  const [skills, setSkills] = useState<Skill[]>([]);
  const [domains, setDomains] = useState<Domain[]>([]);
  const [statusTab, setStatusTab] = useState<SkillStatus>("draft");
  const [error, setError] = useState<string | null>(null);
  const [selectedSkillId, setSelectedSkillId] = useState<string | null>(null);
  const [versions, setVersions] = useState<SkillVersion[]>([]);
  const [editing, setEditing] = useState(false);
  const [editSteps, setEditSteps] = useState("");
  const [editReason, setEditReason] = useState("");
  const [invokeArgsText, setInvokeArgsText] = useState("");
  const [invokeResult, setInvokeResult] = useState<ActionProposal[] | null>(null);

  // Create-draft form state
  const [newSlug, setNewSlug] = useState("");
  const [newName, setNewName] = useState("");
  const [newDescription, setNewDescription] = useState("");
  const [newDomainId, setNewDomainId] = useState("");
  const [newStepsText, setNewStepsText] = useState(
    '[{"capability_id": "memory.create", "description": "Log a fact"}]',
  );

  const refreshSkills = useCallback(async () => {
    try {
      const data = await listSkills({ status: statusTab });
      setSkills(data);
    } catch {
      setError("Could not load skills.");
    }
  }, [statusTab]);

  useEffect(() => {
    refreshSkills();
  }, [refreshSkills]);

  useEffect(() => {
    fetchDomains()
      .then(setDomains)
      .catch(() => setError("Could not load domains."));
  }, []);

  async function openSkill(skillId: string) {
    setSelectedSkillId(skillId);
    setEditing(false);
    setInvokeResult(null);
    setInvokeArgsText("");
    try {
      const detail = await getSkill(skillId);
      setVersions(detail.versions);
    } catch {
      setError("Could not load this skill's version history.");
    }
  }

  const selectedSkill = skills.find((s) => s.id === selectedSkillId) ?? null;
  const currentVersion = versions.find((v) => v.id === selectedSkill?.current_version_id) ?? null;

  async function handleCreate(event: FormEvent) {
    event.preventDefault();
    setError(null);
    try {
      const steps = JSON.parse(newStepsText);
      await createSkill({
        slug: newSlug,
        name: newName,
        description: newDescription,
        domain_id: newDomainId || null,
        workflow_steps: steps,
      });
      setNewSlug("");
      setNewName("");
      setNewDescription("");
      setNewDomainId("");
      await refreshSkills();
    } catch {
      setError("Could not create this skill — check the workflow steps are valid JSON naming an allowed capability.");
    }
  }

  async function handleActivate(skillId: string) {
    setError(null);
    try {
      await activateSkill(skillId);
      await refreshSkills();
      if (selectedSkillId === skillId) await openSkill(skillId);
    } catch {
      setError("Could not activate this skill.");
    }
  }

  async function handleArchive(skillId: string) {
    setError(null);
    try {
      await archiveSkill(skillId);
      await refreshSkills();
    } catch {
      setError("Could not archive this skill.");
    }
  }

  function startEditing() {
    if (!currentVersion) return;
    setEditSteps(JSON.stringify(currentVersion.workflow_steps, null, 2));
    setEditReason("");
    setEditing(true);
  }

  async function handleSaveEdit(event: FormEvent) {
    event.preventDefault();
    if (!selectedSkillId) return;
    setError(null);
    try {
      const steps = JSON.parse(editSteps);
      await editSkill(selectedSkillId, { workflow_steps: steps, change_reason: editReason || undefined });
      setEditing(false);
      await refreshSkills();
      await openSkill(selectedSkillId);
    } catch {
      setError("Could not save this edit — check the workflow steps are valid JSON.");
    }
  }

  async function handleInvoke(event: FormEvent) {
    event.preventDefault();
    if (!selectedSkillId) return;
    setError(null);
    try {
      const stepArguments = JSON.parse(invokeArgsText || "[]");
      const result = await invokeSkill(selectedSkillId, { step_arguments: stepArguments });
      setInvokeResult(result.proposals);
    } catch {
      setError("Could not invoke this skill — check the step arguments are valid JSON and match the required steps.");
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
        title="Skills Centre"
        description="Declarative workflows only — never arbitrary code. A new skill always starts as a draft; activating or modifying one always requires this explicit review."
        meta={
          skills.length > 0 ? (
            <span>
              {skills.length} {statusTab}
            </span>
          ) : undefined
        }
      />

      {error && (
        <p className="error-banner" role="alert">
          {error}
        </p>
      )}

      <details className="builder-surface">
        <summary>New skill — builder</summary>
        <div className="builder-surface-body">
          <section aria-label="Create a draft skill">
            <form className="memory-create-form" onSubmit={handleCreate}>
              <input placeholder="slug (e.g. my-skill)" value={newSlug} onChange={(e) => setNewSlug(e.target.value)} />
              <input placeholder="Name" value={newName} onChange={(e) => setNewName(e.target.value)} />
              <textarea
                placeholder="Description"
                value={newDescription}
                onChange={(e) => setNewDescription(e.target.value)}
              />
              <select aria-label="Domain for new skill" value={newDomainId} onChange={(e) => setNewDomainId(e.target.value)}>
                <option value="">No domain (global)</option>
                {domains.map((d) => (
                  <option key={d.id} value={d.id}>
                    {d.name}
                  </option>
                ))}
              </select>
              <textarea
                placeholder="Workflow steps (JSON array)"
                value={newStepsText}
                onChange={(e) => setNewStepsText(e.target.value)}
              />
              <button type="submit" className="primary">
                Create draft
              </button>
            </form>
          </section>
        </div>
      </details>

      <ConsoleModule title="Registry" ariaLabel="Skills by status">
        <div className="tab-row">
          {STATUS_TABS.map((tab) => (
            <label key={tab}>
              <input
                type="radio"
                name="skill-status-tab"
                checked={statusTab === tab}
                onChange={() => setStatusTab(tab)}
              />
              {tab}
            </label>
          ))}
        </div>
        <div className="ledger">
          {skills.map((skill) => (
            <div key={skill.id} className="ledger-row" style={{ flexWrap: "wrap" }}>
              <div className="ledger-row-main">
                <strong>{skill.name}</strong>
                <span className="ledger-row-meta">({skill.slug})</span>
                <StatusChip label={skill.status} tone={SKILL_STATUS_TONE[skill.status]} />
                {skill.created_by === "jarvis" && <span className="ledger-row-meta">suggested by Jarvis</span>}
              </div>
              <div className="ledger-row-actions">
                <button type="button" onClick={() => openSkill(skill.id)}>
                  Review
                </button>
                {skill.status !== "active" && (
                  <button type="button" onClick={() => handleActivate(skill.id)}>
                    Activate
                  </button>
                )}
                {skill.status !== "archived" && (
                  <button type="button" onClick={() => handleArchive(skill.id)}>
                    Archive
                  </button>
                )}
              </div>
            </div>
          ))}
          {skills.length === 0 && <p className="ledger-empty">No {statusTab} skills.</p>}
        </div>
      </ConsoleModule>

      {selectedSkill && (
        <ConsoleModule title={selectedSkill.name} ariaLabel="Skill detail" live={selectedSkill.status === "active"}>
          <p className="message-content">{selectedSkill.description}</p>
          <p>
            Status: <StatusChip label={selectedSkill.status} tone={SKILL_STATUS_TONE[selectedSkill.status]} /> · Version{" "}
            {currentVersion?.version_number ?? "?"}
          </p>

          {editing ? (
            <form onSubmit={handleSaveEdit}>
              <textarea value={editSteps} onChange={(e) => setEditSteps(e.target.value)} />
              <input
                placeholder="Change reason (optional)"
                value={editReason}
                onChange={(e) => setEditReason(e.target.value)}
              />
              <div className="message-form-actions">
                <button type="submit" className="primary">
                  Save as new version
                </button>
                <button type="button" onClick={() => setEditing(false)}>
                  Cancel
                </button>
              </div>
            </form>
          ) : (
            <>
              <ul className="timeline">
                {(currentVersion?.workflow_steps ?? []).map((step, i) => (
                  <li key={i} className="timeline-item tone-neutral">
                    <strong>{step.capability_id}</strong> — {step.description}
                  </li>
                ))}
                {(currentVersion?.workflow_steps ?? []).length === 0 && (
                  <li className="timeline-empty">No workflow steps.</li>
                )}
              </ul>
              <TechnicalDetails summary="Raw workflow JSON">
                <pre>{JSON.stringify(currentVersion?.workflow_steps ?? [], null, 2)}</pre>
              </TechnicalDetails>
              <button type="button" onClick={startEditing}>
                Edit (new version)
              </button>
            </>
          )}

          <TechnicalDetails summary="Version history">
            <ul>
              {versions.map((v) => (
                <li key={v.id}>
                  v{v.version_number}
                  {v.change_reason ? ` — ${v.change_reason}` : ""} ({formatDateTime(v.created_at)})
                </li>
              ))}
            </ul>
          </TechnicalDetails>

          {selectedSkill.status === "active" && (
            <>
              <h3>Invoke this skill</h3>
              <form onSubmit={handleInvoke}>
                <textarea
                  placeholder='Step arguments (JSON array, one object per workflow step)'
                  value={invokeArgsText}
                  onChange={(e) => setInvokeArgsText(e.target.value)}
                />
                <button type="submit" className="primary">
                  Invoke → propose actions
                </button>
              </form>
              {invokeResult && (
                <div className="context-used-panel">
                  <p>Created {invokeResult.length} action proposal(s) — review them in the Actions Centre:</p>
                  <ul>
                    {invokeResult.map((p) => (
                      <li key={p.id}>
                        {p.capability_id} — {p.status}
                      </li>
                    ))}
                  </ul>
                </div>
              )}
            </>
          )}
        </ConsoleModule>
      )}
    </div>
  );
}

export default SkillsCentre;
