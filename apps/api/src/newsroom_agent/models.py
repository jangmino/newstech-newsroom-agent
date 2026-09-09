from typing import Literal

from pydantic import BaseModel, Field

SourceName = Literal["opendart", "kosis", "undetermined"]
DataMode = Literal["mock", "live", "snapshot"]


class AnalysisRequest(BaseModel):
    question: str = Field(min_length=3, max_length=1000)
    mode: DataMode = "mock"


class QueryPlan(BaseModel):
    selected_source: SourceName
    selection_reason: str
    entity: str | None = None
    metric: str | None = None
    period: str | None = None
    comparison: str | None = None
    filters: dict[str, str] = Field(default_factory=dict)
    clarification_required: bool = False
    clarification_questions: list[str] = Field(default_factory=list)


class Evidence(BaseModel):
    source_name: str
    table_or_report: str
    query_parameters: dict[str, str] = Field(default_factory=dict)
    retrieved_at: str
    unit: str
    raw_values: list[dict[str, str | int | float]] = Field(default_factory=list)
    formula: str
    caveats: list[str] = Field(default_factory=list)
    data_mode: DataMode


class Brief(BaseModel):
    summary: str
    verified_facts: list[str]
    interpretation_limits: list[str]
    follow_up_questions: list[str]
    verification_status: Literal["review_required", "reviewed"] = "review_required"


class AnalysisResponse(BaseModel):
    request_id: str
    question: str
    query_plan: QueryPlan
    evidence: Evidence
    brief: Brief
