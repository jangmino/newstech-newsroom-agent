"""Operator-only event rehearsal. Explicit opt-in, fixed call budget, no automatic retries."""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import time
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path

import httpx
from stage_load import CheckFailed, LoadCheck, require, summarize, validate_origin

SNAPSHOTS = (
    Path(__file__).resolve().parents[1] / "apps/api/src/newsroom_agent/event_snapshots"
)


async def run(origin, code, users, interval):
    report = {
        "started_at": datetime.now(UTC).isoformat(),
        "users": users,
        "interval_seconds": interval,
        "gemini_call_budget": users * 3,
        "profile": "paced_operator_simulation_not_real_attendees",
        "passed": False,
        "completed": 0,
        "briefs": {},
        "cache": {},
        "failure": None,
    }
    cases = [
        json.loads((SNAPSHOTS / f"{name}.json").read_text())["result"]
        for name in ("seoul", "finance", "ranking", "disclosures")
    ]
    briefs, caches = Counter(), Counter()
    started = time.monotonic()
    async with httpx.AsyncClient(
        base_url=validate_origin(origin),
        trust_env=False,
        follow_redirects=False,
        timeout=55,
    ) as client:
        check = LoadCheck(client, code, request_timeout=55)
        try:
            await check.request(
                "guard.unauthorized",
                "GET",
                "/api/v1/event/catalog",
                authenticated=False,
                expected=401,
            )
            catalog = await check.request(
                "guard.catalog", "GET", "/api/v1/event/catalog"
            )
            require(len(catalog["snapshots"]) == 4, "missing_snapshots")
            for index in range(users):
                await asyncio.sleep(
                    max(0, index * interval - (time.monotonic() - started))
                )
                case = cases[index % len(cases)]
                plan = await check.request(
                    "live.plan",
                    "POST",
                    "/api/v1/event/plan",
                    body={"question": case["question"]},
                )
                require(
                    not {"facts", "brief"} & plan.keys(), "evidence_before_approval"
                )
                require(not plan["field_errors"].get("scope"), "unsupported_core_case")
                # The operator explicitly approves the fixed, source-checked fixture conditions.
                # Any planner differences are recorded as edits, never silently accepted.
                body = {
                    "question": case["question"],
                    "conditions": case["conditions"],
                    "approved": True,
                    "mode": "live",
                }
                result = await check.request(
                    "live.execute", "POST", "/api/v1/event/execute", body=body
                )
                require(
                    result["conditions"] == body["conditions"], "conditions_mismatch"
                )
                require(
                    result["data_mode"] == "live" and bool(result["facts"]),
                    "missing_live_facts",
                )
                require(
                    all(
                        f["source_urls"] and f["retrieved_at"] and f["unit"]
                        for f in result["facts"]
                    ),
                    "missing_provenance",
                )
                briefs[result["brief"]["status"]] += 1
                caches[(result.get("cache") or {}).get("status", "none")] += 1
                if result["brief"]["status"] != "complete":
                    require(
                        bool(result["brief"]["error"]), "missing_brief_failure_notice"
                    )
                general = await check.request(
                    "live.general", "POST", "/api/v1/event/general", body=body
                )
                require(
                    general["conditions"] == body["conditions"]
                    and general["tools"] == []
                    and bool(general["text"]),
                    "invalid_general_comparison",
                )
                report["completed"] += 1
                print(
                    json.dumps(
                        {
                            "participant": index + 1,
                            "brief": result["brief"]["status"],
                            "edited_plan": plan["conditions"] != body["conditions"],
                            "elapsed_s": round(time.monotonic() - started, 1),
                        }
                    ),
                    flush=True,
                )
            # Official replay and mismatch errors use no providers.
            for item in catalog["snapshots"]:
                body = {
                    "question": item["question"],
                    "conditions": item["conditions"],
                    "approved": True,
                    "mode": "snapshot",
                    "snapshot_id": item["id"],
                }
                result = await check.request(
                    "snapshot.execute", "POST", "/api/v1/event/execute", body=body
                )
                require(
                    result["data_mode"] == "snapshot"
                    and result["brief"]["status"] == "complete",
                    "invalid_snapshot",
                )
                await check.request(
                    "snapshot.general", "POST", "/api/v1/event/general", body=body
                )
                await check.request(
                    "guard.unapproved",
                    "POST",
                    "/api/v1/event/execute",
                    body=body | {"approved": False},
                    expected=422,
                )
            report["passed"] = True
        except CheckFailed as exc:
            report["failure"] = str(exc)
        finally:
            report.update(
                briefs=dict(briefs),
                cache=dict(caches),
                duration_s=round(time.monotonic() - started, 2),
                requests=summarize(check.records),
                request_ids=sorted(check.request_ids),
            )
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--origin", required=True)
    parser.add_argument("--access-code-file", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--users", type=int, choices=range(1, 31), default=4)
    parser.add_argument("--interval", type=int, default=20)
    parser.add_argument("--execute-live", action="store_true")
    args = parser.parse_args()
    if not args.execute_live or args.interval < 20 or args.output.exists():
        parser.error(
            "Explicit --execute-live, interval >=20 and a new output path required"
        )
    logging.disable(logging.CRITICAL)
    try:
        report = asyncio.run(
            run(
                args.origin,
                args.access_code_file.read_text().strip(),
                args.users,
                args.interval,
            )
        )
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2))
        print(
            json.dumps(
                {k: report[k] for k in ("passed", "completed", "briefs", "failure")}
            )
        )
        raise SystemExit(0 if report["passed"] else 1)
    except (OSError, httpx.HTTPError, ValueError):
        parser.exit(
            1, "Rehearsal failed; inspect configuration without printing credentials.\n"
        )


if __name__ == "__main__":
    main()
