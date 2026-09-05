export interface Domain {
  id: string;
  slug: string;
  name: string;
  description: string;
  created_at: string;
  updated_at: string;
}

export interface Conversation {
  id: string;
  // null means a general Jarvis conversation — not a seventh domain, just
  // the absence of one (see docs/DECISIONS.md, migration 0011).
  domain_id: string | null;
  title: string | null;
  created_at: string;
  updated_at: string;
  archived_at: string | null;
}

export interface Message {
  id: string;
  conversation_id: string;
  role: "user" | "assistant" | "system";
  content: string;
  created_at: string;
  model_used: string | null;
}

const API_BASE_URL: string =
  (import.meta.env.VITE_API_BASE_URL as string | undefined) ?? "http://127.0.0.1:8000";

class ApiError extends Error {
  status: number;

  constructor(status: number, message: string) {
    super(message);
    this.status = status;
  }
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(`${API_BASE_URL}${path}`, {
    headers: { "Content-Type": "application/json" },
    ...init,
  });

  if (!response.ok) {
    let detail = response.statusText;
    try {
      const body = await response.json();
      detail = body.detail ?? detail;
    } catch {
      // ignore body parse failure, fall back to statusText
    }
    throw new ApiError(response.status, detail);
  }

  return (await response.json()) as T;
}

export async function fetchHealth(): Promise<{ status: string }> {
  return request("/api/health");
}

export async function fetchDataDir(): Promise<{ path: string }> {
  return request("/api/data-dir");
}

export async function fetchDomains(): Promise<Domain[]> {
  return request("/api/domains");
}

export async function fetchConversations(slug: string): Promise<Conversation[]> {
  return request(`/api/domains/${slug}/conversations`);
}

export async function createConversation(
  slug: string,
  title?: string,
): Promise<Conversation> {
  return request(`/api/domains/${slug}/conversations`, {
    method: "POST",
    body: JSON.stringify({ title: title ?? null }),
  });
}

export async function fetchGeneralConversations(): Promise<Conversation[]> {
  return request("/api/general/conversations");
}

export async function createGeneralConversation(title?: string): Promise<Conversation> {
  return request("/api/general/conversations", {
    method: "POST",
    body: JSON.stringify({ title: title ?? null }),
  });
}

export async function fetchMessages(conversationId: string): Promise<Message[]> {
  return request(`/api/conversations/${conversationId}/messages`);
}

export async function createMessage(
  conversationId: string,
  content: string,
): Promise<Message> {
  return request(`/api/conversations/${conversationId}/messages`, {
    method: "POST",
    body: JSON.stringify({ role: "user", content }),
  });
}

export interface ExportInfo {
  filename: string;
  created_at_utc: string;
  size_bytes: number;
  included_components: string[];
}

export interface ExportListItem {
  filename: string;
  size_bytes: number;
  created_at_utc: string | null;
}

export type BackupCategory = "daily" | "weekly" | "monthly";

export interface BackupInfo {
  category: BackupCategory;
  filename: string;
  created_at_utc: string;
  size_bytes: number;
  sha256: string;
}

export interface LatestBackupInfo {
  latest: (BackupInfo & Record<string, unknown>) | null;
  by_category: Record<BackupCategory, (BackupInfo & Record<string, unknown>) | null>;
}

export interface ImportValidationResult {
  ok: boolean;
  errors: string[];
  manifest: Record<string, unknown> | null;
}

export async function createExport(): Promise<ExportInfo> {
  return request("/api/export", { method: "POST" });
}

export async function listExports(): Promise<ExportListItem[]> {
  return request("/api/exports");
}

export function exportDownloadUrl(filename: string): string {
  return `${API_BASE_URL}/api/exports/${encodeURIComponent(filename)}/download`;
}

export async function createBackup(category: BackupCategory = "daily"): Promise<BackupInfo> {
  return request(`/api/backups?category=${category}`, { method: "POST" });
}

export async function fetchLatestBackup(): Promise<LatestBackupInfo> {
  return request("/api/backups/latest");
}

export async function validateImportArchive(file: File): Promise<ImportValidationResult> {
  const formData = new FormData();
  formData.append("file", file);

  const response = await fetch(`${API_BASE_URL}/api/imports/validate`, {
    method: "POST",
    body: formData,
  });

  if (!response.ok) {
    throw new ApiError(response.status, response.statusText);
  }

  return (await response.json()) as ImportValidationResult;
}

export interface RestoreResult {
  domains_restored: number;
  conversations_restored: number;
  messages_restored: number;
  documents_restored: number;
  domain_summaries_restored: number;
  skills_restored: number;
  schema_revision_before: string | null;
  schema_revision_after: string;
  rollback_dir: string | null;
  target_dir: string;
  hermes_profile_export_path: string | null;
  hermes_profile_import_command: string | null;
}

/** Restores an export archive onto this machine's own real JARVIS_DATA_DIR
 * — the guarded action behind Data Management's "Restore from Jarvis
 * export" flow (Mac-migration support). `confirm` must be true to
 * overwrite a target that already has data; every other safety behavior
 * (schema/checksum validation, forced-disconnected integrations,
 * forced-disabled schedules/routines) lives entirely server-side. */
export async function restoreImport(file: File, confirm: boolean): Promise<RestoreResult> {
  const formData = new FormData();
  formData.append("file", file);
  formData.append("confirm", confirm ? "true" : "false");

  const response = await fetch(`${API_BASE_URL}/api/restore`, {
    method: "POST",
    body: formData,
  });

  if (!response.ok) {
    let detail = response.statusText;
    try {
      const body = (await response.json()) as { detail?: string };
      if (body.detail) detail = body.detail;
    } catch {
      // response wasn't JSON — fall back to statusText
    }
    throw new ApiError(response.status, detail);
  }

  return (await response.json()) as RestoreResult;
}

export interface TurnUsage {
  input_tokens: number | null;
  output_tokens: number | null;
  total_tokens: number | null;
}

export interface TurnErrorInfo {
  code: string;
  summary: string;
}

export interface TurnResult {
  run_id: string;
  status: "pending" | "running" | "succeeded" | "failed" | "cancelled";
  user_message: Message;
  assistant_message: Message | null;
  provider: string;
  model: string;
  latency_ms: number | null;
  usage: TurnUsage | null;
  context_snapshot_id: string | null;
  error: TurnErrorInfo | null;
}

export async function sendTurn(
  conversationId: string,
  content: string,
  idempotencyKey: string,
  additionalDomainIds: string[] = [],
): Promise<TurnResult> {
  return request(`/api/conversations/${conversationId}/turns`, {
    method: "POST",
    body: JSON.stringify({
      content,
      idempotency_key: idempotencyKey,
      additional_domain_ids: additionalDomainIds,
    }),
  });
}

export interface AgentStatus {
  hermes_available: boolean;
  model_configured: boolean;
  model: string | null;
  provider: string;
}

export async function fetchAgentStatus(): Promise<AgentStatus> {
  return request("/api/agent/status");
}

// --- Phase 4: memory, structured records, summaries, context -----------------

export type MemoryScope = "global" | "domain";
export type MemoryKind =
  | "identity"
  | "preference"
  | "fact"
  | "goal"
  | "constraint"
  | "decision"
  | "health_context"
  | "relationship_context";
export type MemoryStatus = "active" | "archived" | "deleted";
export type Sensitivity = "normal" | "sensitive";

export interface MemoryItem {
  id: string;
  scope: MemoryScope;
  domain_id: string | null;
  kind: MemoryKind;
  title: string;
  status: MemoryStatus;
  importance: number;
  confidence: number;
  sensitivity: Sensitivity;
  event_date: string | null;
  created_at: string;
  updated_at: string;
  current_version_id: string | null;
  supersedes_id: string | null;
  superseded_by_id: string | null;
}

export interface MemoryVersion {
  id: string;
  memory_item_id: string;
  version_number: number;
  title: string;
  kind: MemoryKind;
  content: string;
  importance: number;
  confidence: number;
  sensitivity: Sensitivity;
  event_date: string | null;
  change_reason: string | null;
  source: string | null;
  created_at: string;
}

export interface MemoryItemWithHistory {
  item: MemoryItem;
  current_content: string | null;
  versions: MemoryVersion[];
}

export interface MemoryCreateInput {
  scope: MemoryScope;
  domain_id?: string | null;
  kind: MemoryKind;
  title: string;
  content: string;
  importance?: number;
  confidence?: number;
  sensitivity?: Sensitivity;
  source_message_id?: string | null;
  source_conversation_id?: string | null;
  source_note?: string | null;
  change_reason?: string | null;
}

