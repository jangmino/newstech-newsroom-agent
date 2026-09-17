"""Part 2 contracts, kept separate from the guided/legacy contracts."""

from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, StrictBool, StrictInt, field_validator

from newsroom_agent.models import CacheMetadata, InterpretationMethod, SourceName


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class ResearchConditions(StrictModel):
    selected_source: SourceName = "undetermined"
    entity: str = Field(default="", max_length=100)
    company_code: str = Field(default="", max_length=8)
    metrics: list[Annotated[str, Field(max_length=100)]] = Field(default_factory=list, max_length=2)
    start_year: StrictInt | None = None
    end_year: StrictInt | None = None
    comparison: str = Field(default="증감 폭", max_length=30)
    statement_basis: str = Field(default="연결", max_length=30)
    age_range: str = Field(default="15-29세", max_length=30)
    frequency: str = Field(default="연간", max_length=30)


class ResearchPlanRequest(StrictModel):
    question: str = Field(min_length=3, max_length=1000)
    mode: Literal["mock", "live"] = "mock"
    interpretation_method: InterpretationMethod = "mock_rules"
    previous_conditions: ResearchConditions | None = None
    revision: str = Field(default="", max_length=1000)


class Company(StrictModel):
    name: str = Field(min_length=1, max_length=100)
    code: str = Field(pattern=r"^[0-9]{8}$")
    stock_code: str = Field(pattern=r"^[0-9]{6}$")


class ResearchPlanResponse(StrictModel):
    request_id: str
    question: str
    conditions: ResearchConditions
    selection_reason: str
    proposals: list[str]
    clarification_questions: list[str]
    field_errors: dict[str, str]
    companies: list[Company]
    available_years: list[int]
    available_entities: list[str]
    available_metrics: list[str]
    metadata_notice: str
    interpretation_method: InterpretationMethod
    interpretation_model: str | None
    data_mode: Literal["mock", "live"]


class ResearchExecuteRequest(StrictModel):
    question: str = Field(min_length=3, max_length=1000)
    mode: Literal["mock", "live"] = "mock"
    approved: StrictBool
    conditions: ResearchConditions
    briefing_method: Literal["scripted", "gemini"] = "scripted"

    @field_validator("approved")
    @classmethod
    def require_approval(cls, value: bool) -> bool:
        if not value:
            raise ValueError("조사 조건을 확인한 뒤 ‘이 조건으로 조회’를 눌러 주세요.")
        return value


class ResearchFact(StrictModel):
    id: str
    entity: str
    metric: str
    period: str
    value: str
    unit: str
    kind: Literal["observation", "change"]
    rank: int | None = None
    source_urls: list[str] = Field(default_factory=list)
    retrieved_at: str
    formula: str = "원자료 값"
    details: dict[str, str] = Field(default_factory=dict)


class CitedText(StrictModel):
    text: str = Field(min_length=1, max_length=1600)
    evidence_ids: list[str] = Field(min_length=1, max_length=12)


class BriefDraft(StrictModel):
    summary: CitedText
    findings: list[CitedText] = Field(min_length=1, max_length=6)
    limitations: list[str] = Field(min_length=1, max_length=6)
    follow_up_questions: list[str] = Field(min_length=1, max_length=5)


class ResearchBrief(StrictModel):
    status: Literal["complete", "failed"]
    generation_method: Literal["scripted", "gemini"]
    model: str | None = None
    content: BriefDraft | None = None
    error: str | None = None
    verification_status: Literal["review_required"] = "review_required"


class ResearchExecutionResponse(StrictModel):
    request_id: str
    question: str
    conditions: ResearchConditions
    data_mode: Literal["mock", "live"]
    source_name: str
    table_or_report: str
    facts: list[ResearchFact]
    caveats: list[str]
    cache: CacheMetadata | None = None
    brief: ResearchBrief
