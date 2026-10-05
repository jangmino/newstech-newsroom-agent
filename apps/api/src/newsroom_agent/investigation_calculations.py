"""Deterministic newsroom comparisons from bounded, traceable official material."""

import re
from collections import defaultdict
from decimal import ROUND_HALF_UP, Decimal

from newsroom_agent.event_models import AnalysisTable, EventData, InvestigationAnalysis
from newsroom_agent.investigation_catalog import SCENARIOS, archive
from newsroom_agent.research import ResearchError
from newsroom_agent.research_models import ResearchFact


def number(value):
    if not isinstance(value, str) or not re.fullmatch(r"-?\d+(?:\.\d+)?", value):
        return None
    result = Decimal(value)
    return result if result.is_finite() else None


def rounded(value, places=2):
    return str(value.quantize(Decimal(10) ** -places, rounding=ROUND_HALF_UP))


def month(value):
    value = value.replace("-", "")
    return int(value[:4]) * 12 + int(value[4:]) - 1


def stamp(index):
    return f"{index // 12:04d}{index % 12 + 1:02d}"


def table_url(table):
    return f"https://kosis.kr/statHtml/statHtml.do?orgId=101&tblId={table}"


class Builder:
    def __init__(self, c, at, version):
        self.c, self.at, self.version = c, at, version
        self.facts, self.tables, self.focus, self.warnings = [], [], [], []
        self.partial = False

    def fact(self, entity, metric, period, value, unit, urls, formula="원자료 값", **details):
        fact = ResearchFact(
            id=f"F{len(self.facts) + 1}",
            entity=entity,
            metric=metric,
            period=period,
            value=str(value),
            unit=unit,
            kind="observation" if formula == "원자료 값" else "change",
            source_urls=list(dict.fromkeys(urls)),
            retrieved_at=details.pop("retrieved_at", self.at),
            formula=formula,
            details={k: str(v) for k, v in details.items()},
        )
        self.facts.append(fact)
        return fact

    def table(self, title, columns, rows, ids, note=""):
        self.tables.append(
            AnalysisTable(title=title, columns=columns, rows=rows, evidence_ids=ids, note=note)
        )

    def result(self, methods):
        if not self.facts:
            raise ResearchError(
                "승인한 범위의 비교 가능한 값이 없습니다. 조건과 원문을 확인해 주세요."
            )
        return EventData(
            facts=self.facts,
            caveats=list(dict.fromkeys(self.warnings)),
            coverage="partial" if self.partial else "complete",
            analysis=InvestigationAnalysis(
                title=SCENARIOS[self.c.tool]["title"],
                tables=self.tables,
                focus_ids=list(dict.fromkeys(self.focus))[
                    : 40 if self.c.tool == "business_mix" else 24
                ],
                method=methods,
                source_version=self.version,
            ),
        )


def checked_rows(dataset):
    """Reject mixed tables/items/duplicate cells, never turn a missing value into zero."""
    params, seen = dataset["parameters"], set()
    result = []
    for r in dataset["rows"]:
        key = tuple(r.get(k, "") for k in ("ITM_ID", "C1", "C2", "C3", "C4", "PRD_DE"))
        if (
            r.get("ORG_ID") != "101"
            or r.get("TBL_ID") != params["tblId"]
            or key in seen
            or r.get("ITM_ID") not in params["itmId"].split("+")
        ):
            raise ResearchError("통계표·항목·중복 셀 검증에 실패했습니다. 원자료를 확인해 주세요.")
        for i in range(1, 5):
            allowed = params.get(f"objL{i}")
            if allowed and allowed != "ALL" and r.get(f"C{i}") not in allowed.split("+"):
                raise ResearchError("승인 범위와 다른 통계 분류가 반환되어 계산을 멈췄습니다.")
        if not params["startPrdDe"] <= r.get("PRD_DE", "") <= params["endPrdDe"]:
            raise ResearchError("조회 기간과 다른 자료가 반환되었습니다.")
        seen.add(key)
        result.append(r)
    return result