export async function listMemories(params: {
  scope?: MemoryScope;
  domain_id?: string;
  status?: MemoryStatus;
  kind?: MemoryKind;
  limit?: number;
} = {}): Promise<MemoryItem[]> {
  const query = new URLSearchParams();
  Object.entries(params).forEach(([key, value]) => {
    if (value !== undefined) query.set(key, String(value));
  });
  const qs = query.toString();
  return request(`/api/memories${qs ? `?${qs}` : ""}`);
}

export async function searchMemories(
  q: string,
  domainId?: string,
): Promise<MemoryItem[]> {
  const query = new URLSearchParams({ q });
  if (domainId) query.set("domain_id", domainId);
  return request(`/api/memories/search?${query.toString()}`);
}

export async function createMemory(input: MemoryCreateInput): Promise<MemoryItem> {
  return request("/api/memories", { method: "POST", body: JSON.stringify(input) });
}

export async function getMemory(memoryId: string): Promise<MemoryItemWithHistory> {
  return request(`/api/memories/${memoryId}`);
}

export async function editMemory(
  memoryId: string,
  input: { content: string; title?: string; change_reason?: string },
): Promise<MemoryItem> {
  return request(`/api/memories/${memoryId}/edit`, {
    method: "POST",
    body: JSON.stringify(input),
  });
}

export async function archiveMemory(memoryId: string): Promise<MemoryItem> {
  return request(`/api/memories/${memoryId}/archive`, { method: "POST" });
}

export async function unarchiveMemory(memoryId: string): Promise<MemoryItem> {
  return request(`/api/memories/${memoryId}/unarchive`, { method: "POST" });
}

export async function permanentlyDeleteMemory(
  memoryId: string,
  confirmTitle: string,
): Promise<void> {
  const response = await fetch(`${API_BASE_URL}/api/memories/${memoryId}/delete`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ confirm_title: confirmTitle }),
  });
  if (!response.ok) {
    let detail = response.statusText;
    try {
      const body = await response.json();
      detail = body.detail ?? detail;
    } catch {
      // ignore
    }
    throw new ApiError(response.status, detail);
  }
}

export interface DomainSummary {
  domain_id: string;
  current_content: string | null;
  current_version_id: string | null;
  updated_at: string | null;
}

export interface DomainSummaryVersion {
  id: string;
  domain_summary_id: string;
  version_number: number;
  content: string;
  source: string | null;
  created_at: string;
}

export async function getDomainSummary(slug: string): Promise<DomainSummary> {
  return request(`/api/domains/${slug}/summary`);
}

export async function setDomainSummary(slug: string, content: string): Promise<DomainSummary> {
  return request(`/api/domains/${slug}/summary`, {
    method: "PUT",
    body: JSON.stringify({ content, source: "manual" }),
  });
}

export async function getDomainSummaryHistory(slug: string): Promise<DomainSummaryVersion[]> {
  return request(`/api/domains/${slug}/summary/history`);
}

export type RecordType =
  | "body_weight"
  | "body_symptom"
  | "mind_checkin"
  | "people_interaction"
  | "path_deadline"
  | "build_checkpoint"
  | "life_task";

export interface StructuredRecord {
  id: string;
  domain_id: string;
  record_type: RecordType;
  occurred_at: string;
  payload: Record<string, unknown>;
  sensitivity: Sensitivity;
  created_at: string;
  archived_at: string | null;
}

export async function createStructuredRecord(
  slug: string,
  input: { record_type: RecordType; occurred_at: string; payload: Record<string, unknown> },
): Promise<StructuredRecord> {
  return request(`/api/domains/${slug}/records`, {
    method: "POST",
    body: JSON.stringify(input),
  });
}

export async function listStructuredRecords(
  slug: string,
  params: { record_type?: RecordType; include_archived?: boolean } = {},
): Promise<StructuredRecord[]> {
  const query = new URLSearchParams();
  Object.entries(params).forEach(([key, value]) => {
    if (value !== undefined) query.set(key, String(value));
  });
  const qs = query.toString();
  return request(`/api/domains/${slug}/records${qs ? `?${qs}` : ""}`);
}

export async function archiveStructuredRecord(recordId: string): Promise<StructuredRecord> {
  return request(`/api/records/${recordId}/archive`, { method: "POST" });
}

export interface ContextSnapshot {
  id: string;
  agent_run_id: string;
  active_domain_id: string | null;
  additional_domain_ids: string[];
  global_memory_version_ids: string[];
  domain_memory_version_ids: string[];
  domain_summary_version_ids: string[];
  structured_record_ids: string[];
  recent_message_ids: string[];
  retrieval_query: string;
  retrieval_reasons: Array<{ memory_item_id: string; reason: string }>;
  estimated_context_chars: number;
  created_at: string;
}

export async function getContextSnapshot(runId: string): Promise<ContextSnapshot> {
  return request(`/api/agent-runs/${runId}/context`);
}

export async function rebuildMemoryIndex(): Promise<{ indexed_count: number }> {
  return request("/api/memory-index/rebuild", { method: "POST" });
}

// --- Phase 5: push-to-talk voice ----------------------------------------

export async function transcribeAudio(audio: Blob): Promise<string> {
  const formData = new FormData();
  formData.append("audio", audio, "recording.webm");

  const response = await fetch(`${API_BASE_URL}/api/voice/transcribe`, {
    method: "POST",
    body: formData,
  });

  if (!response.ok) {
    let detail = response.statusText;
    try {
      const body = await response.json();
      detail = body.detail ?? detail;
    } catch {
      // ignore body parse failure, fall back to statusText
    }
    throw new ApiError(response.status, detail);
  }

  const body = (await response.json()) as { transcript: string };
  return body.transcript;
}

export async function synthesizeSpeech(text: string): Promise<Blob> {
  const response = await fetch(`${API_BASE_URL}/api/voice/speak`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ text }),
  });

  if (!response.ok) {
    let detail = response.statusText;
    try {
      const body = await response.json();
      detail = body.detail ?? detail;
    } catch {
      // ignore body parse failure, fall back to statusText
    }
    throw new ApiError(response.status, detail);
  }

  return await response.blob();
}

// --- Phase 8: permissions, actions, hooks, skills -----------------------

export type CapabilityId = "memory.create" | "structured_record.create" | "domain_summary.update";

export interface Capability {
  capability_id: CapabilityId;
  permission_level: string;
}

export type ActionStatus =
  | "proposed"
  | "approved"
  | "denied"
  | "expired"
  | "executing"
  | "succeeded"
  | "failed";

export interface ActionProposal {
  id: string;
  capability_id: CapabilityId;
  domain_id: string | null;
  permission_level: string;
  arguments: Record<string, unknown>;
  reason: string;
  expected_effect: string;
  payload_digest: string;
  status: ActionStatus;
  source: string;
  confirmation_token: string | null;
  confirmation_expires_at: string | null;
  result: Record<string, unknown> | null;
  error_summary: string | null;
  created_at: string;
  updated_at: string;
}

export interface ActionAuditEvent {
  id: string;
  action_proposal_id: string;
  event_type: string;
  detail: string | null;
  created_at: string;
}

export interface ActionProposalWithHistory {
  proposal: ActionProposal;
  audit_events: ActionAuditEvent[];
}

export async function fetchCapabilities(): Promise<Capability[]> {
  return request("/api/capabilities");
}

export async function createActionProposal(input: {
  capability_id: CapabilityId;
  domain_id?: string | null;
  arguments: Record<string, unknown>;
  reason: string;
}): Promise<ActionProposal> {
  return request("/api/actions", { method: "POST", body: JSON.stringify(input) });
}

export async function listActionProposals(params: {
  status?: ActionStatus;
  domain_id?: string;
  limit?: number;
} = {}): Promise<ActionProposal[]> {
  const query = new URLSearchParams();
  Object.entries(params).forEach(([key, value]) => {
    if (value !== undefined) query.set(key, String(value));
  });
  const qs = query.toString();
  return request(`/api/actions${qs ? `?${qs}` : ""}`);
}

export async function getActionProposal(id: string): Promise<ActionProposalWithHistory> {
  return request(`/api/actions/${id}`);
}

export async function approveActionProposal(id: string, payloadDigest: string): Promise<ActionProposal> {
  return request(`/api/actions/${id}/approve`, {
    method: "POST",
    body: JSON.stringify({ payload_digest: payloadDigest }),
  });
}

export async function denyActionProposal(id: string, reason?: string): Promise<ActionProposal> {
  return request(`/api/actions/${id}/deny`, {
    method: "POST",
    body: JSON.stringify({ reason: reason ?? null }),
  });
}

export async function executeActionProposal(id: string, confirmationToken: string): Promise<ActionProposal> {
  return request(`/api/actions/${id}/execute`, {
    method: "POST",
    body: JSON.stringify({ confirmation_token: confirmationToken }),
  });
}

export type SkillStatus = "draft" | "active" | "archived";

