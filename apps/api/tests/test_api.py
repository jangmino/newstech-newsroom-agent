from fastapi.testclient import TestClient

from newsroom_agent.main import app

client = TestClient(app)


def test_health_reports_mock_mode() -> None:
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json()["public_data_mode"] == "mock"
    assert response.json()["live_api_enabled"] is False


def test_kosis_question_is_routed_and_requires_clarification() -> None:
    response = client.post(
        "/api/v1/analyze",
        json={"question": "최근 5년 동안 청년 고용이 가장 좋아진 지역은 어디인가?", "mode": "mock"},
    )
    assert response.status_code == 200
    payload = response.json()
    assert payload["query_plan"]["selected_source"] == "kosis"
    assert payload["query_plan"]["clarification_required"] is True
    assert payload["evidence"]["data_mode"] == "mock"
    assert payload["brief"]["verification_status"] == "review_required"


def test_opendart_question_is_routed() -> None:
    response = client.post(
        "/api/v1/analyze",
        json={"question": "삼성전자의 최근 실적은 악화됐는가?", "mode": "mock"},
    )
    assert response.status_code == 200
    assert response.json()["query_plan"]["selected_source"] == "opendart"


def test_live_mode_is_disabled_by_default() -> None:
    response = client.post(
        "/api/v1/analyze",
        json={"question": "청년 고용률을 알려줘", "mode": "live"},
    )
    assert response.status_code == 503
