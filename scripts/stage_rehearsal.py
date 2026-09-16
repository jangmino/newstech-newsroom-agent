"""Manual fallback rehearsal against a stage whose live providers are already OFF."""

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


async def run_rehearsal(origin, code, *, transport=None):
    origin = validate_origin(origin)
    require(re.fullmatch(r"[A-Za-z0-9_-]{16,128}", code) is not None, "invalid_access_code_file")
    report = {"started_at": datetime.now(UTC).isoformat(), "passed": False,
              "profile": "live_disabled_to_explicit_snapshot", "completed_sources": [],
              "failure": None}
    async with httpx.AsyncClient(base_url=origin, transport=transport, trust_env=False,
                                 follow_redirects=False, timeout=15) as client:
        check = LoadCheck(client, code)
        try:
            async with asyncio.timeout(90):
                # Must pass BEFORE sending any mode=live body. No cloud settings are changed.
                await check.preflight()
                for source, question in QUESTIONS.items():
                    _, base = await check.plan("mock", source, "drill.conditions")
                    conditions = copy.deepcopy(base["conditions"])
                    conditions["comparison"] = "증감률"
                    if source == "kosis":
                        conditions.update(entity="수도권 시·도", period="2021-2024")
                    live_body = {"question": question, "mode": "live", "approved": True,
                                 "conditions": conditions}
                    for path, body in (
                        ("/api/v1/plan", {"question": question, "mode": "live",
                                          "interpretation_method": "mock_rules"}),
                        ("/api/v1/execute", live_body),
                    ):
                        blocked = await check.request("drill.live_disabled", "POST", path,
                                                      body=body, expected=503)
                        require(blocked["detail"]["code"] == f"{source}_disabled",
                                "unexpected_live_error")
                    preview = await check.request("drill.snapshot_preview", "POST", "/api/v1/plan",
                                                  body={"question": question, "mode": "snapshot",
                                                        "interpretation_method": "mock_rules",
                                                        "conditions": conditions})
                    require(not RESULT_FIELDS.intersection(preview), "result_before_approval")
                    require(preview["data_mode"] == "snapshot" and preview["conditions_preserved"]
                            and preview["interpretation_method"] == "mock_rules"
                            and not preview["required_fields"], "invalid_snapshot_preview")
                    require({key: preview["query_plan"][key] for key in CONDITION_FIELDS}
                            == conditions, "preserved_conditions_mismatch")
                    body = {**live_body, "mode": "snapshot",
                            "snapshot_id": preview["snapshot"]["snapshot_id"]}
                    await check.request("drill.unapproved", "POST", "/api/v1/execute",
                                        body={**body, "approved": False}, expected=422)
                    stale = await check.request(
                        "drill.stale_snapshot", "POST", "/api/v1/execute",
                        body={**body, "snapshot_id": "rehearsal-old-version"}, expected=409,
                    )
                    require(stale["detail"]["code"] == "snapshot_changed",
                            "unexpected_version_error")
                    await check.execute(body, preview)
                    report["completed_sources"].append(source)
                await check.operations("guard.operations_after")
                report["passed"] = True
        except CheckFailed as exc:
            report["failure"] = str(exc)
        except (ValueError, KeyError, TypeError, AttributeError):
            report["failure"] = "invalid_response_contract"
        except TimeoutError:
            report["failure"] = "rehearsal_deadline"
        report["http_requests"] = len(check.records)
        report["metrics"] = summarize(check.records)
    return report


def main():
    parser = argparse.ArgumentParser(description="live off stage의 실패·저장 자료 재승인 점검")
    parser.add_argument("--base-url", required=True)
    parser.add_argument("--access-code-file", type=Path, required=True)
    parser.add_argument("--report", type=Path, required=True)
    args = parser.parse_args()
    logging.getLogger("httpx").disabled = True
    logging.getLogger("httpcore").disabled = True
    try:
        require(not args.report.exists(), "report_already_exists")
        require(args.access_code_file.stat().st_mode & 0o077 == 0, "access_code_file_permissions")
        code = args.access_code_file.read_text().strip()
        report = asyncio.run(run_rehearsal(args.base_url, code))
        with args.report.open("x") as output:
            output.write(json.dumps(report, ensure_ascii=False, indent=2) + "\n")
        print(json.dumps(report, ensure_ascii=False, indent=2))
        return 0 if report["passed"] else 1
    except (CheckFailed, OSError, ValueError):
        print("리허설을 시작하거나 기록하지 못했습니다. URL·파일 경로·권한을 확인하세요.")
        return 2
    except KeyboardInterrupt:
        print("사용자가 리허설을 중단했습니다.")
        return 130


if __name__ == "__main__":
    raise SystemExit(main())
