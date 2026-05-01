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
  blocks: CDUBlock[]
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
  status: string
  rows_parsed: number
  rows_skipped: number
}

export interface KasePrice {
  id: number
  trade_date: string
  instrument_code: string
  isin: string | null
  instrument_name: string | null
  close_price: number | null
  ytm: number | null
  duration: number | null
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
