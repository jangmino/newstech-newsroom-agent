import type { CacheMetadata, InterpretationMethod, SourceName } from "./types";

export interface ResearchConditions {
  selected_source: SourceName;
  entity: string;
  company_code: string;
  metrics: string[];
  start_year: number | null;
  end_year: number | null;
  comparison: string;
  statement_basis: string;
  age_range: string;
  frequency: string;
}

export interface ResearchPlanRequest {
  question: string;
  mode: "mock" | "live";
  interpretation_method: InterpretationMethod;
  previous_conditions?: ResearchConditions;
  revision?: string;
}

export interface ResearchPlan {
  request_id: string;
  question: string;
  conditions: ResearchConditions;
  selection_reason: string;
  proposals: string[];
  clarification_questions: string[];
  field_errors: Record<string, string>;
  companies: { name: string; code: string; stock_code: string }[];
  available_years: number[];
  available_entities: string[];
  available_metrics: string[];
  metadata_notice: string;
  interpretation_method: InterpretationMethod;
  interpretation_model: string | null;
  data_mode: "mock" | "live";
}

export interface ResearchExecuteRequest {
  question: string;
  mode: "mock" | "live";
  approved: true;
  conditions: ResearchConditions;
  briefing_method: "scripted" | "gemini";
}

export interface ResearchFact {
  id: string;
  entity: string;
  metric: string;
  period: string;
  value: string;
  unit: string;
  kind: "observation" | "change";
  rank?: number | null;
  source_urls: string[];
  retrieved_at: string;
  formula: string;
  details: Record<string, string>;
}

export interface CitedText { text: string; evidence_ids: string[] }

export interface ResearchResult {
  request_id: string;
  question: string;
  conditions: ResearchConditions;
  data_mode: "mock" | "live";
  source_name: string;
  table_or_report: string;
  facts: ResearchFact[];
  caveats: string[];
  cache: CacheMetadata | null;
  brief: {
    status: "complete" | "failed";
    generation_method: "scripted" | "gemini";
    model: string | null;
    content: { summary: CitedText; findings: CitedText[]; limitations: string[]; follow_up_questions: string[] } | null;
    error: string | null;
    verification_status: "review_required";
  };
}