export interface SkillWorkflowStep {
  capability_id: CapabilityId;
  description: string;
  argument_hint?: Record<string, unknown>;
}

export interface Skill {
  id: string;
  slug: string;
  name: string;
  description: string;
  domain_id: string | null;
  invocation_phrases: string[];
  status: SkillStatus;
  created_by: "user" | "jarvis";
  current_version_id: string | null;
  created_at: string;
  updated_at: string;
}

export interface SkillVersion {
  id: string;
  skill_id: string;
  version_number: number;
  name: string;
  description: string;
  workflow_steps: SkillWorkflowStep[];
  change_reason: string | null;
  created_at: string;
}

export interface SkillWithHistory {
  skill: Skill;
  versions: SkillVersion[];
}

export async function createSkill(input: {
  slug: string;
  name: string;
  description: string;
  domain_id?: string | null;
  invocation_phrases?: string[];
  workflow_steps: SkillWorkflowStep[];
}): Promise<Skill> {
  return request("/api/skills", { method: "POST", body: JSON.stringify(input) });
}

export async function listSkills(params: {
  status?: SkillStatus;
  domain_id?: string;
} = {}): Promise<Skill[]> {
  const query = new URLSearchParams();
  Object.entries(params).forEach(([key, value]) => {
    if (value !== undefined) query.set(key, String(value));
  });
  const qs = query.toString();
  return request(`/api/skills${qs ? `?${qs}` : ""}`);
}

export async function getSkill(id: string): Promise<SkillWithHistory> {
  return request(`/api/skills/${id}`);
}

export async function editSkill(
  id: string,
  input: { name?: string; description?: string; workflow_steps: SkillWorkflowStep[]; change_reason?: string },
): Promise<Skill> {
  return request(`/api/skills/${id}/edit`, { method: "POST", body: JSON.stringify(input) });
}

export async function activateSkill(id: string): Promise<Skill> {
  return request(`/api/skills/${id}/activate`, { method: "POST" });
}

export async function archiveSkill(id: string): Promise<Skill> {
  return request(`/api/skills/${id}/archive`, { method: "POST" });
}

export async function invokeSkill(
  id: string,
  input: { step_arguments: Record<string, unknown>[]; reason?: string },
): Promise<{ proposals: ActionProposal[] }> {
  return request(`/api/skills/${id}/invoke`, { method: "POST", body: JSON.stringify(input) });
}

// --- Phase 9 (corrected): integrations (Google Calendar, Google Health,
// documents). "google_health" reads Fitbit/Health data via Google OAuth
// and the Google Health API — the legacy Fitbit Web API integration was
// replaced ahead of its September 2026 shutdown.

export type IntegrationProvider = "google_calendar" | "google_health";

export interface IntegrationConnection {
  provider: IntegrationProvider;
  status: "disconnected" | "connected" | "error";
  scopes: string[];
  external_account_label: string | null;
  connected_at: string | null;
  last_sync_at: string | null;
  last_sync_status: string | null;
  last_error: string | null;
}

export async function listIntegrations(): Promise<IntegrationConnection[]> {
  return request("/api/integrations");
}

export async function connectIntegration(
  provider: IntegrationProvider,
  includeWriteScope = false,
): Promise<{ authorization_url: string }> {
  return request(`/api/integrations/${provider}/connect`, {
    method: "POST",
    body: JSON.stringify({ include_write_scope: includeWriteScope }),
  });
}

export async function disconnectIntegration(provider: IntegrationProvider): Promise<IntegrationConnection> {
  return request(`/api/integrations/${provider}/disconnect`, { method: "POST" });
}

export async function syncGoogleCalendar(): Promise<IntegrationConnection> {
  return request("/api/integrations/google_calendar/sync", { method: "POST" });
}

export async function syncGoogleHealth(daysBack = 7): Promise<IntegrationConnection> {
  return request("/api/integrations/google_health/sync", {
    method: "POST",
    body: JSON.stringify({ days_back: daysBack }),
  });
}

// --- Phase 10: controller-owned automatic integration resync -----------

export interface IntegrationSchedule {
  provider: IntegrationProvider;
  enabled: boolean;
  interval_minutes: number;
  next_due_at: string | null;
  last_attempt_at: string | null;
  last_success_at: string | null;
  last_status: string | null;
  last_error: string | null;
  consecutive_failure_count: number;
}

export interface IntegrationSyncRunInfo {
  id: string;
  provider: IntegrationProvider;
  trigger: "manual" | "scheduled" | "startup_catchup";
  started_at: string;
  completed_at: string | null;
  outcome: "succeeded" | "partial" | "failed" | "skipped";
  reason: string | null;
  result_summary: Record<string, number>;
}

export async function getIntegrationSchedule(provider: IntegrationProvider): Promise<IntegrationSchedule> {
  return request(`/api/integrations/${provider}/schedule`);
}

export async function updateIntegrationSchedule(
  provider: IntegrationProvider,
  enabled: boolean,
  intervalMinutes: number,
): Promise<IntegrationSchedule> {
  return request(`/api/integrations/${provider}/schedule`, {
    method: "PUT",
    body: JSON.stringify({ enabled, interval_minutes: intervalMinutes }),
  });
}

export async function listIntegrationSyncHistory(provider: IntegrationProvider): Promise<IntegrationSyncRunInfo[]> {
  return request(`/api/integrations/${provider}/sync-history`);
}

export interface CalendarCalendarInfo {
  id: string;
  external_calendar_id: string;
  summary: string;
  access_role: string;
  is_owned: boolean;
  timezone: string | null;
  selected: boolean;
}

export async function listCalendars(): Promise<CalendarCalendarInfo[]> {
  return request("/api/integrations/google_calendar/calendars");
}

export async function selectCalendar(calendarId: string, selected: boolean): Promise<CalendarCalendarInfo> {
  return request(`/api/integrations/google_calendar/calendars/${calendarId}/select`, {
    method: "POST",
    body: JSON.stringify({ selected }),
  });
}

export interface CalendarEventInfo {
  id: string;
  calendar_id: string;
  external_event_id: string;
  title: string;
  description: string | null;
  location: string | null;
  all_day: boolean;
  start_datetime: string | null;
  end_datetime: string | null;
  start_date: string | null;
  end_date: string | null;
  event_timezone: string | null;
  fetched_at: string;
}

export async function listCalendarEvents(): Promise<CalendarEventInfo[]> {
  return request("/api/integrations/google_calendar/events");
}

export interface GoogleHealthDailySummaryInfo {
  date: string;
  steps: number | null;
  distance_km: number | null;
  floors: number | null;
  active_zone_minutes: number | null;
  active_calories_kcal: number | null;
  calories_out: number | null;
  heart_rate_avg_bpm: number | null;
  heart_rate_min_bpm: number | null;
  heart_rate_max_bpm: number | null;
  resting_heart_rate: number | null;
  hrv_daily_rmssd_ms: number | null;
  oxygen_saturation_avg_percent: number | null;
  respiratory_rate_breaths_per_min: number | null;
  vo2_max: number | null;
  body_fat_percent: number | null;
  blood_glucose_mg_dl: number | null;
  sleep_duration_ms: number | null;
  sleep_minutes_asleep: number | null;
  sleep_efficiency: number | null;
  sleep_type: string | null;
  weight_kg: number | null;
  weight_source: string | null;
  fetched_at: string;
}

export interface GoogleHealthSessionInfo {
  session_type: string;
  start_time: string;
  end_time: string;
  activity_type: string | null;
  calories_kcal: number | null;
  distance_km: number | null;
  average_heart_rate_bpm: number | null;
  minutes_asleep: number | null;
  minutes_awake: number | null;
  source_platform: string | null;
  source_device: string | null;
  fetched_at: string;
}

export interface GoogleHealthMetricGroupStatus {
  category: string;
  has_data: boolean;
  last_error: string | null;
}

export async function listGoogleHealthSummaries(): Promise<GoogleHealthDailySummaryInfo[]> {
  return request("/api/integrations/google_health/summaries");
}

export async function listGoogleHealthSessions(): Promise<GoogleHealthSessionInfo[]> {
  return request("/api/integrations/google_health/sessions");
}

export async function fetchGoogleHealthMetricGroups(): Promise<GoogleHealthMetricGroupStatus[]> {
  return request("/api/integrations/google_health/metric-groups");
}

export async function fetchGoogleHealthUnsupportedMetrics(): Promise<string[]> {
  return request("/api/integrations/google_health/unsupported-metrics");
}

export type DocumentStatus = "processing" | "ready" | "error" | "encrypted" | "unsupported";

export interface DocumentInfo {
  id: string;
  domain_id: string;
  original_filename: string;
  mime_type: string;
  sha256: string;
  size_bytes: number;
  page_count: number | null;
  status: DocumentStatus;
  error_detail: string | null;
  chunk_count: number;
  created_at: string;
}

