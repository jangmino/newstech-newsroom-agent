"""Manual approved 81-person rehearsal; bounded calls and secret-free reports only."""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import math
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path
from time import monotonic

import httpx
from stage_load import validate_origin

ROOT = Path(__file__).resolve().parents[1]
SNAPSHOTS = ROOT / "apps/api/src/newsroom_agent/event_snapshots"
TOOLS = ("births", "migration", "prices", "compensation", "business_mix")


def cases(users):
    rows = []
    for i in range(users):
        tool = TOOLS[i % len(TOOLS)]
        original = json.loads((SNAPSHOTS / f"investigation-{tool}.json").read_text())["result"]
        rows.append({"question": original["question"], "conditions": original["conditions"],
                     "approved": True, "mode": "archive"})
    return rows


def summary(records):
    durations = sorted(r["seconds"] for r in records)
    return {
        "requests": len(records), "terminal_results": sum(r["result"] for r in records),
        "brief_complete": sum(r.get("brief_status") == "complete" for r in records),
        "brief_failed": sum(r.get("brief_status") == "failed" for r in records),
        "errors": dict(Counter(r["error"] for r in records if r.get("error"))),
        "p95_seconds": durations[max(0, math.ceil(len(durations) * .95) - 1)],
        "max_seconds": durations[-1],
        "waiting_seen": sum(r["waiting_seen"] for r in records),
        "max_queue_ahead": max(r["max_queue_ahead"] for r in records),
        "input_tokens": sum(r.get("input_tokens", 0) for r in records),
        "output_tokens": sum(r.get("output_tokens", 0) for r in records),
    }


