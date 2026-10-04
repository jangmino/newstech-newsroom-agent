import asyncio
from contextlib import asynccontextmanager
from functools import lru_cache
from pathlib import Path
from typing import Annotated

from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.exception_handlers import http_exception_handler, request_validation_exception_handler
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from starlette.exceptions import HTTPException as StarletteHTTPException

from newsroom_agent.calculations import CalculationDataError
from newsroom_agent.conditions import route_question, validate_conditions
from newsroom_agent.config import get_settings
from newsroom_agent.event_models import (
    EventExecuteRequest,
    EventPlan,
    EventPlanRequest,
    EventResult,
    GeneralResponse,
)
from newsroom_agent.event_service import EventService, snapshot_catalog
from newsroom_agent.event_stream import EventAdmission
from newsroom_agent.live_employment import compose_employment, execute_employment
from newsroom_agent.live_financials import compose_financials, execute_financials
from newsroom_agent.models import (
    AnalysisRequest,
    AnalysisResponse,
    ExecuteRequest,
    ExecutionResponse,
    PlanRequest,
    PlanResponse,
    WorkshopAccessStatus,
)
from newsroom_agent.operations import OperationsStatus, operations_status
from newsroom_agent.orchestrator import InvalidConditions, MockOrchestrator
from newsroom_agent.planning import InvalidPlannerOutput, create_plan, plan_from_conditions
from newsroom_agent.providers.kosis import KosisClient
from newsroom_agent.providers.kosis_employment import EmploymentSeries, KosisError
from newsroom_agent.providers.mock_planner import MockQuestionPlanner
from newsroom_agent.providers.opendart import OpenDartClient
from newsroom_agent.providers.opendart_financials import OpenDartError, RevenuePair
from newsroom_agent.providers.planner import (
    PlannerAuthenticationError,
    PlannerBillingError,
    PlannerConfigurationError,
    PlannerDisabled,
    PlannerRateLimited,
    PlannerTimedOut,
    PlannerUnavailable,
    QuestionPlanner,
)
from newsroom_agent.providers.snapshot import SnapshotError, load_snapshot, select_employment
from newsroom_agent.public_data_cache import PublicDataCache
from newsroom_agent.public_data_limits import (
    PublicDataCallLimiter,
    PublicDataLimitError,
    PublicDataSource,
)
from newsroom_agent.request_flow import flow
from newsroom_agent.request_logging import (
    RequestLoggingMiddleware,
    configure_request_logging,
    record_error,
)
from newsroom_agent.research import ResearchError, ResearchService
from newsroom_agent.research_models import (
    ResearchExecuteRequest,
    ResearchExecutionResponse,
    ResearchPlanRequest,
    ResearchPlanResponse,
)
from newsroom_agent.workshop_access import WorkshopAccessMiddleware, access_status

settings = get_settings()
configure_request_logging()


@asynccontextmanager
async def lifespan(app: FastAPI):
    get_public_data_limiter.cache_clear()
    app.state.event_admission = EventAdmission()
    app.state.employment_cache = PublicDataCache[EmploymentSeries](
        settings.cache_ttl_seconds,
        settings.cache_max_entries,
    )
    app.state.revenue_cache = PublicDataCache[RevenuePair](
        settings.cache_ttl_seconds,
        settings.cache_max_entries,
    )
    app.state.research_metadata_cache = PublicDataCache(86400, settings.cache_max_entries)
    app.state.research_data_cache = PublicDataCache(
        settings.cache_ttl_seconds,
        settings.cache_max_entries,
    )
    try:
        yield
    finally:
        await app.state.employment_cache.close()
        await app.state.revenue_cache.close()
        await app.state.research_metadata_cache.close()
        await app.state.research_data_cache.close()
        get_public_data_limiter.cache_clear()


app = FastAPI(title="NewsTech Newsroom Agent API", version="0.1.0", lifespan=lifespan)
app.add_middleware(WorkshopAccessMiddleware, settings=lambda: settings)
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origin_list,
    allow_credentials=False,
    allow_methods=["GET", "POST"],
    allow_headers=["Content-Type", "X-Workshop-Code"],
    expose_headers=["X-Request-ID"],
)
app.add_middleware(RequestLoggingMiddleware, allow_origins=settings.cors_origin_list)