export interface DocumentChunkInfo {
  id: string;
  chunk_index: number;
  page_number: number | null;
  content: string;
}

export async function uploadDocument(domainId: string, file: File): Promise<DocumentInfo> {
  const formData = new FormData();
  formData.append("domain_id", domainId);
  formData.append("file", file);

  const response = await fetch(`${API_BASE_URL}/api/documents`, { method: "POST", body: formData });
  if (!response.ok) {
    let detail = response.statusText;
    try {
      const body = await response.json();
      detail = body.detail ?? detail;
    } catch {
      // ignore
    }
    throw new ApiError(response.status, detail);
  }
  return (await response.json()) as DocumentInfo;
}

export async function listDocuments(domainId?: string): Promise<DocumentInfo[]> {
  const qs = domainId ? `?domain_id=${encodeURIComponent(domainId)}` : "";
  return request(`/api/documents${qs}`);
}

export async function getDocument(id: string): Promise<{ document: DocumentInfo; chunks: DocumentChunkInfo[] }> {
  return request(`/api/documents/${id}`);
}

export async function deleteDocument(id: string, confirmFilename: string): Promise<void> {
  const response = await fetch(`${API_BASE_URL}/api/documents/${id}/delete`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ confirm_filename: confirmFilename }),
  });
  if (!response.ok) {
    let detail = response.statusText;
    try {
      const body = await response.json();
      detail = body.detail ?? detail;
    } catch {
      // ignore
    }
    throw new ApiError(response.status, detail);
  }
}

// --- Phase 10B: controller-owned proactive routines ---------------------

export type RoutineType = "morning_briefing" | "evening_checkin" | "weekly_review";

export interface RoutineSchedule {
  routine_type: RoutineType;
  enabled: boolean;
  local_time: string;
  weekday: number | null;
  timezone: string;
  selected_domains: string[];
  next_due_at: string | null;
  last_run_at: string | null;
  last_status: string | null;
  last_error: string | null;
  consecutive_failure_count: number;
}

export interface RoutineOutputLine {
  text: string;
  source_ref: string | null;
}

export interface RoutineOutputSection {
  title: string;
  lines: RoutineOutputLine[];
}

export interface RoutineRunInfo {
  id: string;
  routine_type: RoutineType;
  trigger: "manual" | "scheduled" | "startup_catchup";
  started_at: string;
  completed_at: string | null;
  outcome: "succeeded" | "failed" | "skipped";
  reason: string | null;
  sections: RoutineOutputSection[];
  responses: Record<string, string>;
  selected_domains: string[];
}

export async function getRoutineSchedule(routineType: RoutineType): Promise<RoutineSchedule> {
  return request(`/api/routines/${routineType}/schedule`);
}

export async function updateRoutineSchedule(
  routineType: RoutineType,
  update: { enabled: boolean; local_time: string; timezone: string; weekday?: number | null; selected_domains: string[] },
): Promise<RoutineSchedule> {
  return request(`/api/routines/${routineType}/schedule`, { method: "PUT", body: JSON.stringify(update) });
}

export async function runRoutineNow(routineType: RoutineType): Promise<RoutineRunInfo> {
  return request(`/api/routines/${routineType}/run`, { method: "POST" });
}

export async function listRoutineHistory(routineType: RoutineType): Promise<RoutineRunInfo[]> {
  return request(`/api/routines/${routineType}/history`);
}

export async function recordCheckinResponses(runId: string, responses: Record<string, string>): Promise<RoutineRunInfo> {
  return request(`/api/routines/runs/${runId}/responses`, { method: "POST", body: JSON.stringify({ responses }) });
}

// --- Phase 12A: on-demand Home situational briefing ----------------------
//
// Assembled entirely locally and deterministically — this endpoint never
// triggers a model/Hermes call (see docs/ARCHITECTURE.md §9l). The only
// model-reaching action anywhere near this feature is the separate
// "Discuss with Jarvis" flow, which reuses the existing general-conversation
// endpoints above, exactly like Phase 10B's Routine Centre.

export type BriefingCategory = "now" | "next" | "watch";
export type BriefingTone = "neutral" | "attention" | "failure";
export type BriefingFreshness = "current" | "cached" | "stale" | "unavailable";
// Phase 12B: continuity classification — see docs/ARCHITECTURE.md §16 for
// the exact deterministic rules this is computed by on the backend; the
// frontend never re-derives or second-guesses this value.
export type BriefingChangeState = "new" | "changed" | "ongoing" | "resolved" | "reopened";
export type BriefingSnoozeDuration = "1h" | "4h" | "tomorrow_morning" | "1w";

export interface BriefingItem {
  id: string;
  category: BriefingCategory;
  tone: BriefingTone;
  title: string;
  subtitle: string | null;
  domain_slug: string | null;
  source_type: string;
  source_ids: string[];
  reason: string;
  source_timestamp: string | null;
  freshness: BriefingFreshness;
  classification: "factual" | "inferred";
  // A string in the exact shape of commands/registry.ts's NavigateTarget
  // (e.g. "domain:life", "actions_centre") — validated defensively before
  // use, never trusted blindly (see components/BriefingStrip.tsx).
  link_target: string | null;
  fingerprint: string;
  change_state: BriefingChangeState;
  // Phase 12C: set only when this exact item corresponds to an active
  // Mission Focus pin.
  pinned: boolean;
  pin_rank: number | null;
}

export interface BriefingSourceStatus {
  source_type: string;
  status: "ok" | "stale" | "unavailable" | "not_connected";
  detail: string | null;
  last_updated: string | null;
}

export interface BriefingAcknowledgedOrSnoozedEntry {
  stable_key: string;
  kind: "acknowledged" | "snoozed";
  title: string;
  subtitle: string | null;
  domain_slug: string | null;
  link_target: string | null;
  since: string;
  until: string | null;
  duration_key: BriefingSnoozeDuration | null;
}

export interface MissionFocusEntry {
  pin_id: string;
  rank: number;
  source_type: string;
  domain_slug: string | null;
  title: string;
  subtitle: string | null;
  next_action: string;
  target_at: string | null;
  blocker: string | null;
  link_target: string | null;
  available: boolean;
  resolved: boolean;
  change_state: BriefingChangeState | null;
}

export interface HomeBriefing {
  generated_at: string;
  items: BriefingItem[];
  sources: BriefingSourceStatus[];
  include_body: boolean;
  include_mind: boolean;
  include_people: boolean;
  acknowledged_and_snoozed: BriefingAcknowledgedOrSnoozedEntry[];
  mission_focus: MissionFocusEntry[];
}

export interface BriefingSettings {
  include_body: boolean;
  include_mind: boolean;
  include_people: boolean;
}

export interface BriefingSnapshotInfo {
  id: string;
  consumer: "home" | "morning_briefing";
  trigger: string;
  generated_at: string;
  item_count: number;
}

export interface BriefingItemActionResult {
  stable_key: string;
  suppressed: "acknowledged" | "snoozed" | null;
  message: string;
}

export async function fetchHomeBriefing(trigger: "home_view" | "home_refresh" = "home_view"): Promise<HomeBriefing> {
  return request(`/api/briefing/home?trigger=${trigger}`);
}

export async function fetchBriefingSettings(): Promise<BriefingSettings> {
  return request("/api/briefing/settings");
}

export async function updateBriefingSettings(includeBody: boolean): Promise<BriefingSettings> {
  return request("/api/briefing/settings", { method: "PUT", body: JSON.stringify({ include_body: includeBody }) });
}

export async function fetchBriefingHistory(
  consumer: "home" | "morning_briefing" = "home",
  limit = 20,
): Promise<BriefingSnapshotInfo[]> {
  return request(`/api/briefing/history?consumer=${consumer}&limit=${limit}`);
}

export async function acknowledgeBriefingItem(stableKey: string): Promise<BriefingItemActionResult> {
  return request(`/api/briefing/items/${encodeURIComponent(stableKey)}/acknowledge`, { method: "POST" });
}

export async function snoozeBriefingItem(
  stableKey: string,
  duration: BriefingSnoozeDuration,
  timezone?: string,
): Promise<BriefingItemActionResult> {
  return request(`/api/briefing/items/${encodeURIComponent(stableKey)}/snooze`, {
    method: "POST",
    body: JSON.stringify({ duration, timezone }),
  });
}

export async function restoreBriefingItem(stableKey: string): Promise<BriefingItemActionResult> {
  return request(`/api/briefing/items/${encodeURIComponent(stableKey)}/restore`, { method: "POST" });
}

