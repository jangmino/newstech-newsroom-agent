from contextlib import asynccontextmanager
from functools import lru_cache
from pathlib import Path
from typing import Annotated

from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.exception_handlers import request_validation_exception_handler
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from newsroom_agent.calculations import CalculationDataError
from newsroom_agent.conditions import route_question, validate_conditions
from newsroom_agent.config import get_settings
from newsroom_agent.live_employment import execute_employment
from newsroom_agent.live_financials import execute_financials
from newsroom_agent.models import (
    AnalysisRequest,
    AnalysisResponse,
    ExecuteRequest,
    ExecutionResponse,
    PlanRequest,
    PlanResponse,
)
from newsroom_agent.orchestrator import InvalidConditions, MockOrchestrator
from newsroom_agent.planning import InvalidPlannerOutput, create_plan
from newsroom_agent.providers.kosis import KosisClient
from newsroom_agent.providers.kosis_employment import EmploymentSeries, KosisError
from newsroom_agent.providers.mock_planner import MockQuestionPlanner
from newsroom_agent.providers.opendart import OpenDartClient
from newsroom_agent.providers.opendart_financials import OpenDartError, RevenuePair
from newsroom_agent.providers.planner import (
    PlannerConfigurationError,
    PlannerDisabled,
    PlannerRateLimited,
    PlannerTimedOut,
    PlannerUnavailable,
    QuestionPlanner,
)
from newsroom_agent.public_data_cache import PublicDataCache

settings = get_settings()


@asynccontextmanager
async def lifespan(app: FastAPI):
    app.state.employment_cache = PublicDataCache[EmploymentSeries](
        settings.cache_ttl_seconds, settings.cache_max_entries,
    )
    app.state.revenue_cache = PublicDataCache[RevenuePair](
        settings.cache_ttl_seconds, settings.cache_max_entries,
    )
    try:
        yield
    finally:
        await app.state.employment_cache.close()
        await app.state.revenue_cache.close()


app = FastAPI(title="NewsTech Newsroom Agent API", version="0.1.0", lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origin_list,
    allow_credentials=False,
    allow_methods=["GET", "POST"],
    allow_headers=["Content-Type", "X-Workshop-Code"],
)


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
    if request.url.path not in {"/api/v1/plan", "/api/v1/execute"}:
        return await request_validation_exception_handler(request, exc)
    messages = {
        "question": "질문을 3자 이상 1,000자 이하로 입력해 주세요.",
        "mode": "모의 자료 또는 공식 실제 자료 모드를 선택해 주세요.",
        "approved": "조건을 확인한 뒤 ‘이 조건으로 조회’를 눌러 주세요.",
        "interpretation_method": "모의 규칙 또는 Gemini 중 질문 해석 방식을 선택해 주세요.",
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
        result = create_plan(request.question, planner, request.mode)
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
        if request.mode == "live":
            errors = validate_conditions(request.conditions, "live")
            if request.conditions.selected_source != route_question(request.question):
                errors["selected_source"] = (
                    "자료원과 질문이 달라졌습니다. 질문을 다시 해석해 주세요."
                )
            if errors:
                raise InvalidConditions(errors)
            require_live_source(request.conditions.selected_source)
            caches = http_request.app.state if settings.public_data_cache_enabled else None
            if request.conditions.selected_source == "kosis":
                return await execute_employment(request.question, request.conditions, lambda: (
                    KosisClient(settings.kosis_api_key, enabled=True)
                ), cache=caches.employment_cache if caches else None)
            return await execute_financials(request.question, request.conditions, lambda: (
                OpenDartClient(settings.opendart_api_key, enabled=True)
            ), cache=caches.revenue_cache if caches else None)
        return MockOrchestrator().execute(request.question, request.conditions)
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
                "code": "invalid_live_data" if request.mode == "live" else "invalid_mock_data",
                "message": ("자료의 숫자나 단위를 검증하지 못해 계산을 중단했습니다."
                            if request.mode == "live" else
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

    uvicorn.run("newsroom_agent.main:app", host="0.0.0.0", port=8000, reload=True)
