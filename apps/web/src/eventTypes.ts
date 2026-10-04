import type { CacheMetadata } from './types';
import type { ResearchFact, ResearchResult } from './researchTypes';
export interface EventConditions {
  tool: 'financials' | 'employment' | 'disclosures' | 'undetermined';
  entities: string[]; company_codes: string[]; metrics: string[];
  start: string; end: string; frequency: string; comparison: string;
  comparison_period: string; statement_basis: string; amount_basis: string; age_range: string;
}
export interface EventDialogueTurn { question: string; answer: string }
export interface EventClarification { question: string; choices: string[] }
export interface EventPlanRequest { question: string; previous_conditions?: EventConditions; revision?: string; conversation?: EventDialogueTurn[] }
export interface EventExecuteRequest { question: string; conditions: EventConditions; approved: true; mode: 'live' | 'snapshot'; snapshot_id?: string }
export interface TraceStep { tool: string; status: 'complete' | 'cached' | 'failed' | 'partial' | 'empty'; at: string; parameters: Record<string, string>; note: string }
export interface EventPlan { request_id: string; question: string; conditions: EventConditions; model: string | null; proposals: string[]; field_errors: Record<string, string>; companies: { name: string; code: string; stock_code: string }[]; trace: TraceStep[]; snapshot_id: string | null; status: 'ready' | 'needs_clarification' | 'unsupported'; clarification: EventClarification | null }
export interface EventResult {
  request_id: string; question: string; conditions: EventConditions; data_mode: 'live' | 'snapshot';
  facts: ResearchFact[]; caveats: string[]; coverage: 'complete' | 'partial' | 'empty';
  trace: TraceStep[]; cache: CacheMetadata | null; brief: ResearchResult['brief']; generated_at: string; snapshot_id: string | null;
}
export interface GeneralResponse { request_id: string; question: string; conditions: EventConditions; text: string; model: string; generated_at: string; instruction: string; tools: string[]; cache: CacheMetadata | null; data_mode: 'live' | 'snapshot' }
export interface DisclosurePeriodLimits { max_days: number; min_date: string; max_date: string }
export interface EventCatalog { snapshots: { id: string; title: string; question: string; conditions: EventConditions; generated_at: string }[]; entities: string[]; ages: string[]; notice: string; disclosure_period?: DisclosurePeriodLimits }