// --- Phase 12C: Mission Focus ---------------------------------------------
//
// A small, deliberate, user-owned watchlist of at most five pinned
// references to existing sources — never a copy of them, never a second
// independent task system, never something Jarvis decides on its own.
// Pinning/unpinning/editing/reordering are direct local presentation
// actions (never the Phase 8 propose/approve/execute lifecycle) and never
// call a model — the only model-reaching action anywhere near this
// feature is "Discuss Mission Focus with Jarvis", which reuses the
// existing general-conversation turn endpoints exactly like Phase 10B/12A.

export type MissionFocusSourceType = "life_task" | "path_deadline" | "build_checkpoint" | "calendar_event" | "action_proposal";

export interface MissionFocusPin {
  id: string;
  source_type: MissionFocusSourceType;
  source_id: string;
  domain_slug: string | null;
  rank: number;
  next_action: string;
  target_at: string | null;
  blocker: string | null;
  status: "active" | "unpinned";
  pinned_at: string;
  unpinned_at: string | null;
  title: string;
  subtitle: string | null;
  link_target: string | null;
  available: boolean;
  resolved: boolean;
  change_state: BriefingChangeState | null;
}

export interface MissionFocusState {
  active_pins: MissionFocusPin[];
  max_active_pins: number;
  default_visible: number;
}

export async function fetchMissionFocus(): Promise<MissionFocusState> {
  return request("/api/mission-focus");
}

export async function createMissionFocusPin(input: {
  source_type: MissionFocusSourceType;
  source_id: string;
  next_action: string;
  target_at?: string | null;
  blocker?: string | null;
  rank?: number | null;
}): Promise<MissionFocusPin> {
  return request("/api/mission-focus/pins", { method: "POST", body: JSON.stringify(input) });
}

export async function updateMissionFocusPin(
  pinId: string,
  input: { next_action: string; target_at?: string | null; blocker?: string | null },
): Promise<MissionFocusPin> {
  return request(`/api/mission-focus/pins/${encodeURIComponent(pinId)}`, { method: "PUT", body: JSON.stringify(input) });
}

export async function unpinMissionFocusPin(pinId: string): Promise<MissionFocusPin> {
  return request(`/api/mission-focus/pins/${encodeURIComponent(pinId)}/unpin`, { method: "POST" });
}

export async function reorderMissionFocus(pinIds: string[]): Promise<MissionFocusState> {
  return request("/api/mission-focus/reorder", { method: "PUT", body: JSON.stringify({ pin_ids: pinIds }) });
}

// --- Mission Control / Current Focus ---------------------------------------
//
// One persistent, timed focus session at a time, built on top of Phase
// 12A/12B's shared briefing candidates and Phase 12C's source resolution —
// never a second prioritization/task system. Starting, pausing, resuming,
// completing, and abandoning a session are all local, reversible, non-
// Hermes actions; the only model-reaching action anywhere near this
// feature is a separate, explicitly user-triggered "Discuss with Jarvis"
// (reusing the existing general-conversation turn endpoints), never
// anything on this surface itself.

export type FocusSessionSourceType =
  | "life_task"
  | "path_deadline"
  | "build_checkpoint"
  | "calendar_event"
  | "action_proposal"
  | "manual";

export type FocusSessionStatus = "planned" | "active" | "paused" | "completed" | "abandoned";

export interface MissionCandidate {
  stable_key: string;
  domain_slug: string | null;
  title: string;
  subtitle: string | null;
  reason: string;
  source_type: string;
  source_ids: string[];
  freshness: BriefingFreshness;
  link_target: string | null;
}

export interface MissionCandidates {
  // Always presented to Bernardo as "suggested from current information" —
  // never a claim that this is definitely his most important task.
  recommended: MissionCandidate | null;
  alternatives: MissionCandidate[];
  watch: MissionCandidate[];
  generated_at: string;
}

export interface FocusSession {
  id: string;
  title: string;
  domain_slug: string | null;
  source_type: string;
  source_id: string | null;
  source_title_snapshot: string | null;
  status: FocusSessionStatus;
  target_duration_minutes: number;
  started_at: string | null;
  paused_at: string | null;
  accumulated_paused_seconds: number;
  completed_at: string | null;
  completion_note: string | null;
  what_changed_note: string | null;
  abandoned_reason: string | null;
  elapsed_seconds: number;
  remaining_seconds: number;
  created_at: string;
  updated_at: string;
}

export interface CurrentMission {
  session: FocusSession | null;
}

export const FOCUS_DURATION_PRESETS_MINUTES = [25, 45, 60] as const;
export const FOCUS_DURATION_MIN_MINUTES = 5;
export const FOCUS_DURATION_MAX_MINUTES = 180;

/** Dispatched on `window` by App.tsx immediately after a voice/command-
 * palette focus_start/pause/resume/complete/abandon action succeeds, so
 * Home's Mission Control strip refetches right away instead of waiting
 * for its own poll interval or a window-focus event — found live during
 * the Phase 12C real-Mac acceptance pass: starting a mission via the
 * command palette while already on Home left the strip showing its old
 * (often empty) state until the next poll/reload, even though the
 * session had genuinely started server-side. Purely a "something
 * changed, refetch" signal — never carries the mutated data itself, so
 * there is nothing here for a listener to trust without still calling
 * the real endpoint. */
export const MISSION_CONTROL_REFRESH_EVENT = "jarvis:mission-control-refresh";

export async function fetchMissionCandidates(): Promise<MissionCandidates> {
  return request("/api/mission-control/candidates");
}

export async function fetchCurrentMission(): Promise<CurrentMission> {
  return request("/api/mission-control/current");
}

export async function fetchMissionHistory(limit = 20): Promise<FocusSession[]> {
  return request(`/api/mission-control/history?limit=${limit}`);
}

export async function startMission(input: {
  source_type: FocusSessionSourceType;
  source_id?: string | null;
  title?: string | null;
  domain_slug?: string | null;
  target_duration_minutes: number;
}): Promise<FocusSession> {
  return request("/api/mission-control/sessions", { method: "POST", body: JSON.stringify(input) });
}

export async function pauseMission(sessionId: string): Promise<FocusSession> {
  return request(`/api/mission-control/sessions/${encodeURIComponent(sessionId)}/pause`, {
    method: "POST",
    body: JSON.stringify({}),
  });
}

export async function resumeMission(sessionId: string): Promise<FocusSession> {
  return request(`/api/mission-control/sessions/${encodeURIComponent(sessionId)}/resume`, {
    method: "POST",
    body: JSON.stringify({}),
  });
}

export async function completeMission(
  sessionId: string,
  input?: { completion_note?: string | null; what_changed_note?: string | null },
): Promise<FocusSession> {
  return request(`/api/mission-control/sessions/${encodeURIComponent(sessionId)}/complete`, {
    method: "POST",
    body: JSON.stringify(input ?? {}),
  });
}

export async function abandonMission(sessionId: string, input?: { completion_note?: string | null }): Promise<FocusSession> {
  return request(`/api/mission-control/sessions/${encodeURIComponent(sessionId)}/abandon`, {
    method: "POST",
    body: JSON.stringify(input ?? {}),
  });
}

/** Pure re-derivation of the backend's `elapsed_seconds()` (app/
 * mission_control_service.py) — never trust a frontend interval as the
 * source of truth. Frozen at `completed_at` for a terminal session, at
 * `paused_at` while paused, ticking live against `now` while active. */
export function computeElapsedSeconds(session: FocusSession, now: Date): number {
  if (!session.started_at) return 0;
  const startedAt = new Date(session.started_at).getTime();
  let endMs: number;
  if (session.status === "completed" || session.status === "abandoned") {
    endMs = session.completed_at ? new Date(session.completed_at).getTime() : startedAt;
  } else if (session.status === "paused") {
    endMs = session.paused_at ? new Date(session.paused_at).getTime() : startedAt;
  } else {
    endMs = now.getTime();
  }
  const totalSeconds = (endMs - startedAt) / 1000 - session.accumulated_paused_seconds;
  return Math.max(0, Math.floor(totalSeconds));
}

export function computeRemainingSeconds(session: FocusSession, now: Date): number {
  const target = session.target_duration_minutes * 60;
  return Math.max(0, target - computeElapsedSeconds(session, now));
}

// --- Phase 12D: Unified Recall and Provenance -------------------------------
// Deterministic local search only — never a model call. See
// backend/app/recall_service.py and docs/ARCHITECTURE.md §19.

export type RecallSourceType =
  | "conversation"
  | "message"
  | "memory_item"
  | "structured_record"
  | "domain_summary"
  | "document"
  | "document_chunk"
  | "calendar_event"
  | "action_proposal"
  | "routine_run"
  | "mission_control_session";

export interface RecallResult {
  source_type: RecallSourceType;
  source_id: string;
  domain_slug: "body" | "build" | "life" | "mind" | "path" | "people" | null;
  title: string;
  // Already HTML-escaped with <mark> highlight spans by the backend —
  // render verbatim (dangerouslySetInnerHTML), never re-escape, never
  // treat as executable.
  snippet_html: string;
  occurred_at: string | null;
  link_target: string | null;
  available: boolean;
  unavailable_reason: string | null;
}

