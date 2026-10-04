"""Bounded catalog-owned queries; official archives are explicitly selected."""

from datetime import UTC, datetime

from newsroom_agent.event_models import TraceStep
from newsroom_agent.investigation_calculations import analyze, month, stamp
from newsroom_agent.investigation_catalog import archive
from newsroom_agent.research import ResearchError


async def fetch(c, research, mode):
    if mode == "archive":
        return analyze(c, archive(c.tool))
    if c.tool in {"compensation", "business_mix"}:
        raise ResearchError(
            "이 사례는 원문 대조를 마친 공식 저장 원자료를 사용합니다. "
            "자료 방식 안내를 확인하고 공식 저장 원자료 재분석을 승인해 주세요."
        )
    research.require_source("kosis")
    jobs = []
    if c.tool == "births":
        regions = [
            r for r in archive("births-meta") if r.get("OBJ_ID_SN") == "1" and r["ITM_ID"] != "12"
        ]
        selected = [
            r["ITM_ID"]
            for r in regions
            if "전국 시·도" in c.entities or r["ITM_NM"] in ["전국", *c.entities]
        ]
        a, z = month(c.start) - 12, month(c.end)
        while a <= z:
            end = min(a + 95, z)
            jobs.append(
                dict(
                    tblId="DT_1B8000G",
                    objL1="+".join(selected),
                    objL2="10",
                    itmId="T1",
                    prdSe="M",
                    startPrdDe=stamp(a),
                    endPrdDe=stamp(end),
                )
            )
            a = end + 1
    elif c.tool == "prices":
        for date in [c.start, c.end]:
            jobs.append(
                dict(
                    tblId="DT_1J22001",
                    objL1="T10",
                    objL2="ALL",
                    itmId="T",
                    prdSe="M",
                    startPrdDe=date.replace("-", ""),
                    endPrdDe=date.replace("-", ""),
                )
            )
    else:
        for table, meta, item, prefix in [
            ("DT_1B26001", "migration-meta", "T10+T20+T25", "47"),
            ("DT_1B040M5_1", "population-meta", "T10", "37"),
        ]:
            codes = [
                r["ITM_ID"]
                for r in archive(meta)
                if r.get("OBJ_ID_SN") == "1"
                and (
                    len(r["ITM_ID"]) == 2
                    and r["ITM_ID"] not in {"00", "12"}
                    or r["ITM_ID"].startswith(prefix)
                    and len(r["ITM_ID"]) == 5
                )
            ]
            jobs.append(
                dict(
                    tblId=table,
                    objL1="+".join(codes),
                    objL2="0",
                    objL3="120+130+150",
                    itmId=item,
                    prdSe="Y",
                    startPrdDe=c.start,
                    endPrdDe=c.end,
                )
            )
        meta = archive("od-meta")
        origin = next(
            r["ITM_ID"] for r in meta if r.get("OBJ_ID_SN") == "1" and r["ITM_NM"] == c.entities[0]
        )
        dest = [
            r["ITM_ID"]
            for r in meta
            if r.get("OBJ_ID_SN") == "2" and r["ITM_ID"] not in {"00", "12"}
        ]
        jobs.append(
            dict(
                tblId="DT_1B26003",
                objL1=origin,
                objL2="+".join(dest),
                objL3="0",
                objL4="120+130+150",
                itmId="T70",
                prdSe="Y",
                startPrdDe=c.start,
                endPrdDe=c.end,
            )
        )
    datasets = []
    for job in jobs:
        params = {
            "method": "getList",
            "orgId": "101",
            "format": "json",
            "jsonVD": "Y",
            "smblChk": "Y",
            **job,
        }
        rows = await research.kosis().fetch_parameters(params)
        datasets.append(
            dict(parameters=params, rows=rows, retrieved_at=datetime.now(UTC).isoformat())
        )
    result = analyze(
        c, {"datasets": datasets}, "공식 API 실제 조회 · 가중치/분류는 검증된 카탈로그"
    )
    result.trace = [
        TraceStep(
            tool="KOSIS 조사 자료",
            status="complete",
            at=d["retrieved_at"],
            parameters=d["parameters"],
        )
        for d in datasets
    ]
    return result
