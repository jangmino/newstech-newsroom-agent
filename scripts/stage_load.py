"""Bounded, manual stage load check. No dotenv, provider calls, retries or raw logs."""

from __future__ import annotations

import argparse
import asyncio
import copy
import json
import logging
import math
import re
import time
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path
from urllib.parse import urlsplit
from uuid import UUID

import httpx

QUESTIONS = {
    "kosis": "전국 시·도 15-29세 청년 고용률 2020-2024년 연간 증감 폭 비교",
    "opendart": "삼성전자 2022-2024년 연간 연결 매출액 증감 폭 비교",
}
SCENARIOS = tuple((mode, source) for mode in ("mock", "snapshot") for source in QUESTIONS)
CONDITION_FIELDS = ("selected_source", "entity", "metric", "period", "comparison", "filters")
RESULT_FIELDS = {"evidence", "brief", "calculation", "financial_calculation", "general_response"}
STAGES = (1, 5, 15, 30)
P95_LIMIT_MS = 2000


class CheckFailed(Exception):
    """Only fixed, non-sensitive reason codes may be supplied."""


def require(condition, reason):
    if not condition:
        raise CheckFailed(reason)


def validate_origin(value):
    parsed = urlsplit(value)
    require(
        parsed.scheme == "https" and bool(parsed.hostname)
        and parsed.username is None and parsed.password is None
        and parsed.path in ("", "/") and not parsed.query and not parsed.fragment
        and parsed.port in (None, 443),
        "https_origin_required",
    )
    return value.rstrip("/")


def percentile(values, fraction):
    return round(sorted(values)[max(0, math.ceil(len(values) * fraction) - 1)], 2)


def summarize(records):
    result = {}
    for label in sorted({row["label"] for row in records}):
        rows = [row for row in records if row["label"] == label]
        durations = [row["duration_ms"] for row in rows]
        result[label] = {
            "requests": len(rows),
            "statuses": dict(Counter(str(row["status"]) for row in rows)),
            "unexpected": sum(row["status"] not in (row["expected"], "cancelled") for row in rows),
            "cancelled": sum(row["status"] == "cancelled" for row in rows),
            "p50_ms": percentile(durations, 0.5),
            "p95_ms": percentile(durations, 0.95),
            "max_ms": round(max(durations), 2),
        }
    return result


