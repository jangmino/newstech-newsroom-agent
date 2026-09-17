"""Opt-in, sequential live stage smoke; two Gemini plans, no retries or raw reports."""

from __future__ import annotations

import argparse
import asyncio
import copy
import json
import logging
import re
from datetime import UTC, datetime
from pathlib import Path

import httpx
from stage_load import (
    CONDITION_FIELDS,
    QUESTIONS,
    RESULT_FIELDS,
    CheckFailed,
    LoadCheck,
    require,
    summarize,
    validate_origin,
)

EXPECTED_CONDITIONS = {
    "kosis": {"selected_source": "kosis", "entity": "전국 시·도", "metric": "고용률",
              "period": "2020-2024", "comparison": "증감 폭",
              "filters": {"age_range": "15-29세", "frequency": "연간"}},
    "opendart": {"selected_source": "opendart", "entity": "삼성전자", "metric": "매출액",
                 "period": "2022-2024", "comparison": "증감 폭",
                 "filters": {"statement_basis": "연결", "report_type": "연간"}},
}


async def live_status(check, label):
    status = await check.request(label, "GET", "/api/v1/operations")
    require(status.get("external_calls_made") is False, "unsafe_operations_status")
    require(status.get("providers") == dict.fromkeys((*QUESTIONS, "gemini"), "configured"),
            "providers_not_configured")
    require(status.get("cache", {}).get("enabled") is True, "cache_required")
    for source in QUESTIONS:
        require(status.get("snapshots", {}).get(source, {}).get("status") == "available",
                "snapshot_unavailable")


def validate_result(result, body):
    evidence = result["evidence"]
    require(result["question"] == body["question"], "question_mismatch")
    require(result["brief"]["verification_status"] == "review_required", "review_status_changed")
    require(evidence["data_mode"] == "live" and result["snapshot"] is None,
            "unexpected_result_mode")
    require(result["cache"]["status"] in ("miss", "hit", "coalesced"), "invalid_cache_status")
    require(all(evidence[field] for field in (
        "source_name", "retrieved_at", "unit", "formula", "caveats", "raw_values",
    )), "missing_evidence_metadata")
    for field, value in body["conditions"].items():
        require(result["query_plan"][field] == value, "approved_conditions_mismatch")
        if field == "filters":
            for key, setting in value.items():
                require(evidence["query_parameters"][f"filters.{key}"] == setting,
                        "evidence_conditions_mismatch")
        else:
            require(evidence["query_parameters"][field] == value, "evidence_conditions_mismatch")
    source = body["conditions"]["selected_source"]
    calculation = result["calculation" if source == "kosis" else "financial_calculation"]
    require(calculation["data_origin"] == source, "calculation_source_mismatch")
    require(result["general_response"]["data_mode"] == "mock", "general_example_changed")


