export type SourceName = "opendart" | "kosis" | "undetermined";

export interface QueryPlan {
  selected_source: SourceName;
  selection_reason: string;
  entity: string | null;
  metric: string | null;
  period: string | null;
  comparison: string | null;
  filters: Record<string, string>;
  clarification_required: boolean;
  clarification_questions: string[];
}

export interface PlanRequest {
  question: string;
  mode: "mock";
}

export interface QueryConditions {
  selected_source: SourceName;
  entity: string;
  metric: string;
  period: string;
  comparison: string;
  filters: Record<string, string>;
}

export interface PlanResponse {
  request_id: string;
  question: string;
  query_plan: QueryPlan;
  required_fields: string[];
  field_options: Record<string, string[]>;
  available_years: number[];
  interpretation_method: "mock_rules";
}

export interface ExecuteRequest extends PlanRequest {
  approved: true;
  conditions: QueryConditions;
}

export interface ApiErrorDetail {
  code: "invalid_request" | "invalid_conditions" | "invalid_mock_data" | "invalid_planner_output" | "planner_unavailable";
  message: string;
  field_errors: Record<string, string>;
}

export interface Evidence {
  source_name: string;
  table_or_report: string;
  query_parameters: Record<string, string>;
  retrieved_at: string;
  unit: string;
  raw_values: Array<Record<string, string | number | null>>;
  formula: string;
  caveats: string[];
  data_mode: "mock" | "live" | "snapshot";
}

export interface Brief {
  summary: string;
  verified_facts: string[];
  interpretation_limits: string[];
  follow_up_questions: string[];
  verification_status: "review_required" | "reviewed";
}

export interface AnalysisResponse {
  request_id: string;
  question: string;
  query_plan: QueryPlan;
  evidence: Evidence;
  brief: Brief;
}

export interface GeneralResponseExample {
  text: string;
  data_mode: "mock";
  generation_method: "scripted";
}

export interface ExecutionResponse extends AnalysisResponse {
  general_response: GeneralResponseExample;
  calculation: CalculationResult | null;
}

export interface CalculationRow {
  region: string;
  start_value: string | null;
  end_value: string | null;
  change: string | null;
  rank: number | null;
  status: "calculated" | "missing_value" | "zero_baseline";
  reason: string | null;
}

export interface CalculationResult {
  dataset_id: string;
  data_origin: "synthetic";
  start_year: number;
  end_year: number;
  input_unit: string;
  result_unit: string;
  decimal_places: 2;
  ranking_method: string;
  rows: CalculationRow[];
  warnings: string[];
}
