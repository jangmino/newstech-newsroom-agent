from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, StrictBool, field_validator

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


class PlanRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    question: str = Field(min_length=3, max_length=1000)
    mode: Literal["mock"] = "mock"


class QueryConditions(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    selected_source: SourceName
    entity: str = Field(max_length=100)
    metric: str = Field(max_length=100)
    period: str = Field(max_length=100)
    comparison: str = Field(max_length=100)
    filters: dict[str, str] = Field(default_factory=dict, max_length=10)


class PlanResponse(BaseModel):
    request_id: str
    question: str
    query_plan: QueryPlan
    required_fields: list[str]
    field_options: dict[str, list[str]]


class ExecuteRequest(PlanRequest):
    approved: StrictBool
    conditions: QueryConditions

    @field_validator("approved")
    @classmethod
    def require_approval(cls, value: bool) -> bool:
        if not value:
            raise ValueError("조회 조건을 확인한 뒤 승인해 주세요.")
        return value


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
