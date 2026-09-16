import { conditionLabels, conditionValue, editableConditions, sourceLabel } from "./conditions";
import type { ExecutionResponse, QueryPlan } from "./types";

export function comparisonConditions(previous: QueryPlan, current: QueryPlan) {
  const before = editableConditions(previous);
  const after = editableConditions(current);
  const fields = ["selected_source", "entity", "metric", "period", "comparison",
    ...Array.from(new Set([...Object.keys(before.filters), ...Object.keys(after.filters)]))
      .sort().map((key) => `filters.${key}`)];
  return fields.map((field) => ({
    field,
    label: conditionLabels[field] ?? field,
    before: field === "selected_source" ? sourceLabel(before.selected_source) : conditionValue(before, field) || "없음",
    after: field === "selected_source" ? sourceLabel(after.selected_source) : conditionValue(after, field) || "없음",
    changed: conditionValue(before, field) !== conditionValue(after, field),
  }));
}

export function canCompareResults(previous: ExecutionResponse, current: ExecutionResponse) {
  return previous.question === current.question
    && previous.evidence.data_mode === current.evidence.data_mode
    && (current.evidence.data_mode !== "snapshot"
      || (!!current.snapshot?.snapshot_id && previous.snapshot?.snapshot_id === current.snapshot.snapshot_id))
    && previous.query_plan.selected_source === current.query_plan.selected_source
    && comparisonConditions(previous.query_plan, current.query_plan).some((row) => row.changed);
}
