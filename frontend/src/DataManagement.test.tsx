import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import DataManagement from "./views/DataManagement";
import * as api from "./api";

beforeEach(() => {
  vi.restoreAllMocks();
});

afterEach(() => {
  vi.restoreAllMocks();
});

function baseMocks() {
  vi.spyOn(api, "listExports").mockResolvedValue([]);
  vi.spyOn(api, "fetchLatestBackup").mockResolvedValue({
    latest: null,
    by_category: { daily: null, weekly: null, monthly: null },
  });
  vi.spyOn(api, "fetchDataDir").mockResolvedValue({ path: "/Users/bernardo/JarvisData" });
}

describe("DataManagement", () => {
  it("explains where data is stored and that secrets are excluded", async () => {
    baseMocks();
    render(<DataManagement onBack={() => {}} />);

    expect(await screen.findByText(/JARVIS_DATA_DIR/i)).toBeInTheDocument();
    expect(screen.getByText(/Secrets are always excluded/i)).toBeInTheDocument();
    expect(screen.getByText(/do not protect you from losing the laptop/i)).toBeInTheDocument();
  });

  it("runs an export and shows the resulting filename and download link", async () => {
    baseMocks();
    const user = userEvent.setup();

    vi.spyOn(api, "createExport").mockResolvedValue({
      filename: "jarvis-export-20260101-120000.zip",
      created_at_utc: "2026-01-01T12:00:00+00:00",
      size_bytes: 4096,
      included_components: ["database"],
    });

    render(<DataManagement onBack={() => {}} />);

    await user.click(screen.getByRole("button", { name: /export jarvis/i }));

    expect(await screen.findByText(/jarvis-export-20260101-120000\.zip/)).toBeInTheDocument();
    expect(screen.getByRole("link", { name: /download/i })).toBeInTheDocument();
  });

  it("shows an error state when export fails", async () => {
    baseMocks();
    const user = userEvent.setup();
    vi.spyOn(api, "createExport").mockRejectedValue(new Error("Export failed: disk full"));

    render(<DataManagement onBack={() => {}} />);
    await user.click(screen.getByRole("button", { name: /export jarvis/i }));

    expect(await screen.findByText(/disk full/i)).toBeInTheDocument();
  });

  it("creates a manual backup", async () => {
    baseMocks();
    const user = userEvent.setup();
    vi.spyOn(api, "createBackup").mockResolvedValue({
      category: "daily",
      filename: "jarvis-backup-daily-20260101-120000.sqlite",
      created_at_utc: "2026-01-01T12:00:00+00:00",
      size_bytes: 2048,
      sha256: "abc123",
    });

    render(<DataManagement onBack={() => {}} />);
    await user.click(screen.getByRole("button", { name: /create manual backup/i }));

    expect(await screen.findByRole("button", { name: /create manual backup/i })).toBeEnabled();
  });

  it("shows the resolved data folder path from the backend", async () => {
    baseMocks();
    render(<DataManagement onBack={() => {}} />);

    expect(await screen.findByText(/\/Users\/bernardo\/JarvisData/)).toBeInTheDocument();
  });

  it("requires explicit acknowledgement before a restore can run", async () => {
    baseMocks();
    const user = userEvent.setup();
    vi.spyOn(api, "validateImportArchive").mockResolvedValue({
      ok: true,
      errors: [],
      manifest: { export_format_version: "1.0", schema_revision: "0018" },
    });
    const restoreSpy = vi.spyOn(api, "restoreImport");

    render(<DataManagement onBack={() => {}} />);

    const file = new File(["zip-bytes"], "export.zip", { type: "application/zip" });
    const input = screen.getByLabelText(/choose an export \.zip to restore/i);
    await user.upload(input, file);

    const restoreButton = await screen.findByRole("button", { name: /restore now/i });
    expect(restoreButton).toBeDisabled();
    expect(restoreSpy).not.toHaveBeenCalled();

    await user.click(screen.getByRole("checkbox"));
    expect(restoreButton).toBeEnabled();
  });

  it("restores after confirmation and reports the result", async () => {
    baseMocks();
    const user = userEvent.setup();
    vi.spyOn(api, "validateImportArchive").mockResolvedValue({
      ok: true,
      errors: [],
      manifest: { export_format_version: "1.0" },
    });
    vi.spyOn(api, "restoreImport").mockResolvedValue({
      domains_restored: 6,
      conversations_restored: 2,
      messages_restored: 4,
      documents_restored: 1,
      domain_summaries_restored: 6,
      skills_restored: 1,
      schema_revision_before: "0017",
      schema_revision_after: "0018",
      rollback_dir: "/Users/bernardo/JarvisData.rollback-20260101-120000",
      target_dir: "/Users/bernardo/JarvisData",
      hermes_profile_export_path: null,
      hermes_profile_import_command: null,
    });

    render(<DataManagement onBack={() => {}} />);

    const file = new File(["zip-bytes"], "export.zip", { type: "application/zip" });
    await user.upload(screen.getByLabelText(/choose an export \.zip to restore/i), file);
    await user.click(await screen.findByRole("checkbox"));
    await user.click(screen.getByRole("button", { name: /restore now/i }));

    expect(await screen.findByText(/restored 6 domain\(s\)/i)).toBeInTheDocument();
    expect(screen.getByText(/now disabled/i)).toBeInTheDocument();
  });

  it("shows a clear error and lets the user retry when the archive is invalid", async () => {
    baseMocks();
    const user = userEvent.setup();
    vi.spyOn(api, "validateImportArchive").mockResolvedValue({
      ok: false,
      errors: ["checksum mismatch"],
      manifest: null,
    });

    render(<DataManagement onBack={() => {}} />);

    const file = new File(["zip-bytes"], "export.zip", { type: "application/zip" });
    await user.upload(screen.getByLabelText(/choose an export \.zip to restore/i), file);

    expect(await screen.findByText(/checksum mismatch/i)).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /restore now/i })).not.toBeInTheDocument();
  });

  it("validates an uploaded archive without restoring it", async () => {
    baseMocks();
    const user = userEvent.setup();
    vi.spyOn(api, "validateImportArchive").mockResolvedValue({
      ok: true,
      errors: [],
      manifest: { export_format_version: "1.0" },
    });

    render(<DataManagement onBack={() => {}} />);

    const file = new File(["zip-bytes"], "export.zip", { type: "application/zip" });
    const input = screen.getByLabelText(/choose an export \.zip to validate/i);
    await user.upload(input, file);

    expect(await screen.findByText(/this archive is valid/i)).toBeInTheDocument();
  });

  it("returns to the home view", async () => {
    baseMocks();
    const user = userEvent.setup();
    const onBack = vi.fn();

    render(<DataManagement onBack={onBack} />);
    await user.click(screen.getByRole("button", { name: /back to jarvis/i }));

    expect(onBack).toHaveBeenCalled();
  });
});
