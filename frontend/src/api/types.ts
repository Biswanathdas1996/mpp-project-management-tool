// API contract types (mirror backend/app/api/*).
export type Role = 'admin' | 'pmo_editor' | 'super_viewer'
export type Status = 'completed' | 'on_track' | 'delay' | 'critical_delay' | 'not_started'
export type Severity = 'Critical' | 'High' | 'Medium' | 'Low'
export type Priority = 'High' | 'Medium' | 'Low'

export interface User {
  id: number
  email: string
  full_name: string
  role: Role
  tenant_id: number
  tenant_name: string
  tenant_name_ar: string | null
  is_platform_admin: boolean
  locale: 'en' | 'ar'
  sso: boolean
  is_active: boolean
  last_login_at: string | null
}

export interface Program {
  id: number
  name: string
  name_ar: string | null
  client_name: string | null
  client_name_ar: string | null
  subtitle: string | null
  location: string | null
  description: string | null
  reporting_cycle_days: number
  thresholds: Record<string, number>
  is_archived: boolean
  created_at: string
  has_client_logo: boolean
  has_vendor_logo: boolean
  latest_snapshot: { id: number; version_no: number; as_of: string } | null
  snapshot_counts: Record<string, number>
  mapping_status: string | null
  track_count: number
}

export interface ErrorReport { code: string; message: string; hint?: string; detail?: string }

export interface Snapshot {
  id: number
  program_id: number
  version_no: number
  as_of: string | null
  as_of_source: string
  filename: string
  file_size: number
  file_hash: string
  file_format: string | null
  status: 'queued' | 'parsing' | 'awaiting_mapping' | 'processing' | 'ready' | 'failed'
  status_message: string | null
  error_report: ErrorReport | null
  warnings: string[]
  task_count: number
  has_baseline: boolean
  planned_method: string | null
  rebaselined: boolean
  kpi_engine_version: string | null
  uploaded_at: string
  processed_at: string | null
  project: Record<string, string | number | null>
  discovery_source: string | null
  profile?: Profile
}

export interface Profile {
  task_count: number
  leaf_task_count: number
  summary_task_count: number
  milestone_flag_count: number
  resource_count: number
  max_outline_level: number
  tasks_per_level: Record<string, number>
  summaries_per_level: Record<string, number>
  summary_names_by_level: Record<string, string[]>
  field_coverage_pct: Record<string, number>
  group_coverage_pct: Record<string, number>
  custom_fields: { field: string; populated_tasks: number; coverage_pct: number; distinct_values: number; top_values: string[]; is_flag_like: boolean }[]
  quality_gaps: { code: string; severity: string; message: string; count: number | null }[]
  project: Record<string, string | null>
  discovery?: {
    source: string
    proposal_source: string
    summary?: string
    structure_notes?: string
    gaps?: string[]
    ideas?: { name: string; rationale: string; required_fields: string[] }[]
    flags?: string[]
    proposal: { track_rule: Rule; milestone_rule: Rule; planned_method: string; rationale: string }
    proposed_kpis: { code: string; rationale: string }[]
  }
}

export interface Rule { type: 'outline_level' | 'custom_field' | 'flag'; level?: number; field?: string; value?: string }

export interface MappingConfig {
  id: number
  version: number
  status: string
  track_rule: Rule
  milestone_rule: Rule
  planned_method: string
  track_names: Record<string, string>
  excluded_track_keys: string[]
  approved_kpis: string[]
  proposed_kpis: { code: string; rationale: string }[]
  proposed_by: string
  rationale: string | null
  source_snapshot_id: number | null
  approved_at: string | null
  auto_approved?: boolean
  created_at: string
}

export interface CatalogueEntry { code: string; name: string; category: string; reference: boolean; phase: string; formula: string }

export interface MappingState {
  approved: MappingConfig | null
  proposed: MappingConfig | null
  history: MappingConfig[]
  snapshot_id: number | null
  profile: Profile
  kpi_catalogue: CatalogueEntry[]
}

