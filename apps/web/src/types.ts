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
}

export interface ExecuteRequest extends PlanRequest {
  approved: true;
  conditions: QueryConditions;
}

export interface ApiErrorDetail {
  code: "invalid_request" | "invalid_conditions";
  message: string;
  field_errors: Record<string, string>;
}

export interface Evidence {
  source_name: string;
  table_or_report: string;
  query_parameters: Record<string, string>;
  retrieved_at: string;
  unit: string;
  raw_values: Array<Record<string, string | number>>;
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
