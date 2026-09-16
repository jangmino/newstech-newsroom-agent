"""Versioned public excerpts bundled in the backend; no settings, network, or writes."""

import hashlib
import json
from dataclasses import dataclass, replace
from datetime import datetime
from importlib.resources import files

from newsroom_agent.models import QueryConditions, SnapshotMetadata
from newsroom_agent.providers.kosis_employment import (
    EmploymentQuery,
    EmploymentSeries,
    KosisError,
    normalize_employment,
)
from newsroom_agent.providers.opendart_financials import (
    OpenDartError,
    RevenuePair,
    normalize_revenue,
)

SPECS = {
    "kosis": (
        "kosis-youth-employment-2020-2024.json", "kosis-youth-employment-20260916-v1",
        "c084210cd23e1084a6d9285ef42dfb026ccc1044bc2cd0733ccdace442cf425a",
    ),
    "opendart": (
        "opendart-samsung-revenue-2022-2024.json", "opendart-samsung-revenue-20260916-v1",
        "2ce89cbfb987b9d902367fa0c3a54cd505e005ddf2204afa51f0c0b9e6c86269",
    ),
}
SNAPSHOT_CAVEAT = (
    "공식 저장 자료입니다. 이번 승인에서 외부 API를 조회하지 않았으며 "
    "원래 확보 시점 이후의 개정·정정은 반영하지 않습니다. 최신 자료와 원문을 다시 확인해 주세요."
)


class SnapshotError(Exception):
    def __init__(self, code: str = "snapshot_unavailable") -> None:
        self.code = code
        super().__init__({
            "snapshot_disabled": "현재 저장 자료 사용이 꺼져 있습니다. 운영자에게 문의해 주세요.",
            "snapshot_unavailable": (
                "저장 자료의 파일·출처·값을 확인하지 못했습니다. "
                "다른 자료로 바꾸지 않고 중단했습니다. 운영자에게 문의해 주세요."
            ),
            "snapshot_changed": "확인한 저장 자료 버전이 달라졌습니다. "
                                "질문을 다시 분석하고 저장 자료 안내를 확인한 뒤 승인해 주세요.",
        }[code])


@dataclass(frozen=True)
class SavedPublicData:
    metadata: SnapshotMetadata
    employment: EmploymentSeries | None = None
    revenue: RevenuePair | None = None


def _read(filename: str) -> bytes:
    return files("newsroom_agent").joinpath("snapshot_data", filename).read_bytes()


def _timestamp(value: str) -> datetime:
    timestamp = datetime.fromisoformat(value)
    if timestamp.tzinfo is None or timestamp.utcoffset() is None:
        raise ValueError("Snapshot timestamp must include timezone")
    return timestamp


def load_snapshot(source: str) -> SavedPublicData:
    try:
        filename, snapshot_id, digest = SPECS[source]
        raw = _read(filename)
        if len(raw) > 1_000_000 or hashlib.sha256(raw).hexdigest() != digest:
            raise ValueError("Unrecognized snapshot content")
        data = json.loads(raw)
        if source == "kosis":
            query = EmploymentQuery(entity="전국 시·도", metric="고용률", age_range="15-29세",
                                    start_year=2020, end_year=2024)
            if data["request"]["parameters"] != query.parameters:
                raise ValueError("Unexpected snapshot scope")
            series = normalize_employment(data["rows"], query, _timestamp(data["retrieved_at"]))
            metadata = SnapshotMetadata(
                snapshot_id=snapshot_id, source="kosis", title="KOSIS · 저장된 청년 고용률",
                captured_at=series.retrieved_at.isoformat(), unit="%",
                coverage="15~29세 연간 고용률 · 17개 시도 · 2020~2024년. "
                         "전국·수도권·비수도권의 시도별 비교를 지원합니다.",
                source_urls=[series.source_url], caveats=[SNAPSHOT_CAVEAT,
                    "공식 API의 항목·기간·주석과 85개 셀의 차원·단위를 확인한 발췌입니다. "
                    "사람의 통계 해석 검증 완료나 기사 사용 승인이 아닙니다.",
                    "표본오차·지역 경계·자료 최종수정일을 원표에서 검토해 주세요."],
            )
            return SavedPublicData(metadata, employment=series)
        rows = data["observations"]
        if [row["year"] for row in rows] != [2022, 2024]:
            raise ValueError("Unexpected snapshot years")
        observations = []
        for row in rows:
            if row["unit"] != "원" or row["statement_basis"] != "CFS":
                raise ValueError("Unexpected snapshot unit or basis")
            normalized = normalize_revenue({"list": [{
                "corp_code": row["corp_code"], "bsns_year": str(row["year"]),
                "reprt_code": row["report_code"], "fs_div": row["statement_basis"],
                "account_id": row["account_id"], "account_nm": row["account_name"],
                "sj_div": row["statement_type"], "rcept_no": row["receipt_no"],
                "currency": row["currency"], "thstrm_amount": row["raw_amount"],
            }]}, row["year"], _timestamp(row["retrieved_at"]))
            if normalized.amount != row["amount"]:
                raise ValueError("Snapshot normalization mismatch")
            observations.append(normalized)
        pair = RevenuePair(start=observations[0], end=observations[1])
        metadata = SnapshotMetadata(
            snapshot_id=snapshot_id, source="opendart", title="OpenDART · 저장된 삼성전자 매출액",
            captured_at=max(row.retrieved_at for row in observations).isoformat(), unit="원",
            coverage="삼성전자 · 2022년과 2024년 사업보고서 · 연간 연결 매출액. "
                     "증감 폭과 증감률 비교를 지원합니다.",
            source_urls=[row.source_url for row in observations], caveats=[SNAPSHOT_CAVEAT,
                "공식 API와 공시 원문의 백만원 값을 대조한 발췌입니다. "
                "사람의 해석 검증 완료나 기사 사용 승인이 아닙니다.",
                "각 사업연도 당기값이며 이후 보고서의 재작성 비교값과 다를 수 있습니다."],
        )
        return SavedPublicData(metadata, revenue=pair)
    except (OSError, ValueError, KeyError, TypeError, KosisError, OpenDartError):
        raise SnapshotError() from None


def select_employment(series: EmploymentSeries, conditions: QueryConditions) -> EmploymentSeries:
    start, end = map(int, conditions.period.split("-"))
    query = EmploymentQuery(entity=conditions.entity, metric=conditions.metric,
                            age_range=conditions.filters["age_range"],
                            start_year=start, end_year=end)
    return replace(series, query=query, observations=tuple(
        row for row in series.observations
        if row.region_code in query.region_codes and row.year in query.years
    ))