@app.exception_handler(StarletteHTTPException)
async def http_error(request: Request, exc: StarletteHTTPException):
    if isinstance(exc.detail, dict):
        record_error(exc.detail.get("code"))
    return await http_exception_handler(request, exc)


@app.exception_handler(SnapshotError)
async def snapshot_error(request: Request, exc: SnapshotError):
    record_error(exc.code)
    return JSONResponse(status_code=409 if exc.code == "snapshot_changed" else 503,
                        headers={"Cache-Control": "no-store"}, content={"detail": {
                            "code": exc.code, "message": str(exc), "field_errors": {},
                        }})


def require_snapshot() -> None:
    if not settings.fallback_snapshot_enabled:
        raise SnapshotError("snapshot_disabled")


@app.get("/api/v1/access", response_model=WorkshopAccessStatus)
@app.post("/api/v1/access", response_model=WorkshopAccessStatus)
def workshop_access() -> WorkshopAccessStatus:
    return access_status(settings)


@app.get("/api/v1/operations", response_model=OperationsStatus)
def workshop_operations() -> OperationsStatus:
    return operations_status(settings)


@app.get("/health")
def health() -> dict[str, str | bool]:
    return {
        "status": "ok",
        "environment": settings.app_env,
        "public_data_mode": settings.public_data_mode,
        "live_api_enabled": settings.live_api_enabled,
        "gemini_planner_enabled": settings.gemini_planner_enabled and settings.live_api_enabled,
        "opendart_enabled": opendart_enabled(),
        "kosis_enabled": kosis_enabled(),
    }


@app.post("/api/v1/analyze", response_model=AnalysisResponse)
def analyze(request: AnalysisRequest) -> AnalysisResponse:
    if request.mode == "live" and not settings.live_api_enabled:
        raise HTTPException(status_code=503, detail="Live API mode is disabled")
    if request.mode != "mock":
        raise HTTPException(
            status_code=501, detail="Only mock mode is implemented in the foundation slice"
        )
    return MockOrchestrator().analyze(request.question)


@app.exception_handler(RequestValidationError)
async def validation_error(request: Request, exc: RequestValidationError):
    record_error("invalid_request")
    if request.url.path not in {"/api/v1/plan", "/api/v1/execute",
                                "/api/v1/research/plan", "/api/v1/research/execute"}:
        return await request_validation_exception_handler(request, exc)
    messages = {
        "question": "질문을 3자 이상 1,000자 이하로 입력해 주세요.",
        "mode": "모의 자료, 공식 실제 자료 또는 공식 저장 자료를 선택해 주세요.",
        "snapshot_id": "저장 자료 안내를 다시 확인한 뒤 해당 조건으로 승인해 주세요.",
        "approved": "조건을 확인한 뒤 ‘이 조건으로 조회’를 눌러 주세요.",
        "interpretation_method": "모의 규칙 또는 Gemini 중 질문 해석 방식을 선택해 주세요.",
        "briefing_method": "모의 문장 또는 Gemini 중 브리핑 작성 방식을 선택해 주세요.",
    }
    errors = {}
    for error in exc.errors():
        path = ".".join(str(part) for part in error["loc"] if part != "body")
        errors[path.removeprefix("conditions.")] = messages.get(
            path, "입력한 조건의 형식을 확인해 주세요."
        )
    return JSONResponse(
        status_code=422,
        content={
            "detail": {
                "code": "invalid_request",
                "message": "입력 내용을 확인해 주세요.",
                "field_errors": errors,
            }
        },
    )


@lru_cache
def get_public_data_limiter(
    source: PublicDataSource, requests_per_minute: int, max_concurrent: int,
) -> PublicDataCallLimiter:
    return PublicDataCallLimiter(source, requests_per_minute, max_concurrent)


@lru_cache
def get_gemini_limiter(requests_per_minute: int, max_concurrent: int):
    from newsroom_agent.providers.gemini_planner import GeminiCallLimiter

    return GeminiCallLimiter(requests_per_minute, max_concurrent)