export interface PreviewResult {
  snapshot_id: number
  tracks: { key: string; number: number; name: string; source_label: string; task_count: number; milestones: string[] }[]
  milestone_count: number
  unmapped_tasks: number
}

export interface Health { kind: string; label: string; days: number | null; urgency: 'done' | 'low' | 'medium' | 'high' | 'critical' }

export interface TrackRow {
  id: number; number: number; label: string; name: string; name_ar: string | null; status: Status
  actual: number; planned: number; variance: number; start: string | null; finish: string | null
  source_label: string; leaf_count: number; started: boolean
}

export interface MilestoneRow {
  id: number; number: number; name: string; task_unique_id: number; track_id: number | null
  track_number: number | null; track_name: string | null; start: string | null; finish: string | null
  baseline_start: string | null; baseline_finish: string | null; percent_complete: number; planned_percent: number
  variance_pts: number; status: Status; health: Health; slippage_days: number | null; is_critical: boolean
}

export interface RiskItem {
  id: number; title: string; title_ar: string | null; description: string | null; severity: Severity
  likelihood: string | null; impact: string | null; mitigation: string | null; owner: string | null
  due_date: string | null; status: 'Open' | 'Mitigating' | 'Closed'; source: string; review_status: string
  related_task_uids: number[]; created_at: string; updated_at: string | null
}
export interface DecisionItem {
  id: number; title: string; title_ar: string | null; description: string | null; kind: 'decision' | 'support'
  priority: Priority; status: 'Pending' | 'Approved' | 'Rejected'; owner: string | null; needed_by: string | null
  decided_at: string | null; source: string; review_status: string; related_task_uids: number[]; created_at: string
  updated_at: string | null
}
export interface AttentionRow {
  id?: number; title: string; title_ar?: string | null; description: string | null; severity: Severity
  status?: string; owner?: string | null; due_date: string | null; category: string | null; source: string
  review_status?: string; related_task_uids: number[]; created_at?: string
}

export interface TrendPoint { snapshot_id: number; version_no: number; as_of: string; cycle: number; planned: number | null; actual: number | null }

export interface Dashboard {
  program_id: number
  snapshot: { id: number; version_no: number; as_of: string; filename: string; planned_method: string; rebaselined: boolean; warnings: string[]; kpi_engine_version: string }
  header: {
    client_name: string | null; client_name_ar: string | null; program_name: string; program_name_ar: string | null
    title: string; subtitle: string; location: string | null; as_of: string; client_logo_url: string | null
    vendor_logo_url: string | null; support_email: string | null; contact_url: string | null; primary_color: string | null
  }
  kpi_strip: { tracks: number; active: number; avg_progress: number; milestones: number }
  cards: {
    program_completion: { value: number | null; tag: string | null; planned: number | null; variance_pts: number | null; kpi: string }
    active_tracks: { value: number | null; total: number | null; pending: number | null; kpi: string }
    total_milestones: { value: number | null; tracks_covered: number | null; by_status: Record<string, number>; kpi: string }
    on_track: { value: number | null; of: number | null; kpi: string }
    not_started: { value: number | null; of: number | null; kpi: string }
    decisions_required: { value: number | null; high_priority: number; kpi: string }
    high_risks: { value: number | null; tracked: number; kpi: string }
    active_track_timeline: { value: number | null; available: boolean; start?: string; finish?: string; month?: number; of_months?: number; elapsed_pct?: number; kpi: string }
    next_milestone: { available: boolean; milestone_id?: number; number?: number; name?: string; start?: string; finish?: string; days_to_start?: number; kpi: string }
  }
  tracks: TrackRow[]
  active_track_progress: { percent: number; planned: number; active_tracks: number; total_tracks: number }
  milestones: MilestoneRow[]
  gantt: {
    months: { key: string; label: string; start: string; end: string }[]
    items: { milestone_id: number; number: number; name: string; track_number: number | null; start: string; finish: string; percent_complete: number; planned_percent: number; status: Status; is_point: boolean }[]
    today: string
    range?: { start: string; end: string }
  }
  trend: { points: TrendPoint[]; cycles_reported: number; cycle_days: number; cycle_label: string; summary: { planned: number | null; actual: number | null; behind_pts: number; tracks_covered: number; tracks_total: number } }
  decisions: DecisionItem[]
  risks: RiskItem[]
  attention: { derived: AttentionRow[]; items: AttentionRow[] }
  ai_summary: { id: number; content: ExecSummary; model: string; created_at: string; flags: string[] } | null
}

