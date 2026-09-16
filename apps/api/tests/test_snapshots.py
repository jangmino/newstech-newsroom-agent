"""Explicit saved-data approvals; no credentials, network, caches, or live quotas."""

import copy
import hashlib
import json

import pytest
from fastapi.testclient import TestClient

from newsroom_agent import main
from newsroom_agent.providers import snapshot
from newsroom_agent.providers.mock_planner import MockQuestionPlanner

QUESTIONS = {
    "kosis": "전국 시·도 15-29세 청년 고용률 2020-2024년 연간 증감 폭 비교",
    "opendart": "삼성전자 2022-2024년 연간 연결 매출액 증감 폭 비교",
}


@pytest.fixture
def client(monkeypatch):
    def forbidden(*args, **kwargs):
        pytest.fail("Snapshot flow must not create live providers or consume live quota")

    for name in ("KosisClient", "OpenDartClient", "get_public_data_limiter", "get_gemini_limiter"):
        monkeypatch.setattr(main, name, forbidden)
    monkeypatch.setattr(main.settings, "live_api_enabled", False)
    monkeypatch.setattr(main.settings, "fallback_snapshot_enabled", True)
    monkeypatch.setattr(main.settings, "public_data_cache_enabled", True)
    return TestClient(main.app)


def prepare(client, source, **extras):
    response = client.post("/api/v1/plan", json={
        "question": QUESTIONS[source], "mode": "snapshot", **extras,
    })
    assert response.status_code == 200, response.text
    plan = response.json()
    conditions = {key: plan["query_plan"][key] for key in (
        "selected_source", "entity", "metric", "period", "comparison", "filters",
    )}
    return plan, {"question": QUESTIONS[source], "mode": "snapshot", "approved": True,
                  "snapshot_id": plan["snapshot"]["snapshot_id"], "conditions": conditions}


@pytest.mark.parametrize("source", QUESTIONS)
def test_preview_has_only_metadata_and_approval_preserves_origin_and_conditions(client, source):
    plan, body = prepare(client, source)
    assert plan["data_mode"] == "snapshot" and plan["snapshot"]["source"] == source
    assert not {"evidence", "brief", "calculation", "raw_values"} & plan.keys()
    assert not {"raw_values", "rows", "observations", "amount"} & plan["snapshot"].keys()
    assert plan["snapshot"]["source_urls"]
    assert not plan["conditions_preserved"]
    response = client.post("/api/v1/execute", json=body)
    assert response.status_code == 200
    result = response.json()
    assert result["snapshot"] == plan["snapshot"] and result["cache"] is None
    assert result["evidence"]["data_mode"] == "snapshot"
    assert result["evidence"]["retrieved_at"] == plan["snapshot"]["captured_at"]
    assert result["brief"]["summary"].startswith("저장 자료 기준:")
    assert result["brief"]["verification_status"] == "review_required"
    assert result["general_response"]["data_mode"] == "mock"
    assert "이번 승인에서 외부 API를 조회하지 않았" in " ".join(result["evidence"]["caveats"])
    for key, value in body["conditions"].items():
        assert result["query_plan"][key] == value
        if key != "filters":
            assert result["evidence"]["query_parameters"][key] == value
        else:
            for field, setting in value.items():
                assert result["evidence"]["query_parameters"][f"filters.{field}"] == setting
    if source == "opendart":
        assert result["financial_calculation"]["change"] == "-1360457000000"
        assert len(result["evidence"]["raw_values"]) == 2
        assert {r["year"] for r in result["evidence"]["raw_values"]} == {2022, 2024}
    else:
        assert result["calculation"]["data_origin"] == "kosis"
        assert len(result["calculation"]["rows"]) == 17
        assert len(result["evidence"]["raw_values"]) == 85


@pytest.mark.parametrize("source", QUESTIONS)
def test_new_approval_recalculates_without_changing_saved_timestamps(client, source):
    _, body = prepare(client, source)
    first = client.post("/api/v1/execute", json=body).json()
    body["conditions"]["comparison"] = "증감률"
    second = client.post("/api/v1/execute", json=body).json()
    assert second["request_id"] != first["request_id"]
    assert second["evidence"]["raw_values"] == first["evidence"]["raw_values"]
    assert second["snapshot"] == first["snapshot"]
    assert second["query_plan"]["comparison"] == "증감률"
    assert second["brief"]["summary"] != first["brief"]["summary"]
    if source == "opendart":
        assert second["financial_calculation"]["change"] == "-0.45"