def births(c, datasets, version):
    b = Builder(c, max(d["retrieved_at"] for d in datasets), version)
    groups = defaultdict(dict)
    for ds in datasets:
        for r in checked_rows(ds):
            if r.get("C2") != "10" or r.get("PRD_SE") != "M":
                raise ResearchError("출생아 수의 분류·주기를 확인하지 못했습니다.")
            key = month(r["PRD_DE"])
            if key in groups[r["C1_NM"]]:
                raise ResearchError("출생 자료에 중복 기간이 있습니다.")
            groups[r["C1_NM"]][key] = r
    start, end = month(c.start), month(c.end)
    rows, refs = [], []
    urls = [table_url("DT_1B8000G")]
    selected = (
        list(groups) if "전국 시·도" in c.entities else list(dict.fromkeys(["전국", *c.entities]))
    )
    for name in selected:
        data = groups[name]
        latest = number(data.get(end, {}).get("DT"))
        prior = number(data.get(end - 12, {}).get("DT"))
        if latest is None or prior is None or prior <= 0:
            b.partial = True
            b.warnings.append(f"{name}: 최근 월 또는 전년 동월 값이 없어 비교에서 제외했습니다.")
            continue
        # Do not bridge creation/transfer boundaries by treating names as equivalent.
        boundary = month("2024-07") if name in {"대구광역시", "경상북도"} else start
        if name in {"세종특별자치시", "충청남도", "충청북도"}:
            boundary = max(boundary, month("2013-07"))
        run = longest = 0
        for t in range(max(start, boundary), end + 1):
            a = number(data.get(t - 12, {}).get("DT"))
            z = number(data.get(t, {}).get("DT"))
            run = run + 1 if a is not None and z is not None and z > a else 0
            longest = max(longest, run)
        values = [
            ("출생아 수", latest, "명", "원자료 값"),
            ("전년 동월 대비 증가 인원", latest - prior, "명", "현재 월 - 전년 동월"),
            (
                "전년 동월 대비 증가율",
                rounded((latest / prior - 1) * 100),
                "%",
                "(현재 월 / 전년 동월 - 1) × 100",
            ),
            ("현재 연속 증가", run, "개월", "비교 가능한 연속 월에서 전년 동월보다 큰 월 수"),
            ("선택 기간 최장 연속 증가", longest, "개월", "선택 기간 연속 증가 월 수의 최댓값"),
        ]
        fs = [
            b.fact(
                name,
                m,
                c.end,
                v,
                unit,
                urls,
                formula,
                current=latest,
                previous_year=prior,
                modified_at=data[end].get("LST_CHN_DE"),
                comparable_start=stamp(max(start, boundary)),
                raw_symbol=data[end]["DT"],
            )
            for m, v, unit, formula in values
        ]
        # Compare the same calendar month in the first covered year, not arbitrary months.
        baseline_t = (start // 12) * 12 + end % 12
        baseline = number(data.get(baseline_t, {}).get("DT"))
        recovery = "비교 불가"
        if baseline is not None and baseline > 0 and baseline_t >= boundary:
            recovery = rounded((latest / baseline - 1) * 100)
            f = b.fact(
                name,
                "시작 연도 같은 달 대비 변화율",
                f"{stamp(baseline_t)}~{stamp(end)}",
                recovery,
                "%",
                urls,
                "(종료 월 / 시작 연도 같은 달 - 1) × 100",
                baseline=baseline,
                current=latest,
            )
            fs.append(f)
        rows.append(
            [
                name,
                str(latest),
                str(latest - prior),
                fs[2].value,
                str(run),
                str(longest),
                "비교 불가" if recovery == "비교 불가" else recovery,
            ]
        )
        refs.extend(f.id for f in fs)
        if name == "전국":
            b.focus.extend(f.id for f in fs)
        if name in {"대구광역시", "경상북도", "세종특별자치시", "충청남도", "충청북도"}:
            b.partial = True
            b.warnings.append(
                f"{name}: 행정구역 변경을 가로지르는 연속·과거 수준 비교를 제한했습니다."
            )
    ordered = sorted(rows, key=lambda r: Decimal(r[3]), reverse=True)
    extremes = {r[0] for r in ordered[:2] + ordered[-2:]}
    b.focus.extend(f.id for f in b.facts if f.entity in extremes and f.metric != "출생아 수")
    b.table(
        "전국과 지역의 회복은 같은가",
        [
            "지역",
            "출생아(명)",
            "증가 인원(명)",
            "전년 동월(%)",
            "연속 증가(개월)",
            "기간 내 최장(개월)",
            "시작 연도 같은 달 대비(%)",
        ],
        ordered,
        refs,
        "전국은 공식 집계입니다. 선택 기간 밖의 역대 기록·출산정책 효과를 의미하지 않습니다.",
    )
    b.warnings.append(
        "최근 출생 자료는 잠정·수정될 수 있습니다. 결측은 0이 아니며 "
        "선택 기간 밖 기록은 판단하지 않습니다."
    )
    return b.result(
        [
            "전년 동월 대비 엄격한 증가(동일 값은 연속 중단)",
            "지역별 증가율과 증가 인원·과거 수준 비교",
        ]
    )


def migration(c, datasets, version):
    b = Builder(c, max(d["retrieved_at"] for d in datasets), version)
    ds = {d["parameters"]["tblId"]: checked_rows(d) for d in datasets}
    flows, pop, od = ds["DT_1B26001"], ds["DT_1B040M5_1"], ds["DT_1B26003"]
    years = list(map(str, range(int(c.start), int(c.end) + 1)))

    def totals(rows, item):
        groups = defaultdict(dict)
        for r in rows:
            if r["PRD_DE"] not in years or r["ITM_ID"] != item:
                continue
            if r.get("C2") != "0" or r.get("C3") not in {"120", "130", "150"}:
                raise ResearchError("이동·인구의 성별·연령 분류가 일치하지 않습니다.")
            groups[(r["C1"], r["C1_NM"])][(r["PRD_DE"], r["C3"])] = number(r["DT"])
        return {
            k: sum(v.values())
            for k, v in groups.items()
            if len(v) == len(years) * 3 and all(x is not None for x in v.values())
        }

    inflow, outflow, net = [totals(flows, i) for i in ["T10", "T20", "T25"]]
    population = totals(pop, "T10")
    # Join the two official code systems by unique names at the same geographic level.
    by_name = {(len(code), name): v for (code, name), v in population.items()}
    if len(by_name) != len(population):
        raise ResearchError("인구 분모에 같은 이름의 지역이 중복되어 결합을 멈췄습니다.")
    result = {2: [], 5: []}
    refs = []
    for (code, name), n in net.items():
        key = (code, name)
        if key not in inflow or key not in outflow or inflow[key] - outflow[key] != n:
            raise ResearchError("전입 - 전출과 공식 순이동이 일치하지 않습니다.")
        if "2023" in years and (name in {"경상북도", "대구광역시", "군위군"}):
            b.partial = True
            b.warnings.append(
                f"{name}: 군위군 편입이 포함된 기간은 인구 대비 순위에서 제외했습니다."
            )
            continue
        denominator = by_name.get((len(code), name))
        if denominator is None or denominator <= 0:
            b.partial = True
            b.warnings.append(
                f"{name}: 같은 연령·기간의 인구 분모가 없어 비율을 만들지 않았습니다."
            )
            continue
        url = [table_url("DT_1B26001"), table_url("DT_1B040M5_1")]
        a = b.fact(
            name,
            "기간 합계 순이동",
            f"{c.start}~{c.end}",
            n,
            "명",
            url,
            "Σ(전입 - 전출), 20~24·25~29·30~34세 합계",
            inflow=inflow[key],
            outflow=outflow[key],
        )
        z = b.fact(
            name,
            "연평균 순이동률",
            a.period,
            rounded(n / denominator * 100),
            "%",
            url,
            "기간 합계 순이동 / 기간 합계 주민등록연앙인구 × 100",
            net=n,
            population_years=denominator,
        )
        result[len(code)].append([name, str(n), z.value])
        refs.extend([a.id, z.id])
    for level, title in [(2, "시도별 규모와 인구 대비 비교"), (5, "경북 시군별 인구 대비 비교")]:
        rows = sorted(result[level], key=lambda r: Decimal(r[2]))
        if level == 5 and c.entities != ["경상북도"]:
            continue
        b.table(
            title,
            ["지역", "기간 합계 순이동(명)", "연평균 순이동률(%)"],
            rows,
            refs,
            (
                "음수는 순유출입니다. 3년 합계 인구 비율이 아닌 인구·연도 "
                "합계로 계산한 연평균 비율입니다."
            ),
        )
        for rank, row in enumerate(rows, 1):
            for fact in b.facts:
                if fact.entity == row[0] and fact.metric == "연평균 순이동률":
                    fact.rank = rank
                    fact.details["rank_scope"] = (
                        title + " · 순유출률 큰 순서 · 제외 지역은 한계 참고"
                    )
        chosen = {r[0] for r in rows[:2] + rows[-1:]}
        b.focus.extend(f.id for f in b.facts if f.entity in chosen)
    destinations = defaultdict(dict)
    origin = c.entities[0]
    for r in od:
        if r["C1_NM"] != origin or r["C1"] == r["C2"] or r["PRD_DE"] not in years:
            continue
        if r.get("C3") != "0" or r.get("C4") not in {"120", "130", "150"}:
            raise ResearchError("목적지 자료의 연령·성별을 확인해 주세요.")
        destinations[r["C2_NM"]][(r["PRD_DE"], r["C4"])] = number(r["DT"])
    rows, ids = [], []
    for name, vals in destinations.items():
        if len(vals) != len(years) * 3 or any(v is None for v in vals.values()):
            b.partial = True
            b.warnings.append(f"{name}: 이동 목적지 자료 일부가 없어 합산하지 않았습니다.")
            continue
        f = b.fact(
            origin + " → " + name,
            "시도 간 이동",
            f"{c.start}~{c.end}",
            sum(vals.values()),
            "명",
            [table_url("DT_1B26003")],
            "선택 기간·연령의 목적지별 이동 합계; 시도 내 이동 제외",
        )
        rows.append([name, f.value])
        ids.append(f.id)
    if len(rows) != 16:
        b.partial = True
        b.warnings.append(
            "선택한 출발 지역의 시도 간 목적지 일부가 없어 전체 목적지 순위가 아닙니다."
        )
    rows.sort(key=lambda r: Decimal(r[1]), reverse=True)
    b.table(
        "어느 시도로 이동했나",
        ["전입 시도", "기간 이동자 수(명)"],
        rows,
        ids,
        (
            "순유출 인원의 목적지가 아닙니다. 반복 이동을 포함한 이동 "
            "통계이며 이동 이유를 설명하지 않습니다."
        ),
    )
    for rank, row in enumerate(rows, 1):
        for fact in b.facts:
            if fact.entity == origin + " → " + row[0]:
                fact.rank = rank
                fact.details["rank_scope"] = (
                    "선택 출발 시도 → 확인된 시도 간 이동 목적지 · 이동 수 내림차순"
                )
    chosen = {origin + " → " + r[0] for r in rows[:3]}
    b.focus.extend(f.id for f in b.facts if f.entity in chosen)
    b.warnings.append(
        "이동 이유와 고유한 개인 수는 알 수 없습니다. 경북 이외 "
        "시군구 상세는 이번 검증 범위에 없습니다."
    )
    return b.result(
        ["20~34세, 같은 기간·연령 분모", "시도·시군 순위를 분리하고 OD 원표로 목적지 확인"]
    )


def prices(c, datasets, version):
    b = Builder(c, max(d["retrieved_at"] for d in datasets), version)
    values = {}
    names = {}
    for d in datasets:
        for r in checked_rows(d):
            if (
                r.get("C1") != "T10"
                or r.get("PRD_SE") != "M"
                or r.get("UNIT_NM", "").replace("＝", "=") != "2020=100"
            ):
                raise ResearchError("물가의 전국·주기·기준연도가 일치하지 않습니다.")
            key = (r["C2"], r["PRD_DE"])
            if key in values:
                raise ResearchError("중복 물가 셀입니다.")
            values[key] = number(r["DT"])
            names[r["C2"]] = r["C2_NM"]
    weights = archive("price-weights")
    a, z = c.start.replace("-", ""), c.end.replace("-", "")
    rows = []
    url = [table_url("DT_1J22001")]
    for w in weights["items"]:
        code = w["C2"]
        before, after = values.get((code, a)), values.get((code, z))
        if before is None or before <= 0 or after is None:
            raise ResearchError(
                "말단 품목 일부의 물가지수가 없어 전체 순위·기여도 계산을 중단했습니다."
            )
        weight = Decimal(w["WGT_CO"])
        rows.append((code, before, after, weight, (after / before - 1) * 100))
    denominator = sum(w * p for _, p, _, w, _ in rows)
    contributions = {
        code: 100 * w * (after - before) / denominator for code, before, after, w, _ in rows
    }
    rises = sorted(rows, key=lambda r: (-r[4], r[0]))[:20]
    impacts = sorted(rows, key=lambda r: (-contributions[r[0]], r[0]))[:20]
    kept = {r[0] for r in rises + impacts}
    facts = {}
    for code, before, after, w, rate in rows:
        if code not in kept:
            continue
        common = dict(
            index_before=before,
            index_after=after,
            weight_per_thousand=w,
            index_base="2020",
            weight_base="2022",
            weight_retrieved_at=weights["retrieved_at"],
        )
        f = b.fact(
            names[code],
            "전년 동월 대비 물가 상승률",
            c.end,
            rounded(rate),
            "%",
            url,
            "(현재 지수 / 전년 동월 지수 - 1) × 100",
            **common,
        )
        g = b.fact(
            names[code],
            "고정 가중치 근사 기여도",
            c.end,
            rounded(contributions[code], 4),
            "%p",
            url,
            "100 × 품목 가중치 × (현재 지수 - 전년 지수) / Σ(말단 품목 가중치 × 전년 지수)",
            **common,
        )
        facts[code] = (f, g)
    for title, selected in [
        ("상승률이 높은 품목 20개", rises),
        ("근사 기여도가 큰 품목 20개", impacts),
    ]:
        b.table(
            title,
            ["품목", "상승률(%)", "가중치(천분비)", "근사 기여도(%p)"],
            [
                [names[r[0]], rounded(r[4]), str(r[3]), rounded(contributions[r[0]], 4)]
                for r in selected
            ],
            [f.id for r in selected for f in facts[r[0]]],
            "2022 가중치를 고정해 재구성한 근사치이며 공식 기여도가 아닙니다.",
        )
    total_before, total_after = values.get(("0", a)), values.get(("0", z))
    if total_before is None or total_after is None or total_before <= 0:
        raise ResearchError("총지수 대조값이 없어 근사 기여도 결과를 표시하지 않습니다.")
    actual = (total_after / total_before - 1) * 100
    approx = sum(contributions.values())
    f = b.fact(
        "전국",
        "공식 총지수의 전년 동월 대비",
        c.end,
        rounded(actual),
        "%",
        url,
        "(공식 현재 총지수 / 공식 전년 총지수 - 1) × 100",
        current=total_after,
        prior=total_before,
    )
    g = b.fact(
        "전국",
        "근사 기여도 합계와 총지수 상승률의 차이",
        c.end,
        rounded(approx - actual, 4),
        "%p",
        url,
        "고정 가중치 근사 기여도 합계 - 공식 총지수로 계산한 상승률",
        approximation=approx,
        official=actual,
    )
    b.focus = [f.id, g.id, *[f.id for r in rises[:3] + impacts[:3] for f in facts[r[0]]]]
    b.table(
        "공식 총지수와 계산 결과 대조",
        ["항목", "값"],
        [
            ["총지수로 계산한 상승률(%)", f.value],
            ["근사 기여도 합계(%p)", rounded(approx, 4)],
            ["차이(%p)", g.value],
        ],
        [f.id, g.id],
    )
    b.warnings.extend(
        [
            (
                "기준연도와 가중치 기준의 차이·지수 연결·반올림으로 공식 기여도와 "
                "다릅니다. 근사 순위도 달라질 수 있습니다."
            ),
            "개인의 소비 구성과 체감물가를 측정하지 않습니다. 상승률 둔화는 가격 하락과 다릅니다.",
        ]
    )
    return b.result(
        [
            "458개 말단 품목만 사용; 가중치 합계 1000 검증",
            "지수 상승률·고정 가중치 근사 기여도·공식 총지수 차이 비교",
        ]
    )


def compensation(c, material, version):
    b = Builder(c, max(r["retrieved_at"] for r in material["records"]), version)
    rows = []
    refs = []
    for r in material["records"]:
        if r["company"] not in c.entities:
            continue
        url = ["https://dart.fss.or.kr/dsaf001/main.do?rcpNo=" + r["receipt"]]
        pay = Decimal(r["pay"]["mendng_totamt"].replace(",", ""))
        avg = Decimal(r["employee_average"])
        fs = [
            b.fact(
                r["company"],
                m,
                "2025",
                v,
                u,
                url,
                formula,
                ceo=r["ceo"],
                receipt=r["receipt"],
                employee_note=r["employee_note"],
                location="VIII. 임원 및 직원 등에 관한 사항",
                retrieved_at=r["retrieved_at"],
            )
            for m, v, u, formula in [
                ("대표이사 " + r["ceo"] + " 보수총액", pay, "원", "원자료 값"),
                ("공식 직원 합계 평균급여", avg, "원", "원자료 값"),
                (
                    "대표이사 보수 / 직원 평균급여",
                    rounded(pay / avg),
                    "배",
                    "대표이사 보수총액 / 보고서 직원 합계 평균급여",
                ),
            ]
        ]
        rows.append([r["company"], r["ceo"], str(pay), str(avg), fs[-1].value])
        refs.extend(f.id for f in fs)
        b.focus.extend(f.id for f in fs)
        components = []
        for row in r["pay_components"][1:]:
            label, amount = (row[2], row[3]) if len(row) == 5 else (row[0], row[1])
            components.append([label, amount])
        b.table(
            r["company"] + " · 지급 보수 구성",
            ["구분", "공시 금액(백만원)"],
            components,
            [fs[0].id],
            (
                "상여에 이미 포함된 지급 주식 보상을 다시 더하지 않습니다. "
                "'-'는 0으로 변환하지 않았습니다."
            ),
        )
    b.table(
        "같은 연간 기간의 보수 비교",
        ["회사", "대표이사", "보수총액(원)", "직원 평균급여(원)", "배율(배)"],
        rows,
        refs,
        (
            "연결그룹 전체 임직원 비교가 아닌 해당 법인의 공시입니다. 직원 평균은 "
            "보고서 합계값이며 연말 인원으로 재계산하지 않습니다."
        ),
    )
    b.warnings.extend(
        [
            (
                "CEO 보수는 기본 연봉과 다릅니다. 상여·지급 주식 "
                "보상·일회성 보상을 원문에서 확인하세요."
            ),
            (
                "공시되지 않은 보수는 0이 아닙니다. 미행사·미지급 주식 "
                "보상을 보수총액에 더하지 않습니다."
            ),
            (
                "회사별 직원 평균급여 산정 방식과 반올림이 달라 배율은 근사 "
                "비교입니다. 다른 연도·반기는 검증하지 않았습니다."
            ),
        ]
    )
    return b.result(
        [
            "같은 보고서 접수번호의 대표이사 직위·개인별 보수·직원 합계 대조",
            "공식 평균을 분모로 사용; 남녀 평균의 단순 평균 금지",
        ]
    )


def business_mix(c, material, version):
    b = Builder(c, max(r["retrieved_at"] for r in material["records"]), version)
    overview = []
    ids = []
    for company in c.entities:
        structure = []
        changes = []
        refs = []
        for r in material["records"]:
            if r["company"] != company or not c.start <= r["year"] <= c.end:
                continue
            url = ["https://dart.fss.or.kr/dsaf001/main.do?rcpNo=" + r["receipt"]]
            common = dict(
                receipt=r["receipt"],
                retrieved_at=r["retrieved_at"],
                basis="연결",
                vintage="각 사업연도 보고서의 정정 반영 당기; 비교액은 같은 보고서 전기",
            )
            sales = Decimal(r["financials"]["매출액"]["thstrm_amount"])
            profit = Decimal(r["financials"]["영업이익"]["thstrm_amount"])
            margin = b.fact(
                company,
                "영업이익률",
                r["year"],
                rounded(profit / sales * 100),
                "%",
                url,
                "연결 영업이익 / 연결 매출액 × 100",
                sales=sales,
                operating_profit=profit,
                **common,
            )
            overview.append([company, r["year"], str(sales), str(profit), margin.value])
            ids.append(margin.id)
            total = Decimal(r["total_million"])
            prev = sum(Decimal(s["prior"]) for s in r["segments"])
            for s in r["segments"]:
                current, prior = Decimal(s["current"]), Decimal(s["prior"])
                f = b.fact(
                    company, s["name"] + " 매출", r["year"], current, "백만원", url, **common
                )
                share = b.fact(
                    company,
                    s["name"] + " 매출 비중",
                    r["year"],
                    rounded(current / total * 100),
                    "%",
                    url,
                    "사업 매출 / 해당 보고서 전체 사업 매출 × 100",
                    segment=current,
                    total=total,
                    **common,
                )
                delta = b.fact(
                    company,
                    s["name"] + " 매출 증가액",
                    r["year"],
                    current - prior,
                    "백만원",
                    url,
                    "당기 사업 매출 - 같은 보고서의 전기 사업 매출",
                    current=current,
                    prior=prior,
                    **common,
                )
                pp = b.fact(
                    company,
                    s["name"] + " 매출 비중 변화",
                    r["year"],
                    rounded(current / total * 100 - prior / prev * 100),
                    "%p",
                    url,
                    "당기 사업 비중 - 같은 보고서 전기 사업 비중",
                    current=current,
                    total=total,
                    prior=prior,
                    prior_total=prev,
                    **common,
                )
                structure.append([r["year"], s["name"], f.value, share.value])
                changes.append([r["year"], s["name"], delta.value, pp.value])
                refs.extend([f.id, share.id, delta.id, pp.id])
                if r["year"] == c.end:
                    b.focus.extend([share.id, delta.id, pp.id])
                elif r["year"] == c.start:
                    b.focus.append(share.id)
            if r["year"] in {c.start, c.end}:
                b.focus.insert(0, margin.id)
        b.table(
            company + " · 사업 구성의 변화",
            ["연도", "사업 분류", "매출(백만원)", "비중(%)"],
            structure,
            refs,
            (
                "각 보고서의 사업 구분을 보존합니다. NAVER의 "
                "클라우드/엔터프라이즈를 명칭만 보고 자동 통합하지 않습니다."
            ),
        )
        b.table(
            company + " · 어느 사업의 증가액이 컸나",
            ["연도", "사업 분류", "전기 대비 증가액(백만원)", "비중 변화(%p)"],
            changes,
            refs,
            (
                "같은 보고서에 실린 전기 비교액 기준입니다. 인수·매각·연결 범위 "
                "변화까지 제거한 유기적 성장이나 인과 기여가 아닙니다."
            ),
        )
    b.table(
        "성장과 수익성 함께 보기",
        ["회사", "연도", "연결 매출(원)", "연결 영업이익(원)", "영업이익률(%)"],
        overview,
        ids,
    )
    b.warnings.extend(
        [
            "양사의 사업 분류가 달라 커머스·플랫폼 등을 동일 사업으로 묶지 않습니다.",
            (
                "정정·중단영업·사업 분류 변경으로 앞 보고서 당기와 뒤 보고서 전기가 다를 수 "
                "있습니다. 5년 일괄 성장 기여율을 만들지 않습니다."
            ),
            (
                "사업별 매출 합계의 백만원 반올림과 원 단위 재무제표를 구분합니다. "
                "수치만으로 성장 원인을 단정하지 않습니다."
            ),
        ]
    )
    return b.result(
        [
            "공식 사업보고서 10건의 정정 후 매출표와 연결 재무 수치 대조",
            "사업 비중·같은 보고서 전기 대비 증가액·영업이익률 결정론 계산",
        ]
    )


def analyze(c, material, version="2026-10-05 공식 저장 원자료"):
    funcs = {
        "births": births,
        "migration": migration,
        "prices": prices,
        "compensation": compensation,
        "business_mix": business_mix,
    }
    return funcs[c.tool](c, material.get("datasets", material), version)
