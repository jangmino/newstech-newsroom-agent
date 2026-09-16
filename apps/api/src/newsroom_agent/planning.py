"""Validate untrusted interpretations before they become editable query plans."""

import json
from typing import Annotated, Literal
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field

from newsroom_agent.conditions import (
    FIELD_OPTIONS,
    SELECTION_REASONS,
    route_question,
    validate_conditions,
)
from newsroom_agent.models import PlanResponse, QueryConditions, QueryPlan, SourceName
from newsroom_agent.providers.mock_employment import YEARS
from newsroom_agent.providers.planner import QuestionPlanner

ConditionText = Annotated[str, Field(max_length=100)]
ConditionField = Literal[
    "selected_source", "entity", "metric", "period", "comparison",
    "filters.age_range", "filters.frequency", "filters.statement_basis", "filters.report_type",
]
MAX_OUTPUT_LENGTH = 8192


class StructuredQuestion(BaseModel):
    """Internal adapter output, not a client request or an executable plan."""

    model_config = ConfigDict(extra="forbid", strict=True, str_strip_whitespace=True)

    selected_source: SourceName
    entity: ConditionText | None
    metric: ConditionText | None
    period: ConditionText | None
    comparison: ConditionText | None
    filters: dict[ConditionText, ConditionText | None] = Field(max_length=10)
    uncertain_fields: list[ConditionField] = Field(max_length=9)


class InvalidPlannerOutput(Exception):
    """No raw output or validation details may cross the public error boundary."""


def _unique_object(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("Duplicate JSON key")
        result[key] = value
    return result


def _reject_constant(value: str) -> None:
    raise ValueError("Non-finite JSON value")


def parse_interpretation(raw: str) -> StructuredQuestion:
    if not isinstance(raw, str) or len(raw) > MAX_OUTPUT_LENGTH:
        raise InvalidPlannerOutput() from None
    try:
        data = json.loads(raw, object_pairs_hook=_unique_object, parse_constant=_reject_constant)
        return StructuredQuestion.model_validate(data)
    except (ValueError, RecursionError):
        raise InvalidPlannerOutput() from None


def create_plan(question: str, planner: QuestionPlanner) -> PlanResponse:
    candidate = parse_interpretation(planner.interpret(question))
    source = candidate.selected_source
    if "selected_source" in candidate.uncertain_fields:
        source = "undetermined"
    if source != "undetermined" and source != route_question(question):
        raise InvalidPlannerOutput() from None
    options = FIELD_OPTIONS.get(source, {})
    if source == "undetermined":
        conditions = QueryConditions(
            selected_source=source, entity="", metric="", period="", comparison="", filters={},
        )
    else:
        allowed_filters = {field[8:] for field in options if field.startswith("filters.")}
        allowed_fields = {*options, "period", "selected_source"}
        if candidate.filters.keys() - allowed_filters or (
            set(candidate.uncertain_fields) - allowed_fields
        ):
            raise InvalidPlannerOutput() from None
        conditions = QueryConditions(
            selected_source=source,
            **{field: getattr(candidate, field) or ""
               for field in ("entity", "metric", "period", "comparison")},
            filters={key: candidate.filters.get(key) or "" for key in sorted(allowed_filters)},
        )
        # Uncertainty overrides even a syntactically valid, supported value.
        for field in candidate.uncertain_fields:
            _clear_field(conditions, field)
    errors = validate_conditions(conditions)
    # Never prefill unsupported values as if they were accepted conditions.
    for field in errors:
        if field != "selected_source":
            _clear_field(conditions, field)
    return PlanResponse(
        request_id=str(uuid4()), question=question,
        query_plan=QueryPlan(
            **conditions.model_dump(), selection_reason=SELECTION_REASONS[source],
            clarification_required=bool(errors), clarification_questions=list(errors.values()),
        ),
        required_fields=list(errors), field_options=options,
        available_years=list(YEARS) if source == "kosis" else [],
    )


def _clear_field(conditions: QueryConditions, field: str) -> None:
    if field.startswith("filters."):
        conditions.filters[field[8:]] = ""
    else:
        setattr(conditions, field, "")