def get_question_planner(request: PlanRequest) -> QuestionPlanner:
    if request.interpretation_method == "mock_rules":
        return MockQuestionPlanner()
    from google.genai import types

    from newsroom_agent.providers.gemini import GeminiProvider
    from newsroom_agent.providers.gemini_planner import GeminiQuestionPlanner

    def make_client():
        return GeminiProvider(
            auth_mode=settings.gemini_auth_mode, api_key=settings.gemini_api_key,
            project=settings.google_cloud_project, location=settings.google_cloud_location,
            http_options=types.HttpOptions(
                timeout=settings.gemini_timeout_ms,
                retry_options=types.HttpRetryOptions(attempts=1),
            ),
        ).client

    configured = (
        settings.gemini_auth_mode == "api_key" and bool(settings.gemini_api_key.strip())
    ) or (
        settings.gemini_auth_mode == "vertex_ai"
        and bool(settings.google_cloud_project.strip())
        and bool(settings.google_cloud_location.strip())
    )
    return GeminiQuestionPlanner(
        client_factory=make_client, model=settings.gemini_model,
        enabled=settings.gemini_planner_enabled and settings.live_api_enabled,
        configured=configured,
        limiter=get_gemini_limiter(settings.requests_per_minute, settings.max_concurrent_requests),
        max_output_tokens=settings.gemini_max_output_tokens,
    )


@app.post("/api/v1/plan", response_model=PlanResponse)
def plan(
    request: PlanRequest, planner: Annotated[QuestionPlanner, Depends(get_question_planner)],
) -> PlanResponse:
    try:
        if request.mode == "live":
            require_live_source(route_question(request.question))
        if request.mode == "snapshot":
            require_snapshot()
        if request.conditions is not None:
            if request.conditions.selected_source != route_question(request.question):
                raise HTTPException(status_code=422, detail={
                    "code": "invalid_conditions", "message": "질문과 자료원이 달라졌습니다. "
                    "질문을 다시 분석해 주세요.", "field_errors": {},
                })
            result = plan_from_conditions(request.question, request.conditions, "snapshot")
            result.conditions_preserved = True
        else:
            result = create_plan(request.question, planner, request.mode)
        if request.mode == "snapshot" and result.query_plan.selected_source != "undetermined":
            result.snapshot = load_snapshot(result.query_plan.selected_source).metadata
        result.interpretation_method = request.interpretation_method
        result.interpretation_model = (
            settings.gemini_model if request.interpretation_method == "gemini" else None
        )
        return result
    except InvalidPlannerOutput:
        raise HTTPException(
            status_code=503,
            detail={
                "code": "invalid_planner_output",
                "message": (
                    "질문 해석 결과의 형식을 확인하지 못했습니다. "
                    "질문은 유지됩니다. ‘질문 분석’을 다시 눌러 주세요."
                ),
                "field_errors": {},
            },
        ) from None
    except PlannerUnavailable as exc:
        code, message, status = {
            PlannerDisabled: (
                "planner_disabled",
                "현재 Gemini 질문 해석이 꺼져 있습니다. "
                "모의 규칙을 선택하거나 운영자에게 문의해 주세요.",
                503,
            ),
            PlannerConfigurationError: (
                "planner_configuration_error",
                "Gemini 연결 설정을 확인해야 합니다. 운영자에게 문의해 주세요.", 503,
            ),
            PlannerRateLimited: (
                "planner_rate_limited",
                "Gemini 요청이 몰리거나 사용 한도에 도달했습니다. 잠시 후 다시 시도해 주세요.", 429,
            ),
            PlannerTimedOut: (
                "planner_timeout",
                "Gemini 응답을 기다리는 시간이 초과됐습니다. 잠시 후 다시 분석해 주세요.", 503,
            ),
        }.get(type(exc), (
            "planner_unavailable",
            "질문을 해석하지 못했습니다. 잠시 후 ‘질문 분석’을 다시 눌러 주세요.", 503,
        ))
        raise HTTPException(
            status_code=status,
            detail={
                "code": code, "message": message, "field_errors": {},
            },
        ) from None