@pytest.mark.parametrize("entity,count", [("전국 시·도", 17), ("수도권 시·도", 3),
                                         ("비수도권 시·도", 14)])
def test_kosis_snapshot_selects_only_approved_regions_and_years(client, entity, count):
    _, body = prepare(client, "kosis")
    body["conditions"].update(entity=entity, period="2021-2023")
    response = client.post("/api/v1/execute", json=body)
    assert response.status_code == 200
    result = response.json()
    assert len(result["calculation"]["rows"]) == count
    assert len(result["evidence"]["raw_values"]) == count * 3
    assert {r["year"] for r in result["evidence"]["raw_values"]} == {2021, 2022, 2023}
    assert result["query_plan"]["entity"] == entity


@pytest.mark.parametrize("source", QUESTIONS)
@pytest.mark.parametrize("approval", [False, None, "true", 1])
def test_snapshot_requires_strict_approval(client, source, approval):
    _, body = prepare(client, source)
    body["approved"] = approval
    response = client.post("/api/v1/execute", json=body)
    assert response.status_code == 422 and set(response.json()) == {"detail"}


@pytest.mark.parametrize("source", QUESTIONS)
def test_snapshot_requires_current_version_and_does_not_accept_other_source_id(client, source):
    _, body = prepare(client, source)
    original = body.pop("snapshot_id")
    assert client.post("/api/v1/execute", json=body).status_code == 422
    for snapshot_id in ("old-version", "../../.env", snapshot.SPECS[
        "kosis" if source == "opendart" else "opendart"
    ][1]):
        body["snapshot_id"] = snapshot_id
        rejected = client.post("/api/v1/execute", json=body)
        assert rejected.status_code == 409
        assert rejected.json()["detail"]["code"] == "snapshot_changed"
        assert set(rejected.json()) == {"detail"}
        assert rejected.headers["cache-control"] == "no-store"
        assert snapshot_id not in rejected.text
    for mode in ("live", "mock"):
        body.update(snapshot_id=original, mode=mode)
        assert client.post("/api/v1/execute", json=body).status_code == 422


@pytest.mark.parametrize("source", QUESTIONS)
def test_snapshot_flag_blocks_preview_and_execution_independently(client, monkeypatch, source):
    _, body = prepare(client, source)
    monkeypatch.setattr(main.settings, "fallback_snapshot_enabled", False)
    for endpoint, request in (("plan", {"question": QUESTIONS[source], "mode": "snapshot"}),
                              ("execute", body)):
        rejected = client.post(f"/api/v1/{endpoint}", json=request)
        assert rejected.status_code == 503
        assert rejected.json()["detail"]["code"] == "snapshot_disabled"
        assert set(rejected.json()) == {"detail"}


@pytest.mark.parametrize("source,changes", [
    ("opendart", {"period": "2022-2023"}), ("opendart", {"metric": "영업이익"}),
    ("opendart", {"entity": "다른 기업"}),
    ("opendart", {"filters": {"statement_basis": "별도", "report_type": "연간"}}),
    ("kosis", {"period": "2019-2024"}), ("kosis", {"metric": "취업자 수"}),
    ("kosis", {"filters": {"age_range": "15-34세", "frequency": "연간"}}),
])
def test_snapshot_cannot_widen_verified_scope(client, source, changes):
    _, body = prepare(client, source)
    body["conditions"].update(changes)
    rejected = client.post("/api/v1/execute", json=body)
    assert rejected.status_code == 422 and set(rejected.json()) == {"detail"}