export interface RecallSearchResult {
  query: string;
  results: RecallResult[];
  total_considered: number;
  limit: number;
  offset: number;
  has_more: boolean;
  partial_failures: string[];
}

export interface RecallRebuildResult {
  indexed_count: number;
}

export async function searchRecall(
  params: {
    q: string;
    domains?: string[];
    sourceTypes?: RecallSourceType[];
    includeGlobal?: boolean;
    currentDomain?: string | null;
    limit?: number;
    offset?: number;
  },
  signal?: AbortSignal,
): Promise<RecallSearchResult> {
  const search = new URLSearchParams();
  search.set("q", params.q);
  if (params.domains !== undefined) search.set("domains", params.domains.join(","));
  if (params.sourceTypes !== undefined) search.set("source_types", params.sourceTypes.join(","));
  if (params.includeGlobal !== undefined) search.set("include_global", String(params.includeGlobal));
  if (params.currentDomain) search.set("current_domain", params.currentDomain);
  if (params.limit !== undefined) search.set("limit", String(params.limit));
  if (params.offset !== undefined) search.set("offset", String(params.offset));
  return request(`/api/recall/search?${search.toString()}`, { signal });
}

export async function rebuildRecallIndex(): Promise<RecallRebuildResult> {
  return request("/api/recall/rebuild", { method: "POST" });
}

// --- Phase 12E: Source-Grounded Research Workspace ------------------------
//
// Research over Jarvis's own local corpus, built entirely on top of Phase
// 12D Unified Recall (evidence search below reuses `searchRecall`'s exact
// backend pipeline, scoped to a workspace's own domain policy) — never a
// second search/indexing engine, never unrestricted web research, never an
// autonomous agent. Every mutation here is a direct local presentation/
// analysis action; the one route that can reach a model,
// `draftBriefWithJarvis`, makes exactly one bounded request and is always
// explicitly triggered.

export type ResearchDomainSlug = "body" | "build" | "life" | "mind" | "path" | "people";
export type ResearchWorkspaceStatus = "active" | "archived";
export type ResearchEvidenceClassification = "supporting" | "contradicting" | "contextual" | "unresolved";
export type ResearchBriefSource = "deterministic" | "model";
export type ResearchBriefStatus = "ok" | "invalid_citations";

export interface ResearchWorkspace {
  id: string;
  title: string;
  domain_slug: ResearchDomainSlug | null;
  included_domain_slugs: ResearchDomainSlug[];
  status: ResearchWorkspaceStatus;
  evidence_count: number;
  note_count: number;
  latest_brief_version: number | null;
  created_at: string;
  updated_at: string;
  archived_at: string | null;
}

export interface ResearchEvidence {
  id: string;
  workspace_id: string;
  source_type: RecallSourceType;
  source_id: string;
  domain_slug: ResearchDomainSlug | null;
  title_snapshot: string;
  snippet_snapshot: string;
  occurred_at_snapshot: string | null;
  classification: ResearchEvidenceClassification;
  note: string | null;
  status: "active" | "removed";
  available: boolean;
  unavailable_reason: string | null;
  link_target: string | null;
  added_at: string;
  updated_at: string;
}

export interface ResearchNote {
  id: string;
  workspace_id: string;
  content: string;
  linked_evidence_ids: string[];
  status: "active" | "archived";
  created_at: string;
  updated_at: string;
}

export interface ResearchCitation {
  number: number;
  evidence_id: string;
  source_type: RecallSourceType;
  source_id: string;
  domain_slug: ResearchDomainSlug | null;
  title_snapshot: string;
  snippet_snapshot: string;
  available: boolean;
  unavailable_reason: string | null;
  link_target: string | null;
}

export interface ResearchModelMeta {
  provider: string;
  model: string;
  latency_ms: number;
  evidence_ids_used: string[];
}

// `sections_json` is the deterministic outline's own structured shape
// (an array of {kind: "evidence_group"|"notes", ...}) for `source ===
// "deterministic"`, or `[{kind: "model_text", heading, text}]` for
// `source === "model"` — parsed by the UI, never re-interpreted as HTML or
// executable in any way; model-generated `text` is always rendered as
// plain React text content, never dangerouslySetInnerHTML.
export interface ResearchBriefVersion {
  id: string;
  workspace_id: string;
  version_number: number;
  source: ResearchBriefSource;
  status: ResearchBriefStatus;
  title: string;
  sections_json: string;
  citations: ResearchCitation[];
  validation_issues: string[];
  model_meta: ResearchModelMeta | null;
  generated_at: string;
  created_at: string;
}

export interface ResearchBriefVersionSummary {
  id: string;
  version_number: number;
  source: ResearchBriefSource;
  status: ResearchBriefStatus;
  generated_at: string;
}

export async function fetchResearchWorkspaces(status?: ResearchWorkspaceStatus): Promise<ResearchWorkspace[]> {
  const search = status ? `?status=${status}` : "";
  return request(`/api/research/workspaces${search}`);
}

export async function fetchResearchWorkspace(workspaceId: string): Promise<ResearchWorkspace> {
  return request(`/api/research/workspaces/${workspaceId}`);
}

export async function createResearchWorkspace(input: {
  title: string;
  domain_slug?: ResearchDomainSlug | null;
  included_domain_slugs?: ResearchDomainSlug[] | null;
}): Promise<ResearchWorkspace> {
  return request("/api/research/workspaces", { method: "POST", body: JSON.stringify(input) });
}

export async function updateResearchWorkspace(
  workspaceId: string,
  input: { title?: string; included_domain_slugs?: ResearchDomainSlug[] },
): Promise<ResearchWorkspace> {
  return request(`/api/research/workspaces/${workspaceId}`, { method: "PUT", body: JSON.stringify(input) });
}

export async function archiveResearchWorkspace(workspaceId: string): Promise<ResearchWorkspace> {
  return request(`/api/research/workspaces/${workspaceId}/archive`, { method: "POST" });
}

export async function reopenResearchWorkspace(workspaceId: string): Promise<ResearchWorkspace> {
  return request(`/api/research/workspaces/${workspaceId}/reopen`, { method: "POST" });
}

export async function searchResearchEvidence(
  workspaceId: string,
  params: { q: string; sourceTypes?: RecallSourceType[]; limit?: number; offset?: number },
  signal?: AbortSignal,
): Promise<RecallSearchResult> {
  const search = new URLSearchParams();
  search.set("q", params.q);
  if (params.sourceTypes !== undefined) search.set("source_types", params.sourceTypes.join(","));
  if (params.limit !== undefined) search.set("limit", String(params.limit));
  if (params.offset !== undefined) search.set("offset", String(params.offset));
  return request(`/api/research/workspaces/${workspaceId}/evidence/search?${search.toString()}`, { signal });
}

export async function listResearchEvidence(workspaceId: string): Promise<ResearchEvidence[]> {
  return request(`/api/research/workspaces/${workspaceId}/evidence`);
}

export async function addResearchEvidence(
  workspaceId: string,
  input: { source_type: RecallSourceType; source_id: string; classification?: ResearchEvidenceClassification; note?: string | null },
): Promise<ResearchEvidence> {
  return request(`/api/research/workspaces/${workspaceId}/evidence`, { method: "POST", body: JSON.stringify(input) });
}

export async function updateResearchEvidence(
  workspaceId: string,
  evidenceId: string,
  input: { classification?: ResearchEvidenceClassification; note?: string | null },
): Promise<ResearchEvidence> {
  return request(`/api/research/workspaces/${workspaceId}/evidence/${evidenceId}`, {
    method: "PUT",
    body: JSON.stringify(input),
  });
}

export async function removeResearchEvidence(workspaceId: string, evidenceId: string): Promise<ResearchEvidence> {
  return request(`/api/research/workspaces/${workspaceId}/evidence/${evidenceId}/remove`, { method: "POST" });
}

export async function listResearchNotes(workspaceId: string): Promise<ResearchNote[]> {
  return request(`/api/research/workspaces/${workspaceId}/notes`);
}

export async function addResearchNote(
  workspaceId: string,
  input: { content: string; linked_evidence_ids?: string[] },
): Promise<ResearchNote> {
  return request(`/api/research/workspaces/${workspaceId}/notes`, { method: "POST", body: JSON.stringify(input) });
}

export async function updateResearchNote(
  workspaceId: string,
  noteId: string,
  input: { content: string; linked_evidence_ids?: string[] },
): Promise<ResearchNote> {
  return request(`/api/research/workspaces/${workspaceId}/notes/${noteId}`, {
    method: "PUT",
    body: JSON.stringify(input),
  });
}

