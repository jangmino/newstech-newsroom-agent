from pathlib import Path
from typing import Annotated

from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.exception_handlers import request_validation_exception_handler
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from newsroom_agent.calculations import CalculationDataError
from newsroom_agent.config import get_settings
from newsroom_agent.models import (
    AnalysisRequest,
    AnalysisResponse,
    ExecuteRequest,
    ExecutionResponse,
    PlanRequest,
    PlanResponse,
)
from newsroom_agent.orchestrator import InvalidConditions, MockOrchestrator
from newsroom_agent.planning import InvalidPlannerOutput
from newsroom_agent.providers.mock_planner import MockQuestionPlanner
from newsroom_agent.providers.planner import PlannerUnavailable, QuestionPlanner

settings = get_settings()
app = FastAPI(title="NewsTech Newsroom Agent API", version="0.1.0")
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
        "mode": "이번 실습에서는 모의 자료 모드만 사용할 수 있습니다.",
        "approved": "조건을 확인한 뒤 ‘이 조건으로 조회’를 눌러 주세요.",
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


def get_question_planner() -> QuestionPlanner:
    # Deliberately independent of credentials and live settings in this slice.
    return MockQuestionPlanner()


@app.post("/api/v1/plan", response_model=PlanResponse)
def plan(
    request: PlanRequest, planner: Annotated[QuestionPlanner, Depends(get_question_planner)],
) -> PlanResponse:
    try:
        return MockOrchestrator(planner).plan(request.question)
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
    except PlannerUnavailable:
        raise HTTPException(
            status_code=503,
            detail={
                "code": "planner_unavailable",
                "message": "질문을 해석하지 못했습니다. 잠시 후 ‘질문 분석’을 다시 눌러 주세요.",
                "field_errors": {},
            },
        ) from None


@app.post("/api/v1/execute", response_model=ExecutionResponse)
def execute(request: ExecuteRequest) -> ExecutionResponse:
    try:
        return MockOrchestrator().execute(request.question, request.conditions)
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
                "code": "invalid_mock_data",
                "message": "가상 자료의 숫자나 단위를 검증하지 못해 계산을 중단했습니다.",
                "field_errors": {},
            },
        ) from exc


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
