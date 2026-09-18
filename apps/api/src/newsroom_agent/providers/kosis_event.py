"""KOSIS event catalog: validate every cell against the approved query."""

import re
from datetime import date, datetime
from decimal import Decimal

from newsroom_agent.event_catalog import AGES, EMPLOYMENT_METRICS, period_list, regions, table_for
from newsroom_agent.event_models import EventConditions
from newsroom_agent.providers.kosis_employment import REGIONS, KosisError
from newsroom_agent.research_models import ResearchFact


def parameters(c: EventConditions, metric: str) -> dict[str, str]:
    national = table_for(c, metric) == "DT_1DA7002S"
    return {
        "orgId": "101",
        "tblId": table_for(c, metric),
        "itmId": EMPLOYMENT_METRICS[metric][0],
        "objL1": AGES[c.age_range] if national else "+".join(regions(c)),
        "objL2": "" if national else AGES[c.age_range],
        **{f"objL{i}": "" for i in range(3, 9)},
        "prdSe": "Y" if c.frequency == "연간" else "M",
        "startPrdDe": c.start.replace("-", ""),
        "endPrdDe": c.end.replace("-", ""),
        "format": "json",
        "jsonVD": "Y",
    }


def normalize(payload, c: EventConditions, metric: str, at: datetime) -> list[ResearchFact]:
    params = parameters(c, metric)
    national = params["tblId"] == "DT_1DA7002S"
    unit = EMPLOYMENT_METRICS[metric][1]
    expected = {(region, period) for region in regions(c) for period in period_list(c)}
    seen = set()
    facts = []
    try:
        if not isinstance(payload, list) or len(payload) != len(expected):
            raise ValueError()
        for row in payload:
            region = "00" if national else row["C1"]
            key = region, row["PRD_DE"]
            age = row["C1"] if national else row["C2"]
            if (
                key not in expected
                or key in seen
                or age != AGES[c.age_range]
                or row["ORG_ID"] != "101"
                or row["TBL_ID"] != params["tblId"]
                or row["ITM_ID"] != params["itmId"]
                or row["UNIT_NM"] != unit
                or row["PRD_SE"] != ("A" if c.frequency == "연간" else "M")
            ):
                raise ValueError()
            if not re.fullmatch(r"\d+(?:\.\d+)?", row["DT"]):
                raise ValueError()
            value = Decimal(row["DT"])
            if unit == "%" and value > 100:
                raise ValueError()
            date.fromisoformat(row["LST_CHN_DE"])
            age_name = row["C1_NM"] if national else row["C2_NM"]
            if age_name.replace(" ", "") != c.age_range:
                raise ValueError()
            entity = "전국 집계" if region == "00" else REGIONS[region]
            if not national and row["C1_NM"] != ("계" if region == "00" else entity):
                raise ValueError()
            seen.add(key)
            facts.append(
                ResearchFact(
                    id="pending",
                    entity=entity,
                    metric=metric,
                    period=row["PRD_DE"],
                    value=format(value, "f"),
                    unit=unit,
                    kind="observation",
                    source_urls=[
                        f"https://kosis.kr/statHtml/statHtml.do?orgId=101&tblId={params['tblId']}"
                    ],
                    retrieved_at=at.isoformat(),
                    details={
                        **params,
                        "region_code": region,
                        "age_range": c.age_range,
                        "last_changed_at": row["LST_CHN_DE"],
                        "raw_value": row["DT"],
                        "table_name": row["TBL_NM"],
                        "national_basis": "공식 전국 집계" if region == "00" else "공식 시도 값",
                    },
                )
            )
    except (ValueError, KeyError, TypeError, ArithmeticError):
        raise KosisError("invalid_response") from None
    return facts