export interface KPIItem {
  code: string; name: string; category: string; formula?: string; widget?: string; unit?: string | null; phase?: string
  version?: number; available: boolean; reason?: string | null; value?: number | null; display?: string | null
  details?: Record<string, any>; drill_count?: number; reference?: boolean; source_fields?: string[]; approved?: boolean
}

export interface TaskRow {
  unique_id: number; task_id: number | null; wbs: string | null; outline_number: string | null; outline_level: number
  name: string; is_summary: boolean; is_milestone: boolean; is_mapped_milestone: boolean; is_critical: boolean
  start: string | null; finish: string | null; baseline_start: string | null; baseline_finish: string | null
  actual_start: string | null; actual_finish: string | null; percent_complete: number; planned_percent: number | null
  duration_days: number | null; total_slack_days: number | null; free_slack_days: number | null
  constraint_type: string | null; deadline: string | null; resource_names: string[]; notes: string | null
  predecessors: { uid: number; type: string; lag_days: number | null }[]; custom_fields: Record<string, unknown>
  work_hours: number | null; cost: number | null; baseline_cost: number | null; actual_cost: number | null
}

export interface DiffRow {
  task_unique_id: number | null; base_unique_id: number | null; match_method: string; match_score: number
  change_type: string; task_name: string; track_id: number | null; is_milestone: boolean
  changes: Record<string, { old: unknown; new: unknown }>; start_delta_days: number | null
  finish_delta_days: number | null; progress_delta: number | null; old_status: string | null; new_status: string | null
}
export interface DiffResult {
  snapshot_id: number; compare_to: string; base: { id: number; version_no: number; as_of: string } | null
  rebaselined: boolean
  summary: { total: number; by_type: Record<string, number>; renamed: number; slipped: number; pulled_in: number; net_finish_days: number; milestones_changed: number; status_transitions: Record<string, number> }
  changes: DiffRow[]
}

export interface ExecSummary { headline: string; summary: string; highlights: string[]; concerns: string[]; recommendations: string[] }
export interface Insight {
  id: number; kind: string; snapshot_id: number; question: string | null; content: any; guardrail_flags: string[]
  provider: string; model: string; prompt_version: string; latency_ms: number; created_at: string
  drafts_created?: { risks: number; decisions: number; attention: number }
  duplicates_skipped?: number
}

export interface Tenant {
  id: number; name: string; name_ar: string | null; slug: string
  branding: { primary_color?: string; support_email?: string; contact_url?: string; location?: string }
  has_client_logo: boolean; has_vendor_logo: boolean; ai_mode: 'off' | 'self_hosted' | 'cloud'; ai_model: string
  ai_redact: boolean; cloud_available: boolean; is_active: boolean
}

export interface AlertRule { id: number; name: string; program_id: number | null; kpi_code: string; kpi_name: string; operator: string; threshold: number; channel: string; target: string | null; enabled: boolean }
export interface AlertItem { id: number; title: string; message: string; value: number | null; program_id: number | null; snapshot_id: number | null; delivery_status: string; acknowledged: boolean; created_at: string }
export interface AuditItem { id: number; action: string; user_email: string | null; entity_type: string | null; entity_id: string | null; program_id: number | null; details: Record<string, unknown>; ip: string | null; created_at: string }

export interface PortfolioRow {
  program_id: number; name: string; name_ar: string | null; client_name: string | null; snapshot_id: number | null; as_of: string | null
  completion: number | null; planned: number | null; variance_pts: number | null; spi: number | null; milestones: number | null
  critical_delays: number | null; delays: number | null; overdue_tasks: number | null; tracks: number | null; active_tracks: number | null
  tag: string | null; open_risks: number; high_risks: number; pending_decisions: number; overdue_decisions: number
}