async def run_live(origin, code, *, transport=None):
    origin = validate_origin(origin)
    require(re.fullmatch(r"[A-Za-z0-9_-]{16,128}", code) is not None, "invalid_access_code_file")
    report = {"started_at": datetime.now(UTC).isoformat(), "passed": False,
              "profile": "gemini_live_two_questions", "completed_sources": [], "failure": None,
              "gemini_plan_attempts": 0, "live_execution_attempts": dict.fromkeys(QUESTIONS, 0),
              "cache_statuses": {}, "request_ids": []}
    async with httpx.AsyncClient(base_url=origin, transport=transport, trust_env=False,
                                 follow_redirects=False, timeout=55) as client:
        check = LoadCheck(client, code, request_timeout=55)
        try:
            async with asyncio.timeout(240):
                health = await check.request("guard.health", "GET", "/health", authenticated=False)
                require(health.get("environment") == "stage"
                        and health.get("public_data_mode") == "live"
                        and health.get("live_api_enabled") is True, "unsafe_stage_settings")
                access = await check.request("guard.access", "GET", "/api/v1/access",
                                             authenticated=False)
                require(access == {"required": True, "available": True}, "unsafe_access_status")
                await check.request("guard.unauthorized", "GET", "/api/v1/operations",
                                    authenticated=False, expected=401)
                await live_status(check, "guard.operations_before")
                for source, question in QUESTIONS.items():
                    report["gemini_plan_attempts"] += 1
                    plan = await check.request("live.plan", "POST", "/api/v1/plan", body={
                        "question": question, "mode": "live", "interpretation_method": "gemini",
                    })
                    require(not RESULT_FIELDS.intersection(plan), "result_before_approval")
                    require(plan["data_mode"] == "live"
                            and plan["interpretation_method"] == "gemini"
                            and bool(plan["interpretation_model"]), "unexpected_plan_mode")
                    require(plan["query_plan"]["selected_source"] == source
                            and not plan["query_plan"]["clarification_required"]
                            and plan["required_fields"] == [], "unexpected_plan_conditions")
                    conditions = {key: copy.deepcopy(plan["query_plan"][key])
                                  for key in CONDITION_FIELDS}
                    require(conditions == EXPECTED_CONDITIONS[source], "unexpected_plan_conditions")
                    conditions["comparison"] = "증감률"
                    if source == "kosis":
                        conditions.update(entity="수도권 시·도", period="2021-2024")
                    body = {"question": question, "mode": "live", "conditions": conditions,
                            "approved": True}
                    await check.request("live.unapproved", "POST", "/api/v1/execute",
                                        body={**body, "approved": False}, expected=422)
                    report["live_execution_attempts"][source] += 1
                    first = await check.request("live.execute", "POST", "/api/v1/execute",
                                                body=body)
                    validate_result(first, body)
                    conditions["comparison"] = "증감 폭"
                    report["live_execution_attempts"][source] += 1
                    second = await check.request("live.reapprove", "POST", "/api/v1/execute",
                                                 body=body)
                    validate_result(second, body)
                    original, reused = first["evidence"], second["evidence"]
                    require(second["cache"]["status"] == "hit"
                            and original["retrieved_at"] == reused["retrieved_at"]
                            and original["raw_values"] == reused["raw_values"],
                            "cache_reuse_mismatch")
                    report["cache_statuses"][source] = [first["cache"]["status"], "hit"]
                    # Explicit snapshot selection verifies fallback readiness without provoking
                    # provider outages. No Gemini reinterpretation or automatic fallback occurs.
                    preview = await check.request("saved.plan", "POST", "/api/v1/plan", body={
                        "question": question, "mode": "snapshot", "conditions": conditions,
                        "interpretation_method": "mock_rules",
                    })
                    require(not RESULT_FIELDS.intersection(preview), "result_before_approval")
                    require(preview["conditions_preserved"] and preview["data_mode"] == "snapshot",
                            "invalid_snapshot_preview")
                    require({key: preview["query_plan"][key] for key in CONDITION_FIELDS}
                            == conditions, "preserved_conditions_mismatch")
                    saved = {**body, "mode": "snapshot",
                             "snapshot_id": preview["snapshot"]["snapshot_id"]}
                    await check.request("saved.unapproved", "POST", "/api/v1/execute",
                                        body={**saved, "approved": False}, expected=422)
                    await check.execute(saved, preview)
                    report["completed_sources"].append(source)
                await live_status(check, "guard.operations_after")
                report["passed"] = True
        except CheckFailed as exc:
            report["failure"] = str(exc)
        except (ValueError, KeyError, TypeError, AttributeError):
            report["failure"] = "invalid_response_contract"
        except TimeoutError:
            report["failure"] = "live_check_deadline"
        report["http_requests"] = len(check.records)
        report["metrics"] = summarize(check.records)
        report["request_ids"] = sorted(check.request_ids)
    return report


def main():
    parser = argparse.ArgumentParser(description="승인된 stage의 Gemini+공식 실제 자료 소규모 확인")
    parser.add_argument("--base-url", required=True)
    parser.add_argument("--access-code-file", type=Path, required=True)
    parser.add_argument("--report", type=Path, required=True)
    parser.add_argument("--allow-live", action="store_true", required=True)
    args = parser.parse_args()
    logging.getLogger("httpx").disabled = True
    logging.getLogger("httpcore").disabled = True
    try:
        require(not args.report.exists(), "report_already_exists")
        require(args.access_code_file.stat().st_mode & 0o077 == 0, "access_code_file_permissions")
        report = asyncio.run(run_live(args.base_url, args.access_code_file.read_text().strip()))
        with args.report.open("x") as output:
            output.write(json.dumps(report, ensure_ascii=False, indent=2) + "\n")
        print(json.dumps(report, ensure_ascii=False, indent=2))
        return 0 if report["passed"] else 1
    except (CheckFailed, OSError, ValueError):
        print("실제 확인을 시작하거나 기록하지 못했습니다. URL·파일·권한을 확인하세요.")
        return 2
    except KeyboardInterrupt:
        print("사용자가 실제 확인을 중단했습니다.")
        return 130


if __name__ == "__main__":
    raise SystemExit(main())
