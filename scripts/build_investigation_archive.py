"""Build verified extracts from separately collected public inputs; no network or credentials."""

import argparse
import hashlib
import json
import re
from decimal import Decimal
from pathlib import Path

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument("--input", type=Path, required=True)
parser.add_argument("--output", type=Path, required=True)
args = parser.parse_args()
p, out = args.input, args.output
out.mkdir(parents=True, exist_ok=True)


def read(n):
    return json.loads((p / (n + ".json")).read_text())


def write(n, v):
    (out / (n + ".json")).write_text(
        json.dumps(v, ensure_ascii=False, separators=(",", ":")) + "\n"
    )


fields = [
    "ORG_ID",
    "TBL_ID",
    "ITM_ID",
    "ITM_NM",
    "C1",
    "C1_NM",
    "C2",
    "C2_NM",
    "C3",
    "C3_NM",
    "C4",
    "C4_NM",
    "DT",
    "PRD_DE",
    "PRD_SE",
    "UNIT_NM",
    "LST_CHN_DE",
]
for name, names in {
    "births": ["births-200401", "births-201201", "births-recent"],
    "migration": ["migration", "population-correct", "od"],
    "prices": ["cpi-202509", "cpi-202603"],
}.items():
    ds = []
    for n in names:
        a = read(n)
        ds.append(
            dict(
                name=n,
                parameters=a["parameters"],
                retrieved_at=a["at"],
                rows=[{k: r[k] for k in fields if k in r} for r in a["data"]],
            )
        )
    write(name, dict(version="2026-10-05", datasets=ds))
for name, src in [
    ("births-meta", "births-meta"),
    ("migration-meta", "migration-meta"),
    ("population-meta", "population-meta"),
    ("od-meta", "od-meta"),
]:
    write(name, read(src)["data"])
meta = [r for r in read("cpi-meta")["data"] if r.get("OBJ_ID_SN") == "2"]
parents = {r.get("UP_ITM_ID") for r in meta}
leaves = {
    r["ITM_ID"]: r["ITM_NM"]
    for r in meta
    if r["ITM_ID"] not in parents and r["ITM_ID"] != "0"
}
weights = [
    r for r in read("cpi-weights")["data"] if r["C1"] == "T10" and r["C2"] in leaves
]
assert len(weights) == len(leaves) == 458
assert sum(Decimal(r["WGT_CO"]) for r in weights) == 1000
write(
    "price-weights",
    dict(
        retrieved_at=read("cpi-weights")["at"],
        table="DT_1J22001",
        index_base="2020",
        weight_base="2022",
        items=weights,
    ),
)
records = []
comp = []
sources = []
indices = {"naver": [30, 26, 30, 33, 43], "kakao": [9, 9, 52, 50, 46]}
for co, name in [("naver", "NAVER"), ("kakao", "카카오")]:
    reports = {
        int(re.search(r"\((\d{4})", r["report_nm"])[1]): r
        for r in read(co + "-reports")["data"]["list"]
    }
    for y in range(2021, 2026):
        rec = reports[y]
        receipt = rec["rcept_no"]
        tables = read(co + "-" + receipt + ".tables")
        idx = indices[co][y - 2021]
        table = tables[idx]
        rows = table["rows"]
        file = p / (co + "-" + receipt + ".xml")
        source = {
            "company": name,
            "year": str(y),
            "receipt": receipt,
            "report_title": rec["report_nm"],
            "url": "https://dart.fss.or.kr/dsaf001/main.do?rcpNo=" + receipt,
            "document_sha256": hashlib.sha256(file.read_bytes()).hexdigest(),
            "table_index": idx,
            "location": "II. 사업의 내용 / 주요제품 및 서비스 또는 매출 및 수주상황",
            "unit": "백만원",
            "rows": rows,
            "retrieved_at": read(co + "-finance-" + str(y))["at"],
        }
        sources.append(source)
        finance = read(co + "-finance-" + str(y))
        frows = finance["data"]["list"]
        selected = {}
        for metric, aid in [
            ("매출액", "ifrs-full_Revenue"),
            ("영업이익", "dart_OperatingIncomeLoss"),
        ]:
            if co == "kakao" and y in [2021, 2022] and metric == "매출액":
                aid = "ifrs-full_GrossProfit"
            rr = [
                r
                for r in frows
                if r["account_id"] == aid and r["sj_div"] in ["IS", "CIS"]
            ]
            assert rr and all(r["thstrm_amount"] == rr[0]["thstrm_amount"] for r in rr)
            assert rr[0]["rcept_no"] == receipt, (name, y, rr[0]["rcept_no"], receipt)
            selected[metric] = rr[0]
        seg = []
        if co == "naver":
            total = rows[3][1]
            for row in rows[4:]:
                seg.append(
                    dict(
                        name=row[0].lstrip("- "),
                        current=row[1].replace(",", ""),
                        prior=row[3].replace(",", ""),
                    )
                )
        else:
            total = rows[-1][1]
            for row in rows:
                if row and row[0] in ["플랫폼 부문", "콘텐츠 부문"]:
                    seg.append(
                        dict(
                            name=row[0],
                            current=row[4].replace(",", ""),
                            prior=row[6].replace(",", ""),
                        )
                    )
        total = int(total.replace(",", ""))
        assert abs(sum(int(s["current"]) for s in seg) - total) <= 1
        assert (
            abs(total * 1000000 - int(selected["매출액"]["thstrm_amount"])) <= 1000000
        ), (name, y, total, selected["매출액"]["thstrm_amount"])
        records.append(
            dict(
                company=name,
                year=str(y),
                receipt=receipt,
                segments=seg,
                total_million=str(total),
                financials=selected,
                retrieved_at=finance["at"],
            )
        )
    # Verified annual employee total and named CEO with same receipt.
    receipt = reports[2025]["rcept_no"]
    tables = read(co + "-" + receipt + ".tables")
    empindex = 2261 if co == "naver" else 2444
    payindex = 2282 if co == "naver" else 2463
    totalrow = tables[empindex]["rows"][-1]
    average = totalrow[-2]
    assert average in ["146", "109"]
    ceo = "최수연" if co == "naver" else "정신아"
    pay = [
        r
        for r in read(co + "-pay")["data"]["list"]
        if r["nm"] == ceo and r["ofcps"] == "대표이사"
    ]
    assert len(pay) == 1 and pay[0]["rcept_no"] == receipt
    executive = [r for r in read(co + "-executives")["data"]["list"] if r["nm"] == ceo]
    assert executive
    comp.append(
        dict(
            company=name,
            year="2025",
            receipt=receipt,
            ceo=ceo,
            pay=pay[0],
            employee_average=str(int(average) * 1000000),
            employee_table=tables[empindex]["rows"],
            employee_note=tables[empindex + 1]["before"][-1200:],
            pay_components=tables[payindex]["rows"],
            employee_table_index=empindex,
            pay_table_index=payindex,
            retrieved_at=read(co + "-pay")["at"],
        )
    )
write("business_mix", dict(version="2026-10-05", records=records, sources=sources))
write("compensation", dict(version="2026-10-05", records=comp))
manifest = {
    f.name: hashlib.sha256(f.read_bytes()).hexdigest()
    for f in out.glob("*.json")
    if f.name != "manifest.json"
}
write("manifest", dict(version="2026-10-05", files=manifest))
print("files", len(manifest), "segments", len(records), "weights", len(weights))