export async function archiveResearchNote(workspaceId: string, noteId: string): Promise<ResearchNote> {
  return request(`/api/research/workspaces/${workspaceId}/notes/${noteId}/archive`, { method: "POST" });
}

export async function listResearchBriefs(workspaceId: string): Promise<ResearchBriefVersionSummary[]> {
  return request(`/api/research/workspaces/${workspaceId}/briefs`);
}

export async function getResearchBrief(workspaceId: string, versionId: string): Promise<ResearchBriefVersion> {
  return request(`/api/research/workspaces/${workspaceId}/briefs/${versionId}`);
}

export async function generateDeterministicBrief(workspaceId: string): Promise<ResearchBriefVersion> {
  return request(`/api/research/workspaces/${workspaceId}/briefs/deterministic`, { method: "POST" });
}

export async function draftBriefWithJarvis(workspaceId: string): Promise<ResearchBriefVersion> {
  return request(`/api/research/workspaces/${workspaceId}/briefs/draft`, { method: "POST" });
}

// --- Phase 12F: Evidence-Based Decision Room -------------------------------
//
// Completes Recall -> Research -> Decide -> Focus, built entirely on
// Phase 12D Recall and Phase 12E Research Workspaces — evidence discovery
// below reuses Recall's exact search pipeline, scoped to a decision's own
// *effective* (intersected, never unioned) domain policy. Jarvis supports
// the decision; it never makes it — only an explicit `decideDecision()`
// call ever records a final decision, and "Ask Jarvis to challenge this
// decision" (`draftDecisionCritique`) is a separate, clearly-labeled
// model-generated critique with no lifecycle authority of its own.

export type DecisionStatus = "draft" | "evaluating" | "decided" | "reopened" | "superseded" | "abandoned";
export type DecisionReversibility = "easily_reversible" | "hard_to_reverse" | "irreversible";
export type DecisionOptionStatus = "active" | "eliminated" | "chosen";
export type DecisionEvidenceStance = "supporting" | "contradicting" | "contextual" | "unresolved";
export type DecisionFactorKind = "assumption" | "risk" | "unknown";
export type DecisionFactorStatus = "open" | "resolved";
export type DecisionBriefSource = "deterministic" | "model";
export type DecisionBriefStatus = "ok" | "invalid_citations";
// One more than RecallSourceType — a decision may cite another decision.
export type DecisionSourceType = RecallSourceType | "decision";

export interface Decision {
  id: string;
  title: string;
  description: string | null;
  domain_slug: ResearchDomainSlug | null;
  research_workspace_id: string | null;
  included_domain_slugs: ResearchDomainSlug[];
  // The INTERSECTION of this decision's own policy and its linked
  // Research workspace's policy (if any) — always the real boundary
  // evidence discovery/linking is scoped to, never the union.
  effective_domain_slugs: ResearchDomainSlug[];
  status: DecisionStatus;
  review_date: string | null;
  cost_of_delay_note: string | null;
  info_confidence: number | null;
  reversibility: DecisionReversibility | null;
  supersedes_decision_id: string | null;
  superseded_by_decision_id: string | null;
  abandoned_at: string | null;
  abandoned_reason: string | null;
  option_count: number;
  criterion_count: number;
  evidence_count: number;
  latest_brief_version: number | null;
  is_decided: boolean;
  review_due: boolean;
  created_at: string;
  updated_at: string;
}

export interface DecisionOption {
  id: string;
  decision_id: string;
  name: string;
  description: string | null;
  benefits: string | null;
  costs: string | null;
  risks: string | null;
  reversibility: DecisionReversibility | null;
  status: DecisionOptionStatus;
  rank: number;
  created_at: string;
  updated_at: string;
}

export interface DecisionCriterion {
  id: string;
  decision_id: string;
  name: string;
  description: string | null;
  weight: number;
  rank: number;
  created_at: string;
  updated_at: string;
}

export interface DecisionAssessment {
  id: string;
  option_id: string;
  criterion_id: string;
  score: number | null;
  note: string | null;
  created_at: string;
  updated_at: string;
}

export interface DecisionOptionScore {
  option_id: string;
  option_name: string;
  total_score: number;
  assessed_count: number;
  total_criteria: number;
  missing_criterion_ids: string[];
  missing_criterion_names: string[];
}

export interface DecisionSensitivityWarning {
  criterion_id: string;
  criterion_name: string;
  explanation: string;
}

export interface DecisionScoreBreakdown {
  options: DecisionOptionScore[];
  ranked_option_ids: string[];
  tied: boolean;
  sensitivity_warnings: DecisionSensitivityWarning[];
  incomplete: boolean;
}

export interface DecisionEvidence {
  id: string;
  decision_id: string;
  source_type: DecisionSourceType;
  source_id: string;
  research_evidence_id: string | null;
  linked_option_id: string | null;
  domain_slug: ResearchDomainSlug | null;
  title_snapshot: string;
  snippet_snapshot: string;
  occurred_at_snapshot: string | null;
  stance: DecisionEvidenceStance;
  note: string | null;
  status: "active" | "removed";
  available: boolean;
  unavailable_reason: string | null;
  link_target: string | null;
  added_at: string;
  updated_at: string;
}

export interface DecisionFactor {
  id: string;
  decision_id: string;
  kind: DecisionFactorKind;
  content: string;
  linked_option_id: string | null;
  status: DecisionFactorStatus;
  resolution_note: string | null;
  resolved_at: string | null;
  created_at: string;
  updated_at: string;
}

export interface DecisionCitation {
  number: number;
  evidence_id: string;
  source_type: DecisionSourceType;
  source_id: string;
  domain_slug: ResearchDomainSlug | null;
  title_snapshot: string;
  snippet_snapshot: string;
  available: boolean;
  unavailable_reason: string | null;
  link_target: string | null;
}

export interface DecisionModelMeta {
  provider: string;
  model: string;
  latency_ms: number;
  evidence_ids_used: string[];
}

// `sections_json` shape depends on `source`: for "deterministic" it is
// `{sections: [...], missing_info_warnings: string[], review_date}`; for
// "model" it is `{sections: [{kind: "model_text", heading, text}]}` —
// parsed by the UI, never re-interpreted as HTML/executable. Model text is
// always rendered as plain React text content, never dangerouslySetInnerHTML.
export interface DecisionBriefVersion {
  id: string;
  decision_id: string;
  version_number: number;
  source: DecisionBriefSource;
  status: DecisionBriefStatus;
  title: string;
  sections_json: string;
  citations: DecisionCitation[];
  validation_issues: string[];
  model_meta: DecisionModelMeta | null;
  generated_at: string;
  created_at: string;
}

export interface DecisionBriefVersionSummary {
  id: string;
  version_number: number;
  source: DecisionBriefSource;
  status: DecisionBriefStatus;
  generated_at: string;
}

export interface DecisionFinalVersion {
  id: string;
  decision_id: string;
  version_number: number;
  selected_option_id: string;
  selected_option_name: string;
  rationale: string;
  decision_confidence: number;
  decided_at: string;
  created_at: string;
}

export interface DecisionOutcomeReview {
  id: string;
  decision_id: string;
  decision_final_version_id: string;
  what_happened: string;
  intended_outcome_achieved: boolean | null;
  confidence_was_appropriate: boolean | null;
  would_decide_same_again: boolean | null;
  lessons_learned: string | null;
  reviewed_at: string;
  created_at: string;
}

export interface DecisionCalibrationSummary {
  reviewed_count: number;
  minimum_sample: number;
  has_enough_data: boolean;
  confidence_appropriate_rate: number | null;
  would_decide_same_rate: number | null;
  outcome_achieved_rate: number | null;
}

export async function fetchDecisions(status?: DecisionStatus): Promise<Decision[]> {
  const search = status ? `?status=${status}` : "";
  return request(`/api/decisions${search}`);
}

export async function fetchDecision(decisionId: string): Promise<Decision> {
  return request(`/api/decisions/${decisionId}`);
}

export async function createDecision(input: {
  title: string;
  description?: string | null;
  domain_slug?: ResearchDomainSlug | null;
  research_workspace_id?: string | null;
  included_domain_slugs?: ResearchDomainSlug[] | null;
}): Promise<Decision> {
  return request("/api/decisions", { method: "POST", body: JSON.stringify(input) });
}

export async function updateDecision(
  decisionId: string,
  input: {
    title?: string;
    description?: string | null;
    included_domain_slugs?: ResearchDomainSlug[];
    review_date?: string | null;
    cost_of_delay_note?: string | null;
    info_confidence?: number | null;
    reversibility?: DecisionReversibility | null;
  },
): Promise<Decision> {
  return request(`/api/decisions/${decisionId}`, { method: "PUT", body: JSON.stringify(input) });
}