@app.post("/api/v1/execute", response_model=ExecutionResponse)
async def execute(request: ExecuteRequest, http_request: Request) -> ExecutionResponse:
    try:
        if request.mode in ("live", "snapshot"):
            errors = validate_conditions(request.conditions, request.mode)
            if request.conditions.selected_source != route_question(request.question):
                errors["selected_source"] = (
                    "자료원과 질문이 달라졌습니다. 질문을 다시 해석해 주세요."
                )
            if errors:
                raise InvalidConditions(errors)
            if request.mode == "snapshot":
                require_snapshot()
                saved = load_snapshot(request.conditions.selected_source)
                if request.snapshot_id != saved.metadata.snapshot_id:
                    raise SnapshotError("snapshot_changed")
                if saved.employment is not None:
                    return compose_employment(
                        request.question, request.conditions,
                        select_employment(saved.employment, request.conditions),
                        snapshot=saved.metadata,
                    )
                return compose_financials(request.question, request.conditions, saved.revenue,
                                          snapshot=saved.metadata)
            require_live_source(request.conditions.selected_source)
            caches = http_request.app.state if settings.public_data_cache_enabled else None
            limiter = get_public_data_limiter(
                request.conditions.selected_source, settings.public_data_requests_per_minute,
                settings.public_data_max_concurrent_requests,
            )
            if request.conditions.selected_source == "kosis":
                return await execute_employment(request.question, request.conditions, lambda: (
                    KosisClient(settings.kosis_api_key, enabled=True, limiter=limiter)
                ), cache=caches.employment_cache if caches else None)
            return await execute_financials(request.question, request.conditions, lambda: (
                OpenDartClient(settings.opendart_api_key, enabled=True, limiter=limiter)
            ), cache=caches.revenue_cache if caches else None)
        return MockOrchestrator().execute(request.question, request.conditions)
    except PublicDataLimitError as exc:
        headers = {"Cache-Control": "no-store"}
        if exc.retry_after_seconds is not None:
            headers["Retry-After"] = str(exc.retry_after_seconds)
        raise HTTPException(status_code=429, headers=headers, detail={
            "code": exc.code, "message": str(exc), "field_errors": {},
            "source": exc.source, "scope": "process",
            "retry_after_seconds": exc.retry_after_seconds,
        }) from None
    except (OpenDartError, KosisError) as exc:
        provider = "kosis" if isinstance(exc, KosisError) else "opendart"
        raise HTTPException(
            status_code=429 if exc.code == "rate_limited" else 503,
            detail={"code": f"{provider}_{exc.code}", "message": str(exc), "field_errors": {}},
        ) from None
    except InvalidConditions as exc:
        raise HTTPException(
            status_code=422,
            detail={
                "code": "invalid_conditions",
                "message": str(exc),
                "field_errors": exc.field_errors,
            },
        ) from exc
    except CalculationDataError as exc:
        raise HTTPException(
            status_code=503,
            detail={
                "code": f"invalid_{request.mode}_data",
                "message": ("자료의 숫자나 단위를 검증하지 못해 계산을 중단했습니다."
                            if request.mode != "mock" else
                            "가상 자료의 숫자나 단위를 검증하지 못해 계산을 중단했습니다."),
                "field_errors": {},
            },
        ) from exc


def opendart_enabled() -> bool:
    return (settings.live_api_enabled and settings.public_data_mode == "live"
            and settings.opendart_enabled)


def require_opendart() -> None:
    code = "disabled" if not opendart_enabled() else (
        "configuration" if not settings.opendart_api_key.strip() else None
    )
    if code:
        raise HTTPException(status_code=503, detail={
            "code": f"opendart_{code}", "message": str(OpenDartError(code)), "field_errors": {},
        })


def kosis_enabled() -> bool:
    return (settings.live_api_enabled and settings.public_data_mode == "live"
            and settings.kosis_enabled)


def require_live_source(source: str) -> None:
    if source == "opendart":
        require_opendart()
    elif source == "kosis":
        code = "disabled" if not kosis_enabled() else (
            "configuration" if not settings.kosis_api_key.strip() else None
        )
        if code:
            raise HTTPException(status_code=503, detail={
                "code": f"kosis_{code}", "message": str(KosisError(code)), "field_errors": {},
            })
    elif not settings.live_api_enabled or settings.public_data_mode != "live":
        raise HTTPException(status_code=503, detail={
            "code": "live_disabled", "message": "공식 실제 자료 조회가 꺼져 있습니다.",
            "field_errors": {},
        })