class LoadCheck:
    def __init__(self, client, code, *, pause=0.25, deadline=120):
        self.client = client
        self.code = code
        self.pause = pause
        self.deadline = deadline
        self.records = []
        self.request_ids = set()
        self.inflight = 0
        self.peak = 0
        self.completed = Counter()

    async def request(self, label, method, path, *, body=None, expected=200, authenticated=True):
        start = time.perf_counter()
        self.inflight += 1
        self.peak = max(self.peak, self.inflight)
        row = {"label": label, "expected": expected, "status": "transport_error"}
        try:
            # No default authentication headers: the no-code probe must really omit the code.
            headers = {"X-Workshop-Code": self.code} if authenticated else {}
            async with asyncio.timeout(15):
                response = await self.client.request(method, path, json=body, headers=headers)
            row["status"] = response.status_code
            require(response.status_code == expected, "unexpected_http_status")
            request_id = response.headers.get("X-Request-ID", "")
            require(UUID(request_id).version == 4, "invalid_request_id")
            require(request_id not in self.request_ids, "duplicate_request_id")
            self.request_ids.add(request_id)
            payload = response.json()
            require(isinstance(payload, dict), "invalid_json_object")
            if "request_id" in payload:
                require(payload["request_id"] == request_id, "request_id_mismatch")
            if expected != 200:
                require(not RESULT_FIELDS.intersection(payload), "result_before_approval")
            return payload
        except (httpx.HTTPError, TimeoutError):
            raise CheckFailed("transport_or_timeout") from None
        except (ValueError, KeyError, TypeError):
            raise CheckFailed("invalid_response_contract") from None
        except asyncio.CancelledError:
            row["status"] = "cancelled"
            raise
        finally:
            row["duration_ms"] = (time.perf_counter() - start) * 1000
            self.records.append(row)
            self.inflight -= 1

    async def operations(self, label):
        status = await self.request(label, "GET", "/api/v1/operations")
        require(status.get("external_calls_made") is False, "unsafe_operations_status")
        require(status.get("providers") == dict.fromkeys(QUESTIONS.keys() | {"gemini"}, "disabled"),
                "live_provider_enabled")
        for source in QUESTIONS:
            require(status.get("snapshots", {}).get(source, {}).get("status") == "available",
                    "snapshot_unavailable")

    async def plan(self, mode, source, label):
        payload = await self.request(label, "POST", "/api/v1/plan", body={
            "question": QUESTIONS[source], "mode": mode, "interpretation_method": "mock_rules",
        })
        require(not RESULT_FIELDS.intersection(payload), "result_before_approval")
        require(payload["data_mode"] == mode and payload["interpretation_method"] == "mock_rules",
                "unexpected_plan_mode")
        plan = payload["query_plan"]
        require(plan["selected_source"] == source and plan["clarification_required"] is False
                and plan["comparison"] == "증감 폭"
                and payload["required_fields"] == [], "unexpected_plan_conditions")
        body = {"question": QUESTIONS[source], "mode": mode, "approved": True,
                "conditions": {key: copy.deepcopy(plan[key]) for key in CONDITION_FIELDS}}
        if mode == "snapshot":
            require(payload["snapshot"]["source"] == source, "snapshot_source_mismatch")
            body["snapshot_id"] = payload["snapshot"]["snapshot_id"]
        return payload, body

    async def execute(self, body, plan):
        result = await self.request("load.execute", "POST", "/api/v1/execute", body=body)
        conditions = body["conditions"]
        evidence = result["evidence"]
        require(result["question"] == body["question"], "question_mismatch")
        require(result["brief"]["verification_status"] == "review_required",
                "review_status_changed")
        require(evidence["data_mode"] == body["mode"] and result["cache"] is None,
                "unexpected_result_mode")
        require(all(evidence[field] for field in ("source_name", "retrieved_at", "unit", "formula",
                                                  "caveats")), "missing_evidence_metadata")
        for field, value in conditions.items():
            require(result["query_plan"][field] == value, "approved_conditions_mismatch")
            if field == "filters":
                for key, setting in value.items():
                    require(evidence["query_parameters"][f"filters.{key}"] == setting,
                            "evidence_conditions_mismatch")
            else:
                require(evidence["query_parameters"][field] == value,
                        "evidence_conditions_mismatch")
        if body["mode"] == "snapshot":
            require(result["snapshot"] == plan["snapshot"], "snapshot_version_mismatch")
            require(evidence["retrieved_at"] == plan["snapshot"]["captured_at"],
                    "snapshot_timestamp_changed")

    async def participant(self, index):
        state = await self.request("load.access_get", "GET", "/api/v1/access", authenticated=False)
        require(state == {"required": True, "available": True}, "unsafe_access_status")
        state = await self.request("load.access_post", "POST", "/api/v1/access")
        require(state == {"required": True, "available": True}, "unsafe_access_status")
        # Rotate scenarios so simultaneous participants exercise both sources and modes.
        for offset in range(len(SCENARIOS)):
            mode, source = SCENARIOS[(index + offset) % len(SCENARIOS)]
            plan, body = await self.plan(mode, source, "load.plan")
            await asyncio.sleep(self.pause)
            await self.execute(body, plan)
            body["conditions"]["comparison"] = "증감률"
            await asyncio.sleep(self.pause)
            await self.execute(body, plan)
            self.completed[f"{mode}.{source}"] += 1

    async def preflight(self):
        health = await self.request("guard.health", "GET", "/health", authenticated=False)
        require(health.get("environment") == "stage" and health.get("public_data_mode") == "mock"
                and health.get("live_api_enabled") is False, "unsafe_stage_settings")
        state = await self.request("guard.access", "GET", "/api/v1/access", authenticated=False)
        require(state == {"required": True, "available": True}, "unsafe_access_status")
        await self.request("guard.unauthorized", "GET", "/api/v1/operations",
                           authenticated=False, expected=401)
        await self.operations("guard.operations_before")
        for mode, source in SCENARIOS:
            _, body = await self.plan(mode, source, "guard.plan")
            body["approved"] = False
            await self.request("guard.unapproved", "POST", "/api/v1/execute",
                               body=body, expected=422)

    async def run(self, users):
        require(isinstance(users, int) and not isinstance(users, bool) and 1 <= users <= 30,
                "users_out_of_bounds")
        start = time.perf_counter()
        failure = None
        tasks = []
        try:
            async with asyncio.timeout(self.deadline):
                await self.preflight()
                tasks = [asyncio.create_task(self.participant(index)) for index in range(users)]
                await asyncio.gather(*tasks)
                await self.operations("guard.operations_after")
        except CheckFailed as exc:
            failure = str(exc)
        except (ValueError, KeyError, TypeError, AttributeError):
            failure = "invalid_response_contract"
        except TimeoutError:
            failure = "stage_deadline"
        finally:
            for task in tasks:
                if not task.done():
                    task.cancel()
            await asyncio.gather(*tasks, return_exceptions=True)
        metrics = summarize(self.records)
        if failure is None and any(metrics[label]["p95_ms"] > P95_LIMIT_MS
                                   for label in ("load.plan", "load.execute")):
            failure = "p95_above_target"
        return {
            "users": users, "passed": failure is None, "failure": failure,
            "elapsed_seconds": round(time.perf_counter() - start, 2),
            "peak_client_requests": self.peak, "completed_flows": dict(self.completed),
            "expected_flows": users * len(SCENARIOS), "http_requests": len(self.records),
            "metrics": metrics,
        }


