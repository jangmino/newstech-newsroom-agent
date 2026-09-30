"""Manual opt-in live burst rehearsal. No credentials, questions or response bodies in output."""

import argparse
import asyncio
import json
import math
from copy import deepcopy
from datetime import UTC, datetime
from pathlib import Path
from time import monotonic

import httpx

ROOT = Path(__file__).resolve().parents[1]
SNAPSHOTS = ROOT / "apps/api/src/newsroom_agent/event_snapshots"


def cases(profile, users):
    saved = {
        p.stem: json.loads(p.read_text())["result"] for p in SNAPSHOTS.glob("*.json")
    }
    rows = []
    regions = [
        "서울특별시",
        "부산광역시",
        "대구광역시",
        "인천광역시",
        "광주광역시",
        "대전광역시",
        "울산광역시",
        "세종특별자치시",
        "경기도",
        "강원특별자치도",
        "충청북도",
        "충청남도",
        "전북특별자치도",
        "전라남도",
        "경상북도",
        "경상남도",
        "제주특별자치도",
    ]
    for i in range(users):
        source = (
            "seoul"
            if profile == "same" or i < 20
            else "finance"
            if i < 26
            else "disclosures"
        )
        r = saved[source]
        c = deepcopy(r["conditions"])
        q = r["question"]
        if profile == "mixed":
            if source == "seoul":
                c["entities"] = [regions[i % 17]]
                if i >= 17:
                    c["age_range"] = "20-29세"
                q = (f"{c['entities'][0]}의 {c['age_range']} 고용률을 "
                     "2021년부터 2025년까지 비교해 줘.")
            elif source == "finance":
                c["start"], c["end"] = ("2023", "2024") if i % 2 else ("2024", "2025")
                c["metrics"] = [["매출액"], ["영업이익"], ["당기순이익"]][(i - 20) // 2]
                q = (f"현대자동차의 {c['start']}년과 {c['end']}년 "
                     f"연결 {c['metrics'][0]}을 비교해 줘.")
            else:
                c["start"] = ["2026-08-01", "2026-08-10", "2026-08-20", "2026-09-01"][
                    i - 26
                ]
                q = (f"NAVER와 카카오의 {c['start']}부터 {c['end']}까지 "
                     "투자·지분·소송 공시를 비교해 줘.")
        rows.append({"question": q, "conditions": c, "mode": "live", "approved": True})
    return rows


def summarize(rows):
    values = sorted(x["seconds"] for x in rows)
    return {
        "count": len(rows),
        "success": sum(x["ok"] for x in rows),
        "p95_seconds": values[max(0, math.ceil(len(values) * 0.95) - 1)],
        "max_seconds": max(values),
        "waiting_seen": sum(x["waiting_seen"] for x in rows),
        "briefs_complete": sum(x.get("brief") == "complete" for x in rows),
        "briefs_failed": sum(x.get("brief") == "failed" for x in rows),
    }


async def run(args):
    import logging

    logging.disable(logging.CRITICAL)
    code = args.access_code_file.read_text().strip()
    output = {
        "started_at": datetime.now(UTC).isoformat(),
        "users": args.users,
        "profile": args.profile,
        "phases": {},
        "requests": [],
        "control_requests": [],
    }
    bodies = cases(args.profile, args.users)
    async with httpx.AsyncClient(
        base_url=args.origin.rstrip("/"),
        timeout=225,
        headers={"X-Workshop-Code": code},
        trust_env=False,
        limits=httpx.Limits(max_connections=45, max_keepalive_connections=45),
    ) as client:
        output["before"] = (await client.get("/api/v1/event/queue")).json()
        done = asyncio.Event()

        async def monitor():
            while not done.is_set():
                start = monotonic()
                try:
                    r = await client.get("/api/v1/operations")
                    output["control_requests"].append(
                        {
                            "status": r.status_code,
                            "seconds": round(monotonic() - start, 3),
                        }
                    )
                except httpx.HTTPError:
                    output["control_requests"].append({"status": 0, "seconds": 225})
                try:
                    await asyncio.wait_for(done.wait(), 2)
                except TimeoutError:
                    pass

        monitor_task = asyncio.create_task(monitor())

        async def request(phase, index, body):
            start = monotonic()
            row = {"phase": phase, "index": index, "ok": False, "waiting_seen": False}
            terminal = None
            payload = {"question": body["question"]} if phase == "plan" else body
            try:
                async with client.stream(
                    "POST", f"/api/v1/event/{phase}/stream", json=payload
                ) as r:
                    row["http_status"] = r.status_code
                    row["request_id"] = r.headers.get("X-Request-ID")
                    if r.status_code == 200:
                        async for line in r.aiter_lines():
                            if not line.strip():
                                continue
                            event = json.loads(line)
                            if event["type"] == "progress":
                                row["waiting_seen"] |= event["stage"] in [
                                    "waiting",
                                    "source_wait",
                                    "retry_wait",
                                ]
                            else:
                                terminal = event
                        if terminal and terminal["type"] == "result":
                            result = terminal["result"]
                            row["ok"] = result["question"] == body["question"]
                            if phase == "plan":
                                row["ok"] &= not bool(
                                    result.get("field_errors", {}).get("scope")
                                )
                            else:
                                row["ok"] &= (
                                    result["conditions"] == body["conditions"]
                                    and result["data_mode"] == "live"
                                )
                            if phase == "execute":
                                row["brief"] = result["brief"]["status"]
                                row["facts"] = len(result["facts"])
                                row["coverage"] = result["coverage"]
                                row["cache"] = (result.get("cache") or {}).get("status")
                            row["metrics"] = terminal.get("metrics", {})
                        elif terminal:
                            row["error_code"] = terminal.get("detail", {}).get("code")
            except (httpx.HTTPError, ValueError, KeyError, TypeError) as e:
                row["transport_error"] = type(e).__name__
            row["seconds"] = round(monotonic() - start, 3)
            output["requests"].append(row)
            return row

        try:
            for phase in ["plan", "execute", "general"]:
                rows = await asyncio.gather(
                    *(request(phase, i, body) for i, body in enumerate(bodies))
                )
                summary = summarize(rows)
                output["phases"][phase] = summary
                print(json.dumps({"phase": phase, **summary}), flush=True)
                args.output.write_text(json.dumps(output, ensure_ascii=False, indent=2))
                if not all(x["ok"] for x in rows):
                    output["stopped"] = "request_failure"
                    break
        finally:
            done.set()
            await monitor_task
        output["after"] = (await client.get("/api/v1/event/queue")).json()
    output["passed_transport"] = len(output["phases"]) == 3 and all(
        r["ok"] for r in output["requests"]
    )
    output["passed_latency"] = all(
        p["p95_seconds"] <= 120 for p in output["phases"].values()
    )
    args.output.write_text(json.dumps(output, ensure_ascii=False, indent=2))
    print(
        json.dumps(
            {
                "passed_transport": output["passed_transport"],
                "passed_latency": output["passed_latency"],
            }
        )
    )
    return output["passed_transport"] and output["passed_latency"]


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--origin", required=True)
    p.add_argument("--access-code-file", type=Path, required=True)
    p.add_argument("--output", type=Path, required=True)
    p.add_argument("--users", type=int, choices=[5, 15, 30], required=True)
    p.add_argument("--profile", choices=["same", "mixed"], required=True)
    p.add_argument("--execute-live", action="store_true")
    a = p.parse_args()
    if not a.execute_live or not a.origin.startswith("https://") or a.output.exists():
        p.error("Explicit live opt-in, HTTPS and a new output path are required.")
    raise SystemExit(0 if asyncio.run(run(a)) else 1)


if __name__ == "__main__":
    main()