def test_preserved_conditions_skip_interpretation_and_invalid_values_require_reselection(
    client, monkeypatch,
):
    _, body = prepare(client, "kosis")
    body["conditions"].update(entity="수도권 시·도", period="2021-2024", comparison="증감률")

    def forbidden(*args, **kwargs):
        pytest.fail("Preserving conditions must not interpret the question again")

    monkeypatch.setattr(MockQuestionPlanner, "interpret", forbidden)
    plan, preserved = prepare(client, "kosis", conditions=body["conditions"])
    assert plan["conditions_preserved"] is True
    assert preserved["conditions"] == body["conditions"]
    body["conditions"]["metric"] = "취업자 수"
    body["conditions"]["filters"]["unexpected"] = "unsupported"
    plan, preserved = prepare(client, "kosis", conditions=body["conditions"])
    assert preserved["conditions"]["metric"] == "" and preserved["conditions"]["filters"] == {}
    assert plan["query_plan"]["clarification_required"]
    assert "metric" in plan["required_fields"] and "filters" in plan["required_fields"]
    assert client.post("/api/v1/execute", json=preserved).status_code == 422


def test_preserved_conditions_are_snapshot_only_and_cannot_change_question_source(client):
    _, body = prepare(client, "opendart")
    for mode, method in (("live", "mock_rules"), ("mock", "mock_rules"), ("snapshot", "gemini")):
        response = client.post("/api/v1/plan", json={
            "question": body["question"], "conditions": body["conditions"],
            "mode": mode, "interpretation_method": method,
        })
        assert response.status_code == 422
    for endpoint in ("plan", "execute"):
        request = {**body, "question": QUESTIONS["kosis"]}
        if endpoint == "plan":
            request.pop("approved")
            request.pop("snapshot_id")
        response = client.post(f"/api/v1/{endpoint}", json=request)
        assert response.status_code == 422


@pytest.mark.parametrize("failure", ["missing", "changed", "malformed", "invalid_values"])
@pytest.mark.parametrize("source", QUESTIONS)
def test_missing_changed_or_invalid_snapshot_stops_without_fallback(
    client, monkeypatch, source, failure,
):
    _, body = prepare(client, source)
    filename, version, digest = snapshot.SPECS[source]
    original = snapshot._read(filename)
    if failure == "missing":
        def missing(_):
            raise OSError("private filename must not appear")
        monkeypatch.setattr(snapshot, "_read", missing)
    else:
        data = json.loads(original)
        if failure == "invalid_values":
            if source == "kosis":
                data["rows"].pop()
            else:
                data["observations"][1]["currency"] = "USD"
        replacement = json.dumps(data).encode() if failure == "invalid_values" else b"bad-data"
        monkeypatch.setattr(snapshot, "_read", lambda _: replacement)
        if failure in ("malformed", "invalid_values"):
            monkeypatch.setitem(snapshot.SPECS, source,
                                (filename, version, hashlib.sha256(replacement).hexdigest()))
    for endpoint, request in (("plan", {"question": QUESTIONS[source], "mode": "snapshot"}),
                              ("execute", body)):
        rejected = client.post(f"/api/v1/{endpoint}", json=request)
        assert rejected.status_code == 503
        assert rejected.json()["detail"]["code"] == "snapshot_unavailable"
        assert "private filename" not in rejected.text and filename not in rejected.text
        assert set(rejected.json()) == {"detail"}


def test_live_failure_stays_failure_until_snapshot_is_selected_and_reapproved(client):
    _, body = prepare(client, "kosis")
    live = copy.deepcopy(body)
    live.update(mode="live")
    live.pop("snapshot_id")
    failed = client.post("/api/v1/execute", json=live)
    assert failed.status_code == 503 and failed.json()["detail"]["code"] == "kosis_disabled"
    assert set(failed.json()) == {"detail"}
    plan, saved = prepare(client, "kosis", conditions=live["conditions"])
    assert "evidence" not in plan
    assert client.post("/api/v1/execute", json=saved).json()["evidence"]["data_mode"] == "snapshot"


def test_ambiguous_snapshot_plan_has_no_dataset_or_evidence(client):
    response = client.post("/api/v1/plan", json={"question": "무엇을 볼까요", "mode": "snapshot"})
    assert response.status_code == 200
    assert response.json()["snapshot"] is None
    assert response.json()["query_plan"]["clarification_required"]
    assert "evidence" not in response.json()
