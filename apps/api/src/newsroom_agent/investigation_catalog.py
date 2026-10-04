"""Approved analytical questions; provider codes never come from the model."""

import hashlib
import json
from functools import lru_cache
from pathlib import Path

DATA = Path(__file__).parent / "investigation_data"
SCENARIOS = {
    "births": {
        "title": "A · 출생 회복의 지역 격차",
        "question": "전국 출생아가 계속 늘었다는데, 시도별로도 회복하고 있을까?",
        "entities": ["전국 시·도"],
        "metrics": ["출생아 수"],
        "start": "2005-01",
        "end": "2026-07",
        "frequency": "월간",
        "source": "KOSIS 인구동향조사",
        "calls": "최대 3회",
        "steps": [
            "전년 동월 대비 연속 증가를 다시 계산합니다.",
            "시도별 증가율·증가 인원·과거 수준의 차이를 비교합니다.",
        ],
    },
    "migration": {
        "title": "B · 청년 순유출과 이동 목적지",
        "question": "경북 청년은 어디로 떠나고, 인구 대비 유출이 심한 시군은 어디일까?",
        "entities": ["경상북도"],
        "metrics": ["순이동", "인구 대비 순이동률", "이동 목적지"],
        "start": "2023",
        "end": "2025",
        "frequency": "연간",
        "source": "KOSIS 국내인구이동통계·주민등록연앙인구",
        "calls": "3회",
        "steps": [
            "20~34세의 순이동과 실제 시도 간 이동 경로를 구분합니다.",
            "시도와 경북 시군을 구분해 규모·인구 대비 순위를 계산합니다.",
        ],
    },
    "prices": {
        "title": "C · 물가 상승률과 영향의 차이",
        "question": "최근 1년 많이 오른 품목과 전체 물가를 많이 끌어올린 품목은 같을까?",
        "entities": ["전국"],
        "metrics": ["품목별 상승률", "근사 기여도"],
        "start": "2025-09",
        "end": "2026-09",
        "frequency": "월간",
        "source": "KOSIS 소비자물가조사·공식 가중치",
        "calls": "2회",
        "steps": [
            "말단 품목의 전년 동월 대비 상승률 상위 20개를 찾습니다.",
            "공식 가중치로 근사 기여도를 계산하고 총지수와 차이를 확인합니다.",
        ],
    },
    "compensation": {
        "title": "D · 임원·직원 보수 비교의 함정",
        "question": "NAVER와 카카오의 CEO 보수는 직원 평균의 몇 배이고 같은 기준일까?",
        "entities": ["NAVER", "카카오"],
        "metrics": ["CEO 보수", "직원 평균급여", "보수 배율"],
        "start": "2025",
        "end": "2025",
        "frequency": "연간",
        "source": "OpenDART 보수·직원 현황과 사업보고서 검증 발췌",
        "calls": "원문 검증 자료 재사용",
        "steps": [
            "같은 사업보고서의 대표이사 보수와 공식 직원 합계 평균을 비교합니다.",
            "보수 구성·지급 주식 보상·미지급 보상 및 분모 차이를 확인합니다.",
        ],
    },
    "business_mix": {
        "title": "E · NAVER·카카오의 성장 구조 변화",
        "question": "2021~2025년 NAVER와 카카오는 무엇으로 성장했고 매출 구성은 어떻게 달라졌나?",
        "entities": ["NAVER", "카카오"],
        "metrics": ["사업별 매출", "매출액", "영업이익"],
        "start": "2021",
        "end": "2025",
        "frequency": "연간",
        "source": "OpenDART 사업보고서 10건·연결 재무제표 검증 발췌",
        "calls": "원문 검증 자료 재사용",
        "steps": [
            "각 회사의 사업별 매출과 비중·영업이익률을 비교합니다.",
            "같은 보고서의 전기 비교액으로 증가분을 분해하고 분류·정정 차이를 표시합니다.",
        ],
    },
}


@lru_cache(maxsize=16)
def archive(name: str):
    manifest = json.loads((DATA / "manifest.json").read_text())
    filename = name + ".json"
    if filename not in manifest["files"]:
        raise ValueError("Unknown official archive")
    raw = (DATA / filename).read_bytes()
    if hashlib.sha256(raw).hexdigest() != manifest["files"][filename]:
        raise ValueError("Official archive integrity failure")
    return json.loads(raw)


def catalog():
    return [
        {"tool": key, **value, "archive_only": key in {"compensation", "business_mix"}}
        for key, value in SCENARIOS.items()
    ]


def validate(c):
    spec = SCENARIOS[c.tool]
    errors = {}
    allowed = spec["entities"]
    if c.tool == "births":
        allowed = [
            "전국 시·도",
            *[
                r["ITM_NM"]
                for r in archive("births-meta")
                if r.get("OBJ_ID_SN") == "1" and r["ITM_ID"] != "12"
            ],
        ]
    elif c.tool == "migration":
        allowed = [
            r["ITM_NM"]
            for r in archive("od-meta")
            if r.get("OBJ_ID_SN") == "1" and r["ITM_ID"] not in {"00", "12"}
        ]
    if (
        not c.entities
        or len(set(c.entities)) != len(c.entities)
        or any(e not in allowed for e in c.entities)
    ):
        errors["entities"] = "검증된 대상에서 선택해 주세요: " + " · ".join(allowed)
    if c.tool in {"migration", "prices"} and len(c.entities) != 1:
        errors["entities"] = "조사할 지역 한 곳을 선택해 주세요. 시도 순위는 함께 비교합니다."
    if c.metrics != spec["metrics"] or c.frequency != spec["frequency"]:
        errors["metrics"] = "이 조사는 " + " · ".join(spec["metrics"]) + "을 함께 분석합니다."
    if c.tool in {"births", "business_mix", "migration"}:
        import re

        pattern = r"20\d{2}-(0[1-9]|1[0-2])" if c.tool == "births" else r"20\d{2}"
        if not (
            re.fullmatch(pattern, c.start)
            and re.fullmatch(pattern, c.end)
            and spec["start"] <= c.start <= c.end <= spec["end"]
        ):
            errors["period"] = f"검증한 기간은 {spec['start']}~{spec['end']}입니다."
    elif (c.start, c.end) != (spec["start"], spec["end"]):
        errors["period"] = f"이 사례는 {spec['start']}~{spec['end']} 원문을 검증했습니다."
    if c.tool == "migration" and c.age_range != "20-34세":
        errors["age_range"] = (
            "이동·인구 분모를 맞춘 20~34세 자료입니다. 다른 연령으로 대체하지 않습니다."
        )
    if c.statement_basis != "연결" or c.amount_basis != "당기":
        errors["basis"] = "이 사례의 재무는 연간 연결·당기 기준이며 보수는 해당 법인 기준입니다."
    if c.company_codes:
        errors["company_codes"] = "사례 자료의 검증된 회사 식별자를 서버가 사용합니다."
    if c.comparison != "심층 비교" or c.comparison_period != "조사 계획":
        errors["comparison"] = (
            "조사 계획의 비교 방법을 사용해 주세요. 자연어로 계획을 다시 확인할 수 있습니다."
        )
    return errors
