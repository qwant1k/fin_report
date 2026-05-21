export interface CategoryRow {
  category: string
  label: string
  market_value_prev: number
  daily_change: number
  market_value_current: number
  pct_of_total: number
  ytm: number | null
  duration: number | null
  min_limit_pct: number
  max_limit_pct: number
  hard_limit: string
  soft_limit: string
  free_limit_mln: number | null
}

export interface CDUBlock {
  cdu_id: number
  cdu_name: string
  cdu_short: string
  rows: CategoryRow[]
  total_mv_prev: number
  total_daily_change: number
  total_mv_current: number
  total_pct: number
  ytm_weighted: number
  duration_weighted: number
  benchmark_duration: number | null
  duration_lower: number | null
  duration_upper: number | null
  duration_status: string | null
  cdu_share_pct: number
}

export interface DashboardResponse {
  report_date: string
  fund_total_mv: number
  fund_total_mv_prev: number
  fund_daily_change: number
  fund_daily_change_pct: number
  fund_ytm_weighted: number
  fund_duration_weighted: number
  benchmark_ytm: number | null
  benchmark_duration: number | null
  breaches_count: number
  pending_approvals_count?: number
  flagged_prices_count?: number
  blocks: CDUBlock[]
}

export type ReportStatus = 'draft' | 'pending_approval' | 'approved' | 'rejected'

export interface GeneratedReport {
  id: number
  report_date: string
  report_type: string
  file_path: string
  generated_at: string
  generated_by: string | null
  notes: string | null
  status: ReportStatus
  submitted_by: string | null
  submitted_at: string | null
  approved_by: string | null
  approved_at: string | null
  rejected_by: string | null
  rejected_at: string | null
  rejection_comment: string | null
  version: number
  parent_report_id: number | null
}

export interface InstrumentDetailRow {
  instrument_code: string
  isin: string | null
  instrument_name: string | null
  category: string
  quantity: number
  face_value: number
  amount: number
  ytm: number | null
  duration: number | null
  first_date: string | null
  last_date: string | null
  operations: number
}

export interface InstrumentDetailsResponse {
  cdu_id: number
  category: string
  from: string
  to: string
  rows: InstrumentDetailRow[]
}

export interface AlertItem {
  id: number
  alert_date: string
  cdu_id: number | null
  alert_type: string
  severity: 'INFO' | 'WARN' | 'CRITICAL'
  message: string
  is_resolved: boolean
  created_at: string
}

export interface CDU {
  id: number
  name: string
  short_name: string
  participant_code: string
  participant_code_prefix: string
  share_target_pct: number
  contact_email: string | null
  contact_manager: string | null
  is_active: boolean
}

export interface CDULimit {
  id: number
  cdu_id: number
  instrument_category: string
  min_limit_pct: number
  max_limit_pct: number
  hard_limit_pct: number
  soft_limit_pct: number
  valid_from: string
  valid_to: string | null
}

export interface TradeFile {
  id: number
  cdu_id: number | null
  trade_date: string
  filename: string
  uploaded_at: string
  uploaded_by: string | null
  status: string
  rows_parsed: number
  rows_skipped: number
  sha256: string | null
}

export interface KasePrice {
  id: number
  trade_date: string
  instrument_code: string
  isin: string | null
  instrument_name: string | null
  close_price: number | null
  ytm: number | null
  accrued_interest: number | null
  duration: number | null
  sec_type: string | null
  fin_sec_ru: string | null
  fin_sec_en: string | null
  fin_sec_kz: string | null
  org_code: string | null
  org_name_ru: string | null
  org_name_en: string | null
  org_name_kz: string | null
  settlement_price: number | null
  settlement_dirty_price: number | null
  dohod: number | null
  dtm: number | null
  kase_ytm: number | null
  unit_ru: string | null
  unit_en: string | null
  unit_kz: string | null
  fetched_at: string
  source: string
}

export interface MBM {
  id: number
  index_date: string
  ytm_value: number | null
  duration: number | null
  source: string
  fetched_at: string
}

export interface FormulaDefinition {
  id: number
  code: string
  name: string
  description: string | null
  target: string
  expression_json: string
  is_active: boolean
  version: number
  updated_at: string
  updated_by: string | null
}