export async function linkDecisionResearchWorkspace(decisionId: string, researchWorkspaceId: string | null): Promise<Decision> {
  return request(`/api/decisions/${decisionId}/research-workspace`, {
    method: "PUT",
    body: JSON.stringify({ research_workspace_id: researchWorkspaceId }),
  });
}

export async function startEvaluatingDecision(decisionId: string): Promise<Decision> {
  return request(`/api/decisions/${decisionId}/start-evaluating`, { method: "POST" });
}

export async function decideDecision(
  decisionId: string,
  input: { selected_option_id: string; rationale: string; decision_confidence: number },
): Promise<Decision> {
  return request(`/api/decisions/${decisionId}/decide`, { method: "POST", body: JSON.stringify(input) });
}

export async function reopenDecision(decisionId: string): Promise<Decision> {
  return request(`/api/decisions/${decisionId}/reopen`, { method: "POST" });
}

export async function supersedeDecision(decisionId: string, newDecisionId: string): Promise<Decision> {
  return request(`/api/decisions/${decisionId}/supersede`, {
    method: "POST",
    body: JSON.stringify({ new_decision_id: newDecisionId }),
  });
}

export async function abandonDecision(decisionId: string, reason?: string | null): Promise<Decision> {
  return request(`/api/decisions/${decisionId}/abandon`, { method: "POST", body: JSON.stringify({ reason: reason ?? null }) });
}

export async function searchDecisionEvidence(
  decisionId: string,
  params: { q: string; sourceTypes?: DecisionSourceType[]; limit?: number; offset?: number },
  signal?: AbortSignal,
): Promise<RecallSearchResult> {
  const search = new URLSearchParams();
  search.set("q", params.q);
  if (params.sourceTypes !== undefined) search.set("source_types", params.sourceTypes.join(","));
  if (params.limit !== undefined) search.set("limit", String(params.limit));
  if (params.offset !== undefined) search.set("offset", String(params.offset));
  return request(`/api/decisions/${decisionId}/evidence/search?${search.toString()}`, { signal });
}

export async function listDecisionOptions(decisionId: string): Promise<DecisionOption[]> {
  return request(`/api/decisions/${decisionId}/options`);
}

export async function addDecisionOption(
  decisionId: string,
  input: { name: string; description?: string | null; benefits?: string | null; costs?: string | null; risks?: string | null; reversibility?: DecisionReversibility | null },
): Promise<DecisionOption> {
  return request(`/api/decisions/${decisionId}/options`, { method: "POST", body: JSON.stringify(input) });
}

export async function updateDecisionOption(
  decisionId: string,
  optionId: string,
  input: Partial<{
    name: string; description: string | null; benefits: string | null; costs: string | null; risks: string | null;
    reversibility: DecisionReversibility | null; status: "active" | "eliminated";
  }>,
): Promise<DecisionOption> {
  return request(`/api/decisions/${decisionId}/options/${optionId}`, { method: "PUT", body: JSON.stringify(input) });
}

export async function listDecisionCriteria(decisionId: string): Promise<DecisionCriterion[]> {
  return request(`/api/decisions/${decisionId}/criteria`);
}

export async function addDecisionCriterion(
  decisionId: string, input: { name: string; description?: string | null; weight: number },
): Promise<DecisionCriterion> {
  return request(`/api/decisions/${decisionId}/criteria`, { method: "POST", body: JSON.stringify(input) });
}

export async function updateDecisionCriterion(
  decisionId: string, criterionId: string, input: Partial<{ name: string; description: string | null; weight: number }>,
): Promise<DecisionCriterion> {
  return request(`/api/decisions/${decisionId}/criteria/${criterionId}`, { method: "PUT", body: JSON.stringify(input) });
}

export async function removeDecisionCriterion(decisionId: string, criterionId: string): Promise<void> {
  await request(`/api/decisions/${decisionId}/criteria/${criterionId}/remove`, { method: "POST" });
}

export async function listDecisionAssessments(decisionId: string): Promise<DecisionAssessment[]> {
  return request(`/api/decisions/${decisionId}/assessments`);
}

export async function setDecisionAssessment(
  decisionId: string, input: { option_id: string; criterion_id: string; score: number | null; note?: string | null },
): Promise<DecisionAssessment> {
  return request(`/api/decisions/${decisionId}/assessments`, { method: "PUT", body: JSON.stringify(input) });
}

export async function fetchDecisionScoreBreakdown(decisionId: string): Promise<DecisionScoreBreakdown> {
  return request(`/api/decisions/${decisionId}/score-breakdown`);
}

export async function listDecisionEvidence(decisionId: string): Promise<DecisionEvidence[]> {
  return request(`/api/decisions/${decisionId}/evidence`);
}

export async function addDecisionEvidence(
  decisionId: string,
  input: { source_type: DecisionSourceType; source_id: string; stance?: DecisionEvidenceStance; note?: string | null; linked_option_id?: string | null },
): Promise<DecisionEvidence> {
  return request(`/api/decisions/${decisionId}/evidence`, { method: "POST", body: JSON.stringify(input) });
}

export async function importResearchEvidenceIntoDecision(
  decisionId: string,
  input: { research_evidence_id: string; stance?: DecisionEvidenceStance; linked_option_id?: string | null },
): Promise<DecisionEvidence> {
  return request(`/api/decisions/${decisionId}/evidence/import-research`, { method: "POST", body: JSON.stringify(input) });
}

export async function updateDecisionEvidence(
  decisionId: string, linkId: string,
  input: Partial<{ stance: DecisionEvidenceStance; note: string | null; linked_option_id: string | null }>,
): Promise<DecisionEvidence> {
  return request(`/api/decisions/${decisionId}/evidence/${linkId}`, { method: "PUT", body: JSON.stringify(input) });
}

export async function removeDecisionEvidence(decisionId: string, linkId: string): Promise<DecisionEvidence> {
  return request(`/api/decisions/${decisionId}/evidence/${linkId}/remove`, { method: "POST" });
}

export async function listDecisionFactors(decisionId: string, kind?: DecisionFactorKind): Promise<DecisionFactor[]> {
  const search = kind ? `?kind=${kind}` : "";
  return request(`/api/decisions/${decisionId}/factors${search}`);
}

export async function addDecisionFactor(
  decisionId: string, input: { kind: DecisionFactorKind; content: string; linked_option_id?: string | null },
): Promise<DecisionFactor> {
  return request(`/api/decisions/${decisionId}/factors`, { method: "POST", body: JSON.stringify(input) });
}

export async function updateDecisionFactor(
  decisionId: string, factorId: string, input: Partial<{ content: string; linked_option_id: string | null }>,
): Promise<DecisionFactor> {
  return request(`/api/decisions/${decisionId}/factors/${factorId}`, { method: "PUT", body: JSON.stringify(input) });
}

export async function resolveDecisionFactor(decisionId: string, factorId: string, resolutionNote?: string | null): Promise<DecisionFactor> {
  return request(`/api/decisions/${decisionId}/factors/${factorId}/resolve`, {
    method: "POST",
    body: JSON.stringify({ resolution_note: resolutionNote ?? null }),
  });
}

export async function listDecisionBriefs(decisionId: string): Promise<DecisionBriefVersionSummary[]> {
  return request(`/api/decisions/${decisionId}/briefs`);
}

export async function getDecisionBrief(decisionId: string, versionId: string): Promise<DecisionBriefVersion> {
  return request(`/api/decisions/${decisionId}/briefs/${versionId}`);
}

export async function generateDecisionDeterministicBrief(decisionId: string): Promise<DecisionBriefVersion> {
  return request(`/api/decisions/${decisionId}/briefs/deterministic`, { method: "POST" });
}

export async function draftDecisionCritique(decisionId: string): Promise<DecisionBriefVersion> {
  return request(`/api/decisions/${decisionId}/briefs/critique`, { method: "POST" });
}

export async function listDecisionFinalVersions(decisionId: string): Promise<DecisionFinalVersion[]> {
  return request(`/api/decisions/${decisionId}/final-versions`);
}

export async function listDecisionOutcomeReviews(decisionId: string): Promise<DecisionOutcomeReview[]> {
  return request(`/api/decisions/${decisionId}/outcome-reviews`);
}

export async function addDecisionOutcomeReview(
  decisionId: string,
  input: {
    decision_final_version_id?: string | null; what_happened: string;
    intended_outcome_achieved?: boolean | null; confidence_was_appropriate?: boolean | null;
    would_decide_same_again?: boolean | null; lessons_learned?: string | null;
  },
): Promise<DecisionOutcomeReview> {
  return request(`/api/decisions/${decisionId}/outcome-reviews`, { method: "POST", body: JSON.stringify(input) });
}

export async function fetchDecisionCalibrationSummary(): Promise<DecisionCalibrationSummary> {
  return request("/api/decisions-calibration-summary");
}

export { ApiError };