def get_research_service(request: Request) -> ResearchService:
    from newsroom_agent.providers.opendart_research import OpenDartResearchClient

    def limiter(source):
        return get_public_data_limiter(source, settings.public_data_requests_per_minute,
                                       settings.public_data_max_concurrent_requests)

    def model(instruction, schema, briefing):
        planner = get_question_planner(PlanRequest(
            question="2부 실습", interpretation_method="gemini",
        ))
        planner.system_instruction = instruction
        planner.output_schema = schema
        planner.max_output_tokens = 4096 if briefing else settings.gemini_max_output_tokens
        if briefing:
            planner.enabled = settings.live_api_enabled and getattr(
                settings, "gemini_briefing_enabled", False,
            )
        return planner

    return ResearchService(
        dart=lambda: OpenDartResearchClient(settings.opendart_api_key, enabled=True,
                                            limiter=limiter("opendart")),
        kosis=lambda: KosisClient(settings.kosis_api_key, enabled=True, limiter=limiter("kosis")),
        model=model, require_source=require_live_source,
        metadata_cache=request.app.state.research_metadata_cache,
        data_cache=(request.app.state.research_data_cache
                    if settings.public_data_cache_enabled else None),
    )


async def research_call(operation):
    try:
        async with asyncio.timeout(None if flow.get() else 50):
            return await operation
    except TimeoutError:
        raise HTTPException(
            status_code=503,
            detail={
                "code": "research_timeout",
                "message": "조사 처리 시간이 길어 중단했습니다. "
                "조회 기간을 줄이거나 잠시 후 다시 승인해 주세요.",
                "field_errors": {},
            },
        ) from None
    except ResearchError as exc:
        raise HTTPException(
            status_code=422,
            detail={
                "code": "invalid_conditions",
                "message": str(exc),
                "field_errors": exc.field_errors,
            },
        ) from None
    except (OpenDartError, KosisError) as exc:
        provider = "kosis" if isinstance(exc, KosisError) else "opendart"
        message = str(exc)
        if isinstance(exc, OpenDartError) and exc.code in {
            "missing_account",
            "ambiguous_account",
            "missing_value",
            "invalid_amount",
        }:
            message = "선택한 재무 항목을 정확히 확인하지 못했습니다. 계정 누락·중복·금액을 "
            message += "공시 원문에서 확인하거나 지표·기간을 바꿔 다시 승인해 주세요."
        raise HTTPException(
            status_code=429 if exc.code == "rate_limited" else 503,
            detail={
                "code": f"{provider}_{exc.code}",
                "message": message,
                "field_errors": {},
            },
        ) from None
    except PublicDataLimitError as exc:
        raise HTTPException(
            status_code=429,
            detail={
                "code": exc.code,
                "message": str(exc),
                "field_errors": {},
                "retry_after_seconds": exc.retry_after_seconds,
            },
        ) from None
    except PlannerBillingError:
        raise HTTPException(
            503,
            detail={
                "code": "planner_billing",
                "message": ("Gemini 선불 잔액 또는 결제 설정 확인이 필요합니다. "
                    "반복 요청하지 말고 운영자에게 알려 주세요. "
                    "공식 저장 자료로 실습을 이어갈 수 있습니다."),
                "field_errors": {},
            },
        ) from None
    except (PlannerAuthenticationError, PlannerConfigurationError, PlannerDisabled):
        raise HTTPException(
            503,
            detail={
                "code": "planner_configuration_error",
                "message": ("Gemini 연결 설정이나 접근 권한 확인이 필요합니다. "
                    "운영자에게 알려 주세요. 입력은 유지됩니다."),
                "field_errors": {},
            },
        ) from None
    except PlannerRateLimited:
        raise HTTPException(
            429,
            detail={
                "code": "planner_rate_limited",
                "message": ("Gemini 공급자의 사용 한도에 도달했습니다. "
                    "잠시 후 다시 요청하거나 공식 저장 자료를 선택해 주세요. "
                    "계속되면 운영자에게 알려 주세요."),
                "field_errors": {},
            },
        ) from None
    except PlannerTimedOut:
        raise HTTPException(
            503,
            detail={
                "code": "planner_timeout",
                "message": ("Gemini 응답 시간이 길어 중단했습니다. "
                    "자동 재요청하지 않았습니다. 입력은 유지됩니다."),
                "field_errors": {},
            },
        ) from None
    except (PlannerUnavailable, InvalidPlannerOutput):
        raise HTTPException(
            status_code=503,
            detail={
                "code": "planner_unavailable",
                "message": "Gemini 조사 계획을 확인하지 못했습니다. "
                "설정·사용 한도를 확인하거나 잠시 후 다시 계획을 요청해 주세요. "
                ""
                "입력 내용은 유지됩니다.",
                "field_errors": {},
            },
        ) from None


