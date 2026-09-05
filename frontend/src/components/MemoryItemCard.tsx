import { useState } from "react";
import {
  archiveMemory,
  editMemory,
  getMemory,
  permanentlyDeleteMemory,
  unarchiveMemory,
  type MemoryItem,
  type MemoryVersion,
} from "../api";
import StatusChip, { type ChipTone } from "./StatusChip";
import { formatDateTime } from "../formatDateTime";

const MEMORY_STATUS_TONE: Record<MemoryItem["status"], ChipTone> = {
  active: "ok",
  archived: "neutral",
  deleted: "error",
};

interface MemoryItemCardProps {
  memory: MemoryItem;
  onChanged: () => void;
}

function MemoryItemCard({ memory, onChanged }: MemoryItemCardProps) {
  const [showHistory, setShowHistory] = useState(false);
  const [versions, setVersions] = useState<MemoryVersion[] | null>(null);
  const [currentContent, setCurrentContent] = useState<string | null>(null);
  const [editing, setEditing] = useState(false);
  const [draftContent, setDraftContent] = useState("");
  const [deleting, setDeleting] = useState(false);
  const [confirmTitle, setConfirmTitle] = useState("");
  const [error, setError] = useState<string | null>(null);

  async function loadHistory() {
    const detail = await getMemory(memory.id);
    setVersions(detail.versions);
    setCurrentContent(detail.current_content);
  }

  async function handleToggleHistory() {
    if (!showHistory) await loadHistory();
    setShowHistory(!showHistory);
  }

  async function handleStartEdit() {
    if (currentContent === null) await loadHistory();
    setDraftContent(currentContent ?? "");
    setEditing(true);
  }

  async function handleSaveEdit() {
    setError(null);
    try {
      await editMemory(memory.id, { content: draftContent });
      setEditing(false);
      await loadHistory();
      onChanged();
    } catch {
      setError("Could not save the edit.");
    }
  }

  async function handleArchiveToggle() {
    setError(null);
    try {
      if (memory.status === "archived") {
        await unarchiveMemory(memory.id);
      } else {
        await archiveMemory(memory.id);
      }
      onChanged();
    } catch {
      setError("Could not update this memory's status.");
    }
  }

  async function handlePermanentDelete() {
    setError(null);
    try {
      await permanentlyDeleteMemory(memory.id, confirmTitle);
      onChanged();
    } catch {
      setError("Confirmation text did not match this memory's exact title.");
    }
  }

  return (
    <li className="memory-card">
      <div className="memory-card-header">
        <span className="memory-kind">{memory.kind}</span>
        <strong>{memory.title}</strong>
        {memory.sensitivity === "sensitive" && <span className="sensitive-tag">sensitive</span>}
        <span className="memory-status">
          <StatusChip label={memory.status} tone={MEMORY_STATUS_TONE[memory.status]} />
        </span>
      </div>

      {error && (
        <p className="error-banner" role="alert">
          {error}
        </p>
      )}

      {editing ? (
        <div className="memory-edit-form">
          <textarea
            value={draftContent}
            onChange={(e) => setDraftContent(e.target.value)}
            aria-label={`Edit content for ${memory.title}`}
          />
          <div className="memory-actions">
            <button type="button" className="primary" onClick={handleSaveEdit}>
              Save new version
            </button>
            <button type="button" onClick={() => setEditing(false)}>
              Cancel
            </button>
          </div>
        </div>
      ) : (
        <div className="memory-actions">
          <button type="button" onClick={handleStartEdit}>
            Edit
          </button>
          <button type="button" onClick={handleArchiveToggle}>
            {memory.status === "archived" ? "Unarchive" : "Archive"}
          </button>
          <button type="button" onClick={handleToggleHistory}>
            {showHistory ? "Hide history" : "Version history"}
          </button>
          <button type="button" onClick={() => setDeleting(!deleting)}>
            Delete permanently
          </button>
        </div>
      )}

      {deleting && (
        <div className="memory-delete-confirm">
          <p>
            This is irreversible. Type the exact title (<strong>{memory.title}</strong>) to
            confirm permanent deletion. A rollback backup will be created first.
          </p>
          <input
            type="text"
            value={confirmTitle}
            onChange={(e) => setConfirmTitle(e.target.value)}
            aria-label="Type the exact memory title to confirm deletion"
          />
          <button type="button" className="primary" onClick={handlePermanentDelete}>
            Confirm permanent deletion
          </button>
        </div>
      )}

      {showHistory && versions && (
        <ul className="memory-version-history">
          {versions.map((v) => (
            <li key={v.id}>
              v{v.version_number} ({formatDateTime(v.created_at)}): {v.content}
            </li>
          ))}
        </ul>
      )}
    </li>
  );
}

export default MemoryItemCard;