async def run(args):
    origin = validate_origin(args.origin)
    code = args.access_code_file.read_text().strip()
    report = {"started_at": datetime.now(UTC).isoformat(), "users": args.users,
              "profile": "five_investigations_shared_conditions_operator_approval",
              "phases": {}, "records": [], "passed": False, "control_checks": []}
    bodies = cases(args.users)
    async with httpx.AsyncClient(base_url=origin, timeout=360, trust_env=False,
                                follow_redirects=False, headers={"X-Workshop-Code": code},
                                limits=httpx.Limits(max_connections=130,
                                                   max_keepalive_connections=130)) as client:
        before = (await client.get("/api/v1/event/queue")).json()
        report["before"] = before
        expected = args.users * (3 if args.full_flow else 1)
        assert expected <= args.gemini_budget and before["active_requests"] == 0
        assert before["max_requests"] >= args.users
        done = asyncio.Event()

        async def monitor():
            while not done.is_set():
                started = monotonic()
                try:
                    r = await client.get("/health")
                    report["control_checks"].append({"status": r.status_code,
                        "seconds": round(monotonic() - started, 3)})
                except httpx.HTTPError:
                    report["control_checks"].append({"status": 0})
                try:
                    await asyncio.wait_for(done.wait(), 3)
                except TimeoutError:
                    pass

        monitoring = asyncio.create_task(monitor())

        async def request(phase, index, body):
            started = monotonic()
            row = {"phase": phase, "index": index, "result": False,
                   "waiting_seen": False, "max_queue_ahead": 0}
            payload = {"question": body["question"]} if phase == "plan" else body
            try:
                async with client.stream("POST", f"/api/v1/event/{phase}/stream",
                                         json=payload) as response:
                    row["http_status"] = response.status_code
                    row["request_id"] = response.headers.get("X-Request-ID")
                    if response.status_code != 200:
                        row["error"] = "http_" + str(response.status_code)
                    else:
                        terminal = None
                        async for line in response.aiter_lines():
                            if not line.strip():
                                continue
                            event = json.loads(line)
                            if event["request_id"] != row["request_id"]:
                                raise ValueError("correlation")
                            if event["type"] == "progress":
                                row["waiting_seen"] |= event["stage"] in {
                                    "waiting", "retry_wait", "source_wait",
                                }
                                row["max_queue_ahead"] = max(
                                    row["max_queue_ahead"], event.get("queue_ahead") or 0,
                                )
                            else:
                                terminal = event
                        if terminal and terminal["type"] == "result":
                            result = terminal["result"]
                            row["result"] = result["question"] == body["question"]
                            row.update({key: terminal.get("metrics", {}).get(key, 0)
                                        for key in ("input_tokens", "output_tokens")})
                            if phase == "plan":
                                row["plan_status"] = result["status"]
                                row["operator_edited_conditions"] = (
                                    result["conditions"] != body["conditions"]
                                )
                                if result["status"] != "ready" or result["field_errors"]:
                                    row["error"] = "plan_not_ready"
                            else:
                                row["result"] &= result["conditions"] == body["conditions"]
                                row["result"] &= result["data_mode"] == body["mode"]
                            if phase == "execute":
                                row["brief_status"] = result["brief"]["status"]
                                row["facts"] = len(result["facts"])
                                row["cache"] = (result.get("cache") or {}).get("status")
                                if not result["facts"] or not result.get("analysis"):
                                    row["error"] = "missing_evidence"
                                if row["brief_status"] != "complete":
                                    reason = next((s.get("note") for s in reversed(result["trace"])
                                                   if s["status"] == "failed"), "unknown")
                                    row["brief_failure"] = reason if reason in {
                                        "InvalidPlannerOutput", "PlannerTimedOut",
                                        "PlannerUnavailable",
                                        "PlannerRateLimited", "FlowError",
                                    } else "unknown"
                                    row["error"] = "brief_" + row["brief_failure"]
                            if not row["result"]:
                                row["error"] = "result_contract"
                        else:
                            row["error"] = (terminal or {}).get("detail", {}).get(
                                "code", "no_terminal",
                            )
            except (httpx.HTTPError, ValueError, KeyError):
                row["error"] = "transport_or_contract"
            row["seconds"] = round(monotonic() - started, 3)
            report["records"].append(row)

        try:
            phases = ("plan", "execute", "general") if args.full_flow else ("execute",)
            for phase in phases:
                rows_before = len(report["records"])
                await asyncio.gather(*(request(phase, i, body) for i, body in enumerate(bodies)))
                rows = report["records"][rows_before:]
                report["phases"][phase] = summary(rows)
                print(json.dumps({"users": args.users, "phase": phase,
                                  **report["phases"][phase]}), flush=True)
                after = (await client.get("/api/v1/event/queue")).json()
                consumed = after["provider_calls"]["gemini"] - before["provider_calls"]["gemini"]
                errors = {r["error"] for r in rows if r.get("error")}
                reviewed = args.reviewed_model_failures and errors <= {"brief_InvalidPlannerOutput"}
                if consumed > args.gemini_budget or (errors and not reviewed):
                    break
            report["after"] = (await client.get("/api/v1/event/queue")).json()
            report["gemini_calls"] = (report["after"]["provider_calls"]["gemini"]
                                      - before["provider_calls"]["gemini"])
            report["capacity_passed"] = (len(report["phases"]) == len(phases)
                and all(r["result"] for r in report["records"])
                and all(s["p95_seconds"] <= 120 for s in report["phases"].values())
                and all(r["status"] == 200 for r in report["control_checks"])
                and report["after"]["active_requests"] == 0
                and report["gemini_calls"] <= args.gemini_budget)
            report["quality_passed"] = not any(r.get("error") for r in report["records"])
            report["reviewed_model_failures"] = args.reviewed_model_failures
            report["passed"] = report["capacity_passed"] and report["quality_passed"]
        finally:
            done.set()
            await monitoring
            args.output.write_text(json.dumps(report, indent=2))
    print(json.dumps({"passed": report["passed"], "gemini_calls": report["gemini_calls"]}))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--origin", required=True)
    parser.add_argument("--access-code-file", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--users", type=int, choices=(5, 20, 40, 81), required=True)
    parser.add_argument("--gemini-budget", type=int, default=250)
    parser.add_argument("--full-flow", action="store_true")
    parser.add_argument("--execute-live", action="store_true")
    parser.add_argument("--reviewed-model-failures", action="store_true",
                        help="Operator reviewed known slot-validation failures; preserve and count")
    args = parser.parse_args()
    if not args.execute_live or not 1 <= args.gemini_budget <= 350:
        parser.error("Explicit live opt-in and budget <=350 required")
    logging.disable(logging.CRITICAL)
    asyncio.run(run(args))


if __name__ == "__main__":
    main()