async def run_suite(origin, code, *, stages=STAGES, transport=None, pause=0.25, deadline=120):
    origin = validate_origin(origin)
    require(re.fullmatch(r"[A-Za-z0-9_-]{16,128}", code) is not None, "invalid_access_code_file")
    require(bool(stages) and all(type(n) is int and 1 <= n <= 30 for n in stages)
            and list(stages) == sorted(set(stages)) and len(stages) <= 4, "invalid_stages")
    report = {"started_at": datetime.now(UTC).isoformat(), "passed": False,
              "profile": "mock_snapshot_4_flows_2_approvals", "p95_target_ms": P95_LIMIT_MS,
              "pause_seconds": pause, "request_deadline_seconds": 15,
              "stage_deadline_seconds": deadline, "stages": []}
    # One reusable pool, up to one pending request per virtual participant, HTTP/1.1.
    async with httpx.AsyncClient(base_url=origin, transport=transport, trust_env=False,
                                 follow_redirects=False, timeout=15,
                                 limits=httpx.Limits(max_connections=30,
                                                    max_keepalive_connections=30)) as client:
        for users in stages:
            result = await LoadCheck(client, code, pause=pause, deadline=deadline).run(users)
            report["stages"].append(result)
            if not result["passed"]:
                break
    report["passed"] = len(report["stages"]) == len(stages) and all(
        stage["passed"] for stage in report["stages"])
    report["http_requests"] = sum(stage["http_requests"] for stage in report["stages"])
    return report


def main():
    parser = argparse.ArgumentParser(description="승인된 stage의 1→5→15→30명 mock/저장 자료 시험")
    parser.add_argument("--base-url", required=True, help="stage HTTPS origin; no path or query")
    parser.add_argument("--access-code-file", type=Path, required=True)
    parser.add_argument("--report", type=Path, required=True, help="new local JSON file")
    args = parser.parse_args()
    logging.getLogger("httpx").disabled = True
    logging.getLogger("httpcore").disabled = True
    try:
        require(not args.report.exists(), "report_already_exists")
        require(args.access_code_file.stat().st_mode & 0o077 == 0, "access_code_file_permissions")
        code = args.access_code_file.read_text().strip()
        report = asyncio.run(run_suite(args.base_url, code))
        with args.report.open("x") as output:
            output.write(json.dumps(report, ensure_ascii=False, indent=2) + "\n")
        print(json.dumps(report, ensure_ascii=False, indent=2))
        return 0 if report["passed"] else 1
    except (CheckFailed, OSError, ValueError):
        print("시험을 시작하거나 기록하지 못했습니다. URL·파일 경로·권한·기존 보고서를 확인하세요.")
        return 2
    except KeyboardInterrupt:
        print("사용자가 시험을 중단했습니다.")
        return 130


if __name__ == "__main__":
    raise SystemExit(main())
