from typing import Literal, Self

from pydantic import BaseModel, ConfigDict, Field, StrictBool, field_validator, model_validator

SourceName = Literal["opendart", "kosis", "undetermined"]
DataMode = Literal["mock", "live", "snapshot"]
InterpretationMethod = Literal["mock_rules", "gemini"]


class WorkshopAccessStatus(BaseModel):
    required: bool
    available: bool


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


class QuestionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    question: str = Field(min_length=3, max_length=1000)
    mode: DataMode = "mock"


class QueryConditions(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    selected_source: SourceName
    entity: str = Field(max_length=100)
    metric: str = Field(max_length=100)
    period: str = Field(max_length=100)
    comparison: str = Field(max_length=100)
    filters: dict[str, str] = Field(default_factory=dict, max_length=10)


class PlanRequest(QuestionRequest):
    interpretation_method: InterpretationMethod = "mock_rules"
    conditions: QueryConditions | None = None

    @model_validator(mode="after")
    def preserved_conditions_are_snapshot_only(self) -> Self:
        if self.conditions is not None and (
            self.mode != "snapshot" or self.interpretation_method != "mock_rules"
        ):
            raise ValueError("입력 조건 유지는 저장 자료의 모의 규칙 방식에서만 지원합니다.")
        return self


class SnapshotMetadata(BaseModel):
    snapshot_id: str
    source: Literal["kosis", "opendart"]
    title: str
    captured_at: str
    coverage: str
    unit: str
    source_urls: list[str]
    caveats: list[str]


class PlanResponse(BaseModel):
    request_id: str
    question: str
    query_plan: QueryPlan
    required_fields: list[str]
    field_options: dict[str, list[str]]
    available_years: list[int] = Field(default_factory=list)
    interpretation_method: InterpretationMethod = "mock_rules"
    interpretation_model: str | None = None
    data_mode: DataMode = "mock"
    snapshot: SnapshotMetadata | None = None
    conditions_preserved: bool = False


class ExecuteRequest(QuestionRequest):
    approved: StrictBool
    conditions: QueryConditions
    snapshot_id: str | None = Field(default=None, min_length=1, max_length=100)

    @model_validator(mode="after")
    def snapshot_requires_version(self) -> Self:
        if (self.mode == "snapshot") != (self.snapshot_id is not None):
            raise ValueError("저장 자료를 확인한 뒤 해당 버전의 조건을 승인해 주세요.")
        return self

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
    raw_values: list[dict[str, str | int | float | None]] = Field(default_factory=list)
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


class GeneralResponseExample(BaseModel):
    text: str
    data_mode: Literal["mock"] = "mock"
    generation_method: Literal["scripted"] = "scripted"


class CalculationRow(BaseModel):
    region: str
    start_value: str | None
    end_value: str | None
    change: str | None = None
    rank: int | None = None
    status: Literal["calculated", "missing_value", "zero_baseline"]
    reason: str | None = None


class CalculationResult(BaseModel):
    dataset_id: str
    data_origin: Literal["synthetic", "kosis"] = "synthetic"
    start_year: int
    end_year: int
    input_unit: str
    result_unit: str
    decimal_places: Literal[2] = 2
    ranking_method: str = "반올림 전 변화값 내림차순 · 동률은 공동 순위 (1, 1, 3)"
    rows: list[CalculationRow]
    warnings: list[str] = Field(default_factory=list)


class FinancialCalculation(BaseModel):
    data_origin: Literal["opendart"] = "opendart"
    start_year: int
    end_year: int
    start_value: str
    end_value: str
    input_unit: Literal["원"] = "원"
    result_unit: Literal["원", "%"]
    change: str | None
    decimal_places: Literal[0, 2]
    status: Literal["calculated", "zero_baseline"]
    reason: str | None = None


class CacheMetadata(BaseModel):
    status: Literal["miss", "hit", "coalesced"]
    scope: Literal["process"] = "process"
    stored_at: str
    expires_at: str
    ttl_seconds: int = Field(ge=1, le=86400)
    age_seconds: float = Field(ge=0)


class ExecutionResponse(AnalysisResponse):
    general_response: GeneralResponseExample
    calculation: CalculationResult | None = None
    financial_calculation: FinancialCalculation | None = None
    cache: CacheMetadata | None = None
    snapshot: SnapshotMetadata | None = None