@app.post("/api/v1/research/plan", response_model=ResearchPlanResponse)
async def research_plan(request: ResearchPlanRequest,
                        service: Annotated[ResearchService, Depends(get_research_service)]):
    return await research_call(service.plan(request))


@app.post("/api/v1/research/execute", response_model=ResearchExecutionResponse)
async def research_execute(request: ResearchExecuteRequest,
                           service: Annotated[ResearchService, Depends(get_research_service)]):
    return await research_call(service.execute(request))


# Participant event endpoints deliberately have no mock mode.


def get_event_service(request: Request):
    from newsroom_agent.providers.opendart_event import EventDartClient

    research = get_research_service(request)
    base_model = research.model

    def event_model(instruction, schema, briefing):
        model = base_model(instruction, schema, briefing)
        # Use the same bounded setting for planning and both comparison responses.
        # Gemini 2.x does not support thinking_level.
        if model.model.startswith("gemini-3"):
            model.thinking_level = "LOW"
        return model

    research.model = event_model
    research.dart = lambda: EventDartClient(
        settings.opendart_api_key,
        enabled=True,
        limiter=get_public_data_limiter(
            "opendart",
            settings.public_data_requests_per_minute,
            settings.public_data_max_concurrent_requests,
        ),
    )
    return EventService(research, settings.fallback_snapshot_enabled)


@app.get("/api/v1/event/catalog")
async def event_catalog():
    from newsroom_agent.event_catalog import (
        AGES,
        ENTITIES,
        PERIOD_NOTICE,
        disclosure_period_limits,
    )

    return {
        "snapshots": snapshot_catalog() if settings.fallback_snapshot_enabled else [],
        "entities": ENTITIES,
        "ages": list(AGES),
        "notice": PERIOD_NOTICE,
        "disclosure_period": disclosure_period_limits(),
    }


@app.post("/api/v1/event/plan", response_model=EventPlan)
async def event_plan(
    body: EventPlanRequest, service: Annotated[EventService, Depends(get_event_service)]
):
    return await research_call(service.plan(body))


@app.post("/api/v1/event/execute", response_model=EventResult)
async def event_execute(
    body: EventExecuteRequest, service: Annotated[EventService, Depends(get_event_service)]
):
    return await research_call(service.execute(body))


@app.post("/api/v1/event/general", response_model=GeneralResponse)
async def event_general(
    body: EventExecuteRequest, service: Annotated[EventService, Depends(get_event_service)]
):
    return await research_call(service.general(body))


@app.get("/api/v1/event/queue")
def event_queue(request: Request):
    return request.app.state.event_admission.status()


@app.post("/api/v1/event/plan/stream")
async def event_plan_stream(
    body: EventPlanRequest,
    request: Request,
    service: Annotated[EventService, Depends(get_event_service)],
):
    return request.app.state.event_admission.response(lambda: research_call(service.plan(body)))


@app.post("/api/v1/event/execute/stream")
async def event_execute_stream(
    body: EventExecuteRequest,
    request: Request,
    service: Annotated[EventService, Depends(get_event_service)],
):
    return request.app.state.event_admission.response(lambda: research_call(service.execute(body)))


@app.post("/api/v1/event/general/stream")
async def event_general_stream(
    body: EventExecuteRequest,
    request: Request,
    service: Annotated[EventService, Depends(get_event_service)],
):
    return request.app.state.event_admission.response(lambda: research_call(service.general(body)))


static_dir = Path("/app/static")
if static_dir.exists():
    assets_dir = static_dir / "assets"
    if assets_dir.exists():
        app.mount("/assets", StaticFiles(directory=assets_dir), name="assets")

    @app.get("/{full_path:path}", include_in_schema=False)
    def serve_frontend(full_path: str) -> FileResponse:
        candidate = static_dir / full_path
        if candidate.is_file() and static_dir in candidate.resolve().parents:
            return FileResponse(candidate)
        return FileResponse(static_dir / "index.html")


if __name__ == "__main__":
    import uvicorn

    uvicorn.run("newsroom_agent.main:app", host="0.0.0.0", port=8000, reload=True, access_log=False)
