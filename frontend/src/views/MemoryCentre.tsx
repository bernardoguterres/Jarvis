import { Fragment, useEffect, useState, type FormEvent } from "react";
import {
  createMemory,
  editMemory,
  listMemories,
  searchMemories,
  type MemoryItem,
} from "../api";
import MemoryItemCard from "../components/MemoryItemCard";
import { ConsoleHeader, ConsoleModule, MiniCoreIndicator } from "../components/console/Console";

interface MemoryCentreProps {
  onBack: () => void;
}

const ONBOARDING_FIELDS: Array<{ title: string; kind: MemoryItem["kind"]; label: string; placeholder: string }> = [
  { title: "Preferred name", kind: "identity", label: "Preferred name", placeholder: "e.g. Bernardo" },
  {
    title: "How Jarvis should address Bernardo",
    kind: "identity",
    label: "How should Jarvis address you?",
    placeholder: "e.g. first name, casually",
  },
  {
    title: "Preferred response style",
    kind: "preference",
    label: "Preferred response style",
    placeholder: "e.g. concise and direct",
  },
  {
    title: "Current life stage",
    kind: "fact",
    label: "Current life stage",
    placeholder: "e.g. final year at UCL",
  },
  {
    title: "High-level priorities",
    kind: "goal",
    label: "High-level priorities",
    placeholder: "e.g. finish degree, ship Jarvis, stay healthy",
  },
];

function MemoryCentre({ onBack }: MemoryCentreProps) {
  const [globalMemories, setGlobalMemories] = useState<MemoryItem[]>([]);
  const [onboardingDrafts, setOnboardingDrafts] = useState<Record<string, string>>({});
  const [newTitle, setNewTitle] = useState("");
  const [newContent, setNewContent] = useState("");
  const [newKind, setNewKind] = useState<MemoryItem["kind"]>("fact");
  const [searchQuery, setSearchQuery] = useState("");
  const [searchResults, setSearchResults] = useState<MemoryItem[] | null>(null);
  const [error, setError] = useState<string | null>(null);

  async function refresh() {
    try {
      const memories = await listMemories({ scope: "global" });
      setGlobalMemories(memories);
      const drafts: Record<string, string> = {};
      for (const field of ONBOARDING_FIELDS) {
        const existing = memories.find((m) => m.title === field.title);
        if (existing) {
          drafts[field.title] = "";
        }
      }
      setOnboardingDrafts((prev) => ({ ...drafts, ...prev }));
    } catch {
      setError("Could not load global memories.");
    }
  }

  useEffect(() => {
    refresh();
  }, []);

  async function handleSaveOnboardingField(field: (typeof ONBOARDING_FIELDS)[number]) {
    const content = onboardingDrafts[field.title]?.trim();
    if (!content) return;
    setError(null);
    try {
      const existing = globalMemories.find((m) => m.title === field.title);
      if (existing) {
        await editMemory(existing.id, { content, change_reason: "onboarding update" });
      } else {
        await createMemory({
          scope: "global",
          kind: field.kind,
          title: field.title,
          content,
          source_note: "onboarding",
        });
      }
      await refresh();
    } catch {
      setError(`Could not save "${field.label}".`);
    }
  }

  async function handleCreateMemory(event: FormEvent) {
    event.preventDefault();
    if (!newTitle.trim() || !newContent.trim()) return;
    setError(null);
    try {
      await createMemory({
        scope: "global",
        kind: newKind,
        title: newTitle.trim(),
        content: newContent.trim(),
      });
      setNewTitle("");
      setNewContent("");
      await refresh();
    } catch {
      setError("Could not create memory.");
    }
  }

  async function handleSearch(event: FormEvent) {
    event.preventDefault();
    if (!searchQuery.trim()) {
      setSearchResults(null);
      return;
    }
    try {
      const results = await searchMemories(searchQuery.trim());
      setSearchResults(results);
    } catch {
      setError("Search failed.");
    }
  }

  const displayedMemories = searchResults ?? globalMemories;

  return (
    <div className="domain-view">
      <button type="button" className="back-button" onClick={onBack}>
        ← Back to Jarvis
      </button>

      <ConsoleHeader
        indicator={<MiniCoreIndicator />}
        eyebrow="Centre"
        title="Memory Centre"
        description="Global profile memories, stored only in Jarvis's local database — never in Hermes, never sent to an embedding API, and never tied to a specific model. Changing models later never loses this memory."
        meta={
          <span>
            {globalMemories.length} global memor{globalMemories.length === 1 ? "y" : "ies"} · domain-specific
            memories live in each domain's own conversation view
          </span>
        }
      />

      {error && (
        <p className="error-banner" role="alert">
          {error}
        </p>
      )}

      <ConsoleModule title="Identity & preferences" ariaLabel="Onboarding">
        <p className="notice">
          Nothing here is filled in automatically. Confirm what you want Jarvis to actually
          remember — this never ingests files or past conversations on its own.
        </p>
        <div className="identity-grid">
          {ONBOARDING_FIELDS.map((field) => {
            const existing = globalMemories.find((m) => m.title === field.title);
            return (
              <Fragment key={field.title}>
                <label htmlFor={`onboarding-${field.title}`} className="identity-grid-label">
                  {field.label}
                  {existing && <span className="identity-grid-current">Saved</span>}
                </label>
                <input
                  id={`onboarding-${field.title}`}
                  type="text"
                  placeholder={field.placeholder}
                  value={onboardingDrafts[field.title] ?? ""}
                  onChange={(e) =>
                    setOnboardingDrafts((prev) => ({ ...prev, [field.title]: e.target.value }))
                  }
                />
                <button type="button" className="action-note" onClick={() => handleSaveOnboardingField(field)}>
                  Save
                </button>
              </Fragment>
            );
          })}
        </div>
      </ConsoleModule>

      <ConsoleModule title="Search" ariaLabel="Search global memories">
        <form onSubmit={handleSearch} className="message-form-actions">
          <input
            type="text"
            placeholder="Search memories…"
            value={searchQuery}
            onChange={(e) => setSearchQuery(e.target.value)}
          />
          <button type="submit" className="primary">
            Search
          </button>
          {searchResults && (
            <button type="button" onClick={() => setSearchResults(null)}>
              Clear
            </button>
          )}
        </form>
      </ConsoleModule>

      <ConsoleModule title="Add a global memory" ariaLabel="Create global memory">
        <form onSubmit={handleCreateMemory} className="memory-create-form">
          <input
            type="text"
            placeholder="Title"
            value={newTitle}
            onChange={(e) => setNewTitle(e.target.value)}
          />
          <select aria-label="Memory kind" value={newKind} onChange={(e) => setNewKind(e.target.value as MemoryItem["kind"])}>
            <option value="identity">identity</option>
            <option value="preference">preference</option>
            <option value="fact">fact</option>
            <option value="goal">goal</option>
            <option value="constraint">constraint</option>
            <option value="decision">decision</option>
          </select>
          <textarea
            placeholder="Content"
            value={newContent}
            onChange={(e) => setNewContent(e.target.value)}
          />
          <button type="submit" className="primary">
            Remember
          </button>
        </form>
      </ConsoleModule>

      <ConsoleModule
        title={searchResults ? "Search results" : "Global memories"}
        ariaLabel="Global memories list"
      >
        <ul className="memory-list">
          {displayedMemories.map((memory) => (
            <MemoryItemCard key={memory.id} memory={memory} onChanged={refresh} />
          ))}
          {displayedMemories.length === 0 && <li className="empty-hint">No global memories yet.</li>}
        </ul>
      </ConsoleModule>
    </div>
  );
}

export default MemoryCentre;
