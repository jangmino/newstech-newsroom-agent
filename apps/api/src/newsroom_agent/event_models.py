"""Participant-only event contracts. Legacy mock contracts remain isolated."""

from typing import Annotated, Literal

from pydantic import Field, StrictBool, field_validator

from newsroom_agent.models import CacheMetadata
from newsroom_agent.research_models import Company, ResearchBrief, ResearchFact, StrictModel

Text = Annotated[str, Field(max_length=100)]


class EventConditions(StrictModel):
    tool: Literal["financials", "employment", "disclosures", "undetermined"] = "undetermined"
    entities: list[Text] = Field(default_factory=list, max_length=2)
    company_codes: list[Annotated[str, Field(pattern=r"^\d{8}$")]] = Field(
        default_factory=list, max_length=2
    )
    metrics: list[Text] = Field(default_factory=list, max_length=3)
    start: str = Field(default="", max_length=10)
    end: str = Field(default="", max_length=10)
    frequency: str = Field(default="연간", max_length=20)
    comparison: str = Field(default="증감 폭", max_length=20)
    comparison_period: str = Field(default="전기", max_length=20)
    statement_basis: str = Field(default="연결", max_length=20)
    amount_basis: str = Field(default="당기", max_length=20)
    age_range: str = Field(default="15-29세", max_length=20)


class EventPlanRequest(StrictModel):
    question: str = Field(min_length=3, max_length=1000)
    previous_conditions: EventConditions | None = None
    revision: str = Field(default="", max_length=1000)


class EventIntent(StrictModel):
    conditions: EventConditions
    recent_periods: int | None = Field(default=None, ge=1, le=93)
    clarification: str = Field(default="", max_length=500)
    unsupported: bool = False


class TraceStep(StrictModel):
    tool: str
    status: Literal["complete", "cached", "failed", "partial", "empty"]
    at: str
    parameters: dict[str, str] = Field(default_factory=dict)
    note: str = ""


class EventPlan(StrictModel):
    request_id: str
    question: str
    conditions: EventConditions
    model: str | None = None
    proposals: list[str]
    field_errors: dict[str, str]
    companies: list[Company] = Field(default_factory=list)
    trace: list[TraceStep] = Field(default_factory=list)
    snapshot_id: str | None = None


class EventExecuteRequest(StrictModel):
    question: str = Field(min_length=3, max_length=1000)
    conditions: EventConditions
    approved: StrictBool
    mode: Literal["live", "snapshot"] = "live"
    snapshot_id: str | None = Field(default=None, max_length=80)

    @field_validator("approved")
    @classmethod
    def require_approval(cls, value):
        if value is not True:
            raise ValueError("조건 승인 필요")
        return value


class EventData(StrictModel):
    facts: list[ResearchFact]
    caveats: list[str]
    trace: list[TraceStep] = Field(default_factory=list)
    coverage: Literal["complete", "partial", "empty"] = "complete"


class EventResult(EventData):
    request_id: str
    question: str
    conditions: EventConditions
    data_mode: Literal["live", "snapshot"]
    cache: CacheMetadata | None = None
    brief: ResearchBrief
    generated_at: str
    snapshot_id: str | None = None


class GeneralDraft(StrictModel):
    text: str = Field(min_length=1, max_length=12000)


class GeneralResponse(GeneralDraft):
    request_id: str
    question: str
    conditions: EventConditions
    model: str
    generated_at: str
    instruction: str
    tools: list[str] = Field(default_factory=list)
    cache: CacheMetadata | None = None
    data_mode: Literal["live", "snapshot"] = "live"
