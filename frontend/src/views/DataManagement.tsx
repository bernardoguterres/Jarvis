import { useCallback, useEffect, useState, type ChangeEvent } from "react";
import {
  createBackup,
  createExport,
  exportDownloadUrl,
  fetchDataDir,
  fetchLatestBackup,
  listExports,
  restoreImport,
  validateImportArchive,
  type ExportInfo,
  type ExportListItem,
  type ImportValidationResult,
  type LatestBackupInfo,
  type RestoreResult,
} from "../api";
import { ConsoleHeader, ConsoleModule, MiniCoreIndicator } from "../components/console/Console";

interface DataManagementProps {
  onBack: () => void;
}

type ExportState = "idle" | "running" | "done" | "error";
type BackupState = "idle" | "running" | "done" | "error";
type ValidateState = "idle" | "running" | "done" | "error";
type RestoreState = "idle" | "validating" | "confirming" | "running" | "done" | "error";

function DataManagement({ onBack }: DataManagementProps) {
  const [exports, setExports] = useState<ExportListItem[]>([]);
  const [latestBackup, setLatestBackup] = useState<LatestBackupInfo | null>(null);
  const [dataDirPath, setDataDirPath] = useState<string | null>(null);

  const [exportState, setExportState] = useState<ExportState>("idle");
  const [lastExport, setLastExport] = useState<ExportInfo | null>(null);
  const [exportError, setExportError] = useState<string | null>(null);

  const [backupState, setBackupState] = useState<BackupState>("idle");
  const [backupError, setBackupError] = useState<string | null>(null);

  const [validateState, setValidateState] = useState<ValidateState>("idle");
  const [validateResult, setValidateResult] = useState<ImportValidationResult | null>(null);

  const [restoreState, setRestoreState] = useState<RestoreState>("idle");
  const [restoreFile, setRestoreFile] = useState<File | null>(null);
  const [restoreValidation, setRestoreValidation] = useState<ImportValidationResult | null>(null);
  const [restoreResult, setRestoreResult] = useState<RestoreResult | null>(null);
  const [restoreError, setRestoreError] = useState<string | null>(null);
  const [restoreAcknowledged, setRestoreAcknowledged] = useState(false);

  const refresh = useCallback(async () => {
    try {
      const [exportList, backupInfo, dataDir] = await Promise.all([
        listExports(),
        fetchLatestBackup(),
        fetchDataDir(),
      ]);
      setExports(exportList);
      setLatestBackup(backupInfo);
      setDataDirPath(dataDir.path);
    } catch {
      // Surfaced already by the top-bar health indicator; this view just
      // shows what it last successfully loaded.
    }
  }, []);

  useEffect(() => {
    refresh();
  }, [refresh]);

  async function handleExport() {
    setExportState("running");
    setExportError(null);
    try {
      const result = await createExport();
      setLastExport(result);
      setExportState("done");
      await refresh();
    } catch (err) {
      setExportError(err instanceof Error ? err.message : "Export failed.");
      setExportState("error");
    }
  }

  async function handleBackup() {
    setBackupState("running");
    setBackupError(null);
    try {
      await createBackup("daily");
      setBackupState("done");
      await refresh();
    } catch (err) {
      setBackupError(err instanceof Error ? err.message : "Backup failed.");
      setBackupState("error");
    }
  }

  async function handleValidateFile(event: ChangeEvent<HTMLInputElement>) {
    const file = event.target.files?.[0];
    if (!file) return;

    setValidateState("running");
    setValidateResult(null);
    try {
      const result = await validateImportArchive(file);
      setValidateResult(result);
      setValidateState("done");
    } catch {
      setValidateState("error");
    } finally {
      event.target.value = "";
    }
  }

  async function handleRestoreFileChosen(event: ChangeEvent<HTMLInputElement>) {
    const file = event.target.files?.[0];
    event.target.value = "";
    if (!file) return;

    setRestoreFile(file);
    setRestoreResult(null);
    setRestoreError(null);
    setRestoreAcknowledged(false);
    setRestoreState("validating");
    try {
      const result = await validateImportArchive(file);
      setRestoreValidation(result);
      setRestoreState(result.ok ? "confirming" : "error");
      if (!result.ok) {
        setRestoreError(`This archive is invalid: ${result.errors.join("; ")}`);
      }
    } catch (err) {
      setRestoreState("error");
      setRestoreError(err instanceof Error ? err.message : "Could not validate this archive.");
    }
  }

  function cancelRestore() {
    setRestoreState("idle");
    setRestoreFile(null);
    setRestoreValidation(null);
    setRestoreAcknowledged(false);
    setRestoreError(null);
  }

  async function confirmRestore() {
    if (!restoreFile) return;
    setRestoreState("running");
    setRestoreError(null);
    try {
      const result = await restoreImport(restoreFile, true);
      setRestoreResult(result);
      setRestoreState("done");
      await refresh();
    } catch (err) {
      setRestoreState("error");
      setRestoreError(err instanceof Error ? err.message : "Restore failed.");
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
        title="Data Management"
        description="Export, back up, and understand where your Jarvis data lives."
      />

      <p className="vault-guarantee">
        <span aria-hidden="true">✓</span> Secrets are always excluded — API keys, <code>.env</code> files, and any
        credentials never leave this machine
      </p>

      <ConsoleModule title="Where your data lives" ariaLabel="Where your data lives">
        <div className="vault-tier">
          <span className="vault-tier-index">01</span>
          <p style={{ margin: 0 }}>
            Your personal data (database, documents, domain summaries, skills) lives outside
            this application's source code, in your configured <code>JARVIS_DATA_DIR</code>{" "}
            — on this Mac, <code>{dataDirPath ?? "~/JarvisData"}</code>. Jarvis.app itself
            contains only application code; every launch detects and reuses this exact folder in
            place, and rebuilding or replacing Jarvis.app never touches it. An export bundles
            everything schema-backed here — conversations, memories, structured records, Calendar
            and Health cache, Recall/Research/Decision Room data, routines, and more — into one
            portable archive.
          </p>
        </div>
        <div className="vault-tier">
          <span className="vault-tier-index">02</span>
          <p style={{ margin: 0 }}>
            <strong>Backups on this laptop do not protect you from losing the laptop.</strong>{" "}
            Periodically copy exports to an encrypted external drive or an encrypted Time Machine
            backup.
          </p>
        </div>
        <div className="vault-tier">
          <span className="vault-tier-index">03</span>
          <p style={{ margin: 0 }}>
            <strong>Moving to a new Mac:</strong> install Jarvis.app there, create an export here,
            copy the export file over, then use Restore below on the new Mac. "Reveal Jarvis Data
            Folder" is available from the Jarvis menu-bar icon.
          </p>
        </div>
      </ConsoleModule>

      <ConsoleModule title="Export" ariaLabel="Export" live={exportState === "running"}>
        <button type="button" className="primary" onClick={handleExport} disabled={exportState === "running"}>
          {exportState === "running" ? "Exporting…" : "Export Jarvis"}
        </button>

        {exportState === "done" && lastExport && (
          <p role="status">
            Created <strong>{lastExport.filename}</strong> at {lastExport.created_at_utc} (
            {lastExport.size_bytes} bytes).{" "}
            <a href={exportDownloadUrl(lastExport.filename)}>Download</a>
          </p>
        )}
        {exportState === "error" && (
          <p className="error-banner" role="alert">
            {exportError}
          </p>
        )}

        <h3>Previous exports</h3>
        <div className="ledger">
          {exports.map((item) => (
            <div key={item.filename} className="ledger-row">
              <span className="ledger-row-main">{item.filename}</span>
              <span className="ledger-row-meta">{item.size_bytes} bytes</span>
              <div className="ledger-row-actions">
                <a href={exportDownloadUrl(item.filename)}>Download</a>
              </div>
            </div>
          ))}
          {exports.length === 0 && <p className="ledger-empty">No exports yet.</p>}
        </div>
      </ConsoleModule>

      <ConsoleModule title="Backups" ariaLabel="Backups" live={backupState === "running"}>
        <button type="button" className="primary" onClick={handleBackup} disabled={backupState === "running"}>
          {backupState === "running" ? "Backing up…" : "Create manual backup"}
        </button>
        {backupState === "error" && (
          <p className="error-banner" role="alert">
            {backupError}
          </p>
        )}

        <div className="ledger" style={{ marginTop: "0.6rem" }}>
          <div className="ledger-row">
            <span className="ledger-row-meta">Latest backup</span>
            <span className="ledger-row-main">
              {latestBackup?.latest ? (
                <>
                  {latestBackup.latest.category as string} — {latestBackup.latest.filename as string} at{" "}
                  {latestBackup.latest.created_at_utc as string}
                </>
              ) : (
                "No backups yet."
              )}
            </span>
          </div>
        </div>
        <p className="notice">Retention target: 7 daily · 4 weekly · 12 monthly.</p>
      </ConsoleModule>

      <ConsoleModule
        title="Restore from Jarvis export"
        ariaLabel="Restore from Jarvis export"
        live={restoreState === "validating" || restoreState === "running"}
      >
        <p>
          Restoring <strong>replaces this machine's live Jarvis database</strong> — use this after
          installing Jarvis.app on a new Mac (an empty <code>~/JarvisData</code>), or to roll this
          Mac back to a previous export. Existing Calendar/Health connections, Hermes
          authentication, and every credential in Keychain are never touched by a restore — but
          integrations and all automatic schedules/routines are always force-disabled afterward
          until you review and re-enable them, exactly as the CLI restore path already does.
        </p>

        {restoreState === "idle" && (
          <>
            <label htmlFor="restore-archive-input">Choose an export .zip to restore</label>
            <input
              id="restore-archive-input"
              type="file"
              accept=".zip"
              onChange={handleRestoreFileChosen}
            />
          </>
        )}

        {restoreState === "validating" && <p>Validating archive…</p>}

        {restoreState === "confirming" && restoreFile && restoreValidation?.ok && (
          <div className="vault-tier">
            <p role="alert" className="error-banner">
              <strong>This will replace all data currently on this Mac</strong> with the contents
              of <strong>{restoreFile.name}</strong>
              {typeof restoreValidation.manifest?.schema_revision === "string"
                ? ` (schema ${restoreValidation.manifest.schema_revision})`
                : ""}
              . A rollback copy of the current data is kept automatically, but this action should
              not be taken lightly.
            </p>
            <label style={{ display: "flex", gap: "0.5rem", alignItems: "flex-start" }}>
              <input
                type="checkbox"
                checked={restoreAcknowledged}
                onChange={(e) => setRestoreAcknowledged(e.target.checked)}
              />
              I understand this replaces this Mac's current Jarvis data.
            </label>
            <div style={{ display: "flex", gap: "0.5rem", marginTop: "0.6rem" }}>
              <button
                type="button"
                className="primary"
                onClick={confirmRestore}
                disabled={!restoreAcknowledged}
              >
                Restore now
              </button>
              <button type="button" onClick={cancelRestore}>
                Cancel
              </button>
            </div>
          </div>
        )}

        {restoreState === "running" && <p>Restoring…</p>}

        {restoreState === "done" && restoreResult && (
          <p role="status">
            Restored {restoreResult.domains_restored} domain(s),{" "}
            {restoreResult.conversations_restored} conversation(s),{" "}
            {restoreResult.messages_restored} message(s), {restoreResult.documents_restored}{" "}
            document(s). Integrations and all schedules/routines are now disabled — review and
            re-enable them when ready.
          </p>
        )}

        {restoreState === "error" && (
          <>
            <p className="error-banner" role="alert">
              {restoreError}
            </p>
            <button type="button" onClick={cancelRestore}>
              Try a different file
            </button>
          </>
        )}
      </ConsoleModule>

      <ConsoleModule title="Validate an archive" ariaLabel="Validate an archive">
        <p>You can check whether an export archive is valid without restoring anything:</p>
        <label htmlFor="validate-archive-input">Choose an export .zip to validate</label>
        <input
          id="validate-archive-input"
          type="file"
          accept=".zip"
          onChange={handleValidateFile}
          disabled={validateState === "running"}
        />

        {validateState === "running" && <p>Validating…</p>}
        {validateState === "done" && validateResult && (
          <p role="status">
            {validateResult.ok
              ? "This archive is valid."
              : `This archive is invalid: ${validateResult.errors.join("; ")}`}
          </p>
        )}
        {validateState === "error" && (
          <p className="error-banner" role="alert">
            Could not validate this file.
          </p>
        )}
      </ConsoleModule>
    </div>
  );
}

export default DataManagement;
