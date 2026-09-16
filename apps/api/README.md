# API

FastAPI 백엔드입니다. 로컬 서버는 저장소 루트에서 `make dev-api`로 실행합니다.
일반 로컬 실행은 기존 설정에 따라 `.env`를 읽습니다. 자동 테스트는 앱을 import하기 전에
키가 없는 테스트 설정을 주입하며 `.env`와 실제 자격증명을 읽지 않습니다.
외부 네트워크 연결도 테스트에서 차단합니다.

## 참가자 흐름

```text
질문 → POST /api/v1/plan → 조건 편집·확인
     → ‘이 조건으로 조회’ → POST /api/v1/execute → 일반 응답 예시·근거 기반 브리핑 비교
```

새 API는 기본 `mode=mock`, 선택형 `live`를 받습니다. live는 서버의 전역 live와
`PUBLIC_DATA_MODE=live` 외에 질문에 맞는 공급자의 활성화·키 설정이 필요합니다.
OpenDART는 `OPENDART_ENABLED=true`, KOSIS는 `KOSIS_ENABLED=true`를 각각 검사합니다.
`snapshot`은 422이며 자료·승인 이력을 저장하지 않습니다. 질문 해석 방식은 자료 모드와
독립적입니다. [OpenDART 계약](../../docs/OPENDART_REVENUE.md)과
[KOSIS 계약](../../docs/KOSIS_EMPLOYMENT.md)의 확인된 범위만 지원합니다.

### POST /api/v1/plan

요청:

```json
{"question":"최근 5년 동안 청년 고용이 가장 좋아진 지역은 어디인가?","mode":"mock"}
```

응답은 `request_id`, `question`, `query_plan`, `required_fields`, `field_options`, `available_years`,
`interpretation_method`, `interpretation_model`, `data_mode`입니다.
`evidence`, `brief`, `general_response`, `calculation`, `financial_calculation`은 포함하지 않고, 모의 결과도 생성하지 않습니다.

- `query_plan`: 기존 계획 구조. 질문에서 명확하게 찾은 조건만 채웁니다.
- `interpretation_method`: `mock_rules` 또는 `gemini`. 요청에서 생략하면 `mock_rules`입니다.
- `interpretation_model`: mock은 `null`, Gemini는 서버에서 설정한 모델명입니다.
- `required_fields`: 해결할 조건의 경로. 예: `metric`, `period`, `filters.age_range`.
- `field_options`: 자료원별 지원 선택값. 프런트엔드는 이 목록으로 입력란을 구성합니다.
- `available_years`: KOSIS mock/live 지원 연도 `[2020, 2021, 2022, 2023, 2024]`.
  OpenDART live는 `[2022, 2024]`, OpenDART mock은 빈 배열입니다.
- `data_mode`: 요청에서 확정한 `mock` 또는 `live`. 계획 단계에는 공공자료를 조회하지 않습니다.
- `clarification_required`와 `clarification_questions`: 계획 당시의 미해결 조건과 한국어 안내.
- 자료원이 `undetermined`이면 질문을 구체화해야 합니다.
- 모의 규칙은 키워드와 명시적인 조건 문자열만 해석합니다. Gemini도 기존 자료원 범위
  검사와 지원 조건 검증을 통과해야 하며, 자유 질의 전체를 지원하지 않습니다.
- ‘최근 5년’, ‘실적 악화’, 복수 지표·기간 등은 임의로 하나를 정하지 않습니다.
- 기업공시·국가통계 단서가 함께 있으면 키워드 개수로 한쪽을 선택하지 않고 질문을
  나누도록 안내합니다. 지원하지 않는 조건 값과 불확실한 값은 비워 반환합니다.
- 이번 모의 실습의 주기는 연간으로 제시합니다. 질문에서 분기·월간을 명시했다면
  해당 조건을 비워 두고 지원하는 연간 기준을 참가자가 직접 확인하게 합니다.

내부 해석기는 JSON 문자열만 반환하고, 서버가 형식·자료원·지원 조건을 검증한 뒤
선택 이유·확인 안내·필수 항목을 만듭니다. 공개 응답에 원래 해석기 출력이나 공급자
오류를 넣지 않습니다. [내부 계약](../../docs/QUESTION_PLANNING.md)을 참고하십시오.

Gemini 요청 예시는 `{"question":"청년 고용률 비교","mode":"mock","interpretation_method":"gemini"}`입니다.
서버의 `GEMINI_PLANNER_ENABLED=true`, `LIVE_API_ENABLED=true`와 백엔드 인증 설정이
필요합니다. 모델·키·HTTP 옵션을 요청으로 받을 수 없습니다. 조건 승인 후 실행에서는
해석기를 호출하지 않으며 `/execute`에 `interpretation_method`를 넣으면 422입니다.
기존 요청은 기본 mock으로 계속 작동합니다. `/health`의 `gemini_planner_enabled`는
두 설정의 활성화 여부만 나타내며 인증·실제 모델 접근 성공을 보증하지 않습니다.

### POST /api/v1/execute

요청:

```json
{
  "question": "최근 5년 동안 청년 고용이 가장 좋아진 지역은 어디인가?",
  "mode": "mock",
  "approved": true,
  "conditions": {
    "selected_source": "kosis",
    "entity": "수도권 시·도",
    "metric": "고용률",
    "period": "2020-2024",
    "comparison": "증감 폭",
    "filters": {"age_range": "15-29세", "frequency": "연간"}
  }
}
```

`approved`는 JSON boolean `true`만 허용합니다. 생략, `false`, 문자열, 숫자는 거부합니다.
서버는 질문과 자료원의 일치, 필수값, 지원 선택값, 기간, 추가 조건을 다시 검증합니다.
이때 질문 해석기를 다시 호출하지 않으며 참가자가 승인한 값을 그대로 사용합니다.
`clarification_required`, `selection_reason` 등 서버 계산 필드를 요청에 넣을 수 없습니다.

아래는 mock 모드의 선택 범위입니다.

| 조건 | KOSIS | OpenDART |
|---|---|---|
| 대상 | 전국 시·도 / 수도권 시·도 / 비수도권 시·도 | 삼성전자 |
| 지표 | 고용률 / 취업자 수 | 매출액 / 영업이익 |
| 비교 기준 | 증감 폭 / 증감률 | 증감 폭 / 증감률 |
| 추가 조건 | `age_range`: 15-29세 / 15-34세, `frequency`: 연간 | `statement_basis`: 연결 / 별도, `report_type`: 연간 |
| 기간 | `YYYY-YYYY`, 2020 ≤ 시작 < 종료 ≤ 2024 | `YYYY-YYYY`, 1900 ≤ 시작 < 종료 ≤ 2100 |

이 선택 범위는 **UI 실습을 위한 모의 조건**입니다. 실제 통계표·공시의 지원 범위나 자료
존재를 보증하지 않습니다. 비교는 시작·종료 연도의 연간 값을 대상으로 설계합니다.

성공 응답은 `ExecutionResponse`입니다. 기존 `AnalysisResponse`의 모든 필드를 유지하며
`general_response`, `calculation`, `financial_calculation`, `cache`를 추가합니다. 기존 요청 형식은 바꾸지 않습니다.

- `query_plan`: 검증된 승인 조건. `clarification_required=false`이며 미해결 질문은 없습니다.
- `evidence.query_parameters`: 같은 조건을 문자열 사전으로 표시합니다.
  필터 키는 `filters.age_range`처럼 경로를 유지합니다.
- 단위와 계산식은 승인된 지표·비교 기준에 맞춥니다. 고용률의 증감 폭은 `%p`,
  상대 증감률은 `%`입니다.
- `raw_values`: 청년 고용은 가상 지역별 시작·종료 값, 연도, 지표, 연령, 단위를 제공합니다.
  숫자는 십진 문자열이며 누락은 `null`입니다. 기업 실적은 빈 배열입니다.
- `retrieved_at`: 가상 자료 계산 시각 또는 모의 결과 생성 시각입니다. 공식 자료 조회 시각이 아닙니다.
- mock에서는 `data_mode=mock`, 모든 결과는 `verification_status=review_required`입니다.
- `financial_calculation`: mock에서는 `null`, 실제 매출액은 아래 별도 계약을 사용합니다.
- 브리핑은 승인 조건과 가상 계산 결과를 구분해 표시합니다. 실제 수치가 검증된 사실인 것처럼 표현하지 않습니다.
- `general_response`: 질문 유형별로 미리 작성한 일반 응답 예시입니다.
  `text`는 한국어 설명, `data_mode`는 `mock`, `generation_method`는 `scripted`입니다.
  실제 모델 출력·기록·공식 자료 조회가 아니며 승인 조건에 따라 다시 작성하지 않습니다.

두 응답은 같은 최상위 `question`을 공유합니다. 예시는 기존 청년 고용·기업 실적 두 유형만
지원하며 실제 지역 순위나 기업의 실제 실적 수치를 만들어 넣지 않습니다. 같은 질문에서
조건을 수정하고 재승인하면 일반 예시는 그대로이고 `query_plan`, `evidence`, `brief`는
새 승인 조건을 반영합니다. 승인 누락·조건 오류 응답에는 두 응답 모두 포함하지 않습니다.

프런트엔드는 승인 후 두 응답을 나란히 표시하고 조회 조건·자료원·단위·계산식·시각·
원자료·사람 검토 항목을 비교합니다. 좁은 화면에서는 위아래로 배치합니다.
모의 조회에서는 양쪽 모두 mock 안내를 유지하고, 일반 응답에는 사람 검토 필요, 근거 기반 브리핑에는
참가자의 실습 검토 진행 상태를 표시합니다. 청년 고용 계산에 사용한 숫자는
공식 통계가 아닌 가상 자료임을 명시합니다. 질문이나 조건을 바꾸면 비교 화면 전체를
숨기고 재승인을 요구합니다.

같은 질문에서 바꾼 조건으로 실행에 성공하면 직전 성공 응답과 새 응답을 화면에서
비교합니다. 프론트엔드 메모리에만 두 응답을 유지하며, 별도 비교 API나 추가 조회는
없습니다. 실패·취소된 요청은 비교 기준을 갱신하지 않습니다. 기존 요청·응답 계약과
검증 상태는 그대로입니다. [조건 변경 전후 비교](../../docs/CONDITION_COMPARISON.md)를 참고하십시오.

### OpenDART 실제 실행 계약

위 요청 구조에 `mode=live`를 사용합니다. 조건은 `selected_source=opendart`,
`entity=삼성전자`, `metric=매출액`, `period=2022-2024`, `comparison=증감 폭|증감률`,
`filters={"statement_basis":"연결","report_type":"연간"}`만 지원합니다.
지원하지 않는 계획 값은 비우고 한국어 확인 안내를 제공합니다. 실행 조건 오류는 외부
요청 전에 422로 거부하며, 참가자가 승인한 조건을 다시 해석하거나 바꾸지 않습니다.

성공 응답은 `evidence.data_mode=live`, `calculation=null`이며 다음을 추가합니다.

- `financial_calculation`: `data_origin=opendart`, 시작·종료 연도/값, 입력 단위 `원`,
  변화값, 결과 단위 `원|%`, 표시 소수 자릿수 `0|2`, 상태 `calculated|zero_baseline`, 이유.
- `evidence.raw_values`: 연도별 정확한 금액 문자열, API 금액 원문, KRW/원,
  계정 ID/명·재무제표 구분, 접수번호·원문 링크·조회 시각, 키를 제외한 API 조회 인자.
- 승인 조건은 `query_plan`과 `evidence.query_parameters`에 동일하게 남깁니다.
- 브리핑은 조회값과 Decimal 계산으로 구성하며, 사람 검토 필요를 유지합니다.
- `general_response`는 계속 고정된 mock 예시입니다. 실제 조회 결과와 구분합니다.

원 단위 증감 폭은 정수 그대로, 증감률은 소수 둘째 자리까지 반올림합니다. 시작값 0의
증감률은 `change=null`과 한국어 이유를 반환합니다. 두 연도 중 하나라도 조회·정규화에
실패하면 근거·브리핑 전체를 반환하지 않습니다. 모의 자료나 fixture로 자동 대체하지 않습니다.

공급자 오류는 503 `opendart_<code>`(한도는 429 `opendart_rate_limited`), 안전한 한국어
메시지와 빈 `field_errors`입니다. 설정 비활성은 `opendart_disabled`, 키 누락은
`opendart_configuration`, 조회 없음은 `opendart_no_data`입니다. 전체 오류 목록·정확한
필드는 [조회 계약](../../docs/OPENDART_REVENUE.md)을 따릅니다.

### KOSIS 실제 실행 계약

위 요청 구조에 `mode=live`를 사용합니다. `selected_source=kosis`,
`entity=전국 시·도|수도권 시·도|비수도권 시·도`, `metric=고용률`,
`period=YYYY-YYYY`(2020 ≤ 시작 < 종료 ≤ 2024), `comparison=증감 폭|증감률`,
`filters={"age_range":"15-29세","frequency":"연간"}`만 지원합니다.
15~34세·취업자 수·월/분기 등을 임의로 지원 조건으로 바꾸지 않습니다. `/plan`의 지원
선택값을 제한하고 미지원 값은 비워 참가자가 결정하도록 합니다.

승인·필수 조건·질문과 자료원 일치를 검증한 뒤 필요한 경우 고정 통계표를 한 번 조회합니다.
최대 17개 시도 × 5개 연도 = 85개 셀이며 모든 요청 셀의 정규화에 성공해야 계산합니다.
수도권은 서울·인천·경기 3개, 비수도권은 나머지 14개를 각각 비교하며 권역 평균은 없습니다.
조건 재승인은 항상 필요하며 같은 자료는 아래 캐시 계약에 따라 재사용할 수 있습니다.
비교 기준만 바꾸면 자료를 재사용하여 다시 계산합니다. 자동 재시도·snapshot 대체는 없습니다.

성공 응답은 `evidence.data_mode=live`, `financial_calculation=null`입니다.

- `calculation`: 아래 가상 계산과 같은 행 계약이며 `data_origin=kosis`,
  `dataset_id=kosis:101:DT_1DA7015S:T90:75:annual`, 입력 `%`, 결과 `%p|%`입니다.
  Decimal로 시작·종료 값의 변화를 계산하고 반올림 전 순위·공동 순위를 정합니다.
  0 기준 증감률은 `zero_baseline`, `change=null`, `rank=null`과 이유를 표시합니다.
- `evidence.query_parameters`: 검증된 승인 조건과 필터를 그대로 보존합니다.
- `evidence.raw_values`: 기간 내 **모든 연간 셀**을 담습니다. `region`, `region_code`,
  `year`(정수), `value`(십진 문자열), `raw_value`(공표 문자열), `unit=%`,
  `last_changed_at`(날짜), `retrieved_at`(시각), `source_url`(키 없는 공식 표 링크),
  `org_id=101`, `table_id=DT_1DA7015S`, `item_id=T90`, `age_code=75`, `period_code=A`입니다.
  공개 조회 인자는 이 식별 코드·승인 대상·기간과 자료 계약의 고정 인자로 재구성할 수 있습니다.
- `evidence.retrieved_at`: 정규화에 사용한 API 응답 수신 시각입니다. 자료 최종수정일과
  구분합니다. 조회한 원자료와 코드 계산으로 브리핑을 구성하며 모델은 호출하지 않습니다.
- `general_response`는 고정 mock, `brief.verification_status`는 `review_required`입니다.

공급자 오류는 503 `kosis_<code>`(한도는 429 `kosis_rate_limited`)와 고정 한국어 안내,
빈 `field_errors`를 반환합니다. 전체 목록은 [자료 계약](../../docs/KOSIS_EMPLOYMENT.md#실제-실행과-오류-계약)을
따릅니다. 전역 live가 꺼진 불명확한 질문은 503 `live_disabled`입니다.
오류에는 원래 응답·인증 URL을 넣지 않으며 근거·브리핑도 반환하지 않습니다.

프론트엔드는 결과의 자료 모드·자료원이 승인값과 같은지, KOSIS live의 계산 출처가
`kosis`인지 확인합니다. 출처가 다른 성공 응답도 표시하지 않습니다. 원표 링크·연간 값·
수정일·통계 코드와 실제 통계용 검토 문구를 표시하고 조건 변경 시 숨김·초기화를 유지합니다.

### 공공자료 캐시 계약

M3에서 `/execute` 응답에만 nullable `cache`를 추가했습니다. mock·캐시 비활성은 `null`이며
기존 `/analyze`와 `/plan`에는 이 필드를 추가하지 않습니다. `evidence.data_mode=live`는
공식 자료 출처를 의미하며 이번 승인에서 외부 조회했는지는 `cache.status`로 구분합니다.

| 필드 | 의미 |
|---|---|
| `status` | `miss`: 새 조회 시작, `hit`: 완료 자료 재사용, `coalesced`: 진행 중 동일 조회 공유 |
| `scope` | `process`: 단일 프로세스 메모리 |
| `stored_at`, `expires_at` | 전체 정규화 완료 후 저장 시각과 재사용 기한, ISO 시각 |
| `ttl_seconds`, `age_seconds` | 저장부터의 유효기간과 이번 응답 구성 때 경과 초 |

기본 `PUBLIC_DATA_CACHE_ENABLED=true`, `CACHE_TTL_SECONDS=3600`, `CACHE_MAX_ENTRIES=64`입니다.
실제 조회의 승인·활성화·조건 검증을 먼저 통과해야 하며 원래 조회 시각·출처를 유지합니다.
KOSIS는 조회 조건의 연간 자료 묶음, OpenDART는 두 연도 한 쌍만 보관합니다. 실패·부분
결과는 캐시하지 않습니다. 매 승인마다 계산·브리핑·요청 ID는 새로 만들며 검토 상태는
이어받지 않습니다. 만료 후 실패에도 오래된 자료를 반환하지 않습니다.
재시작 시 초기화되고 워커/인스턴스 간 공유는 없습니다. 상세 수명·취소·키·검증은
[공공자료 캐시](../../docs/PUBLIC_DATA_CACHE.md)를 따릅니다.

### 공공자료 호출·동시 실행 제한 계약

실제 HTTP 직전에 자료원별 공유 한도를 적용합니다. 기본
`PUBLIC_DATA_REQUESTS_PER_MINUTE=30`은 최근 60초 시작 횟수,
`PUBLIC_DATA_MAX_CONCURRENT_REQUESTS=2`는 응답을 읽고 닫을 때까지의 동시 요청 수입니다.
OpenDART 두 연도는 각각 1회입니다. 캐시 적중·동일 요청 공유는 추가 한도를 쓰지 않으며,
캐시 비활성도 실제 HTTP 제한을 우회하지 않습니다. Gemini와 mock은 이 한도와 분리합니다.

`/execute` 오류는 HTTP 429와 기존 `detail.code/message/field_errors`에
`source: kosis|opendart`, `scope: process`, `retry_after_seconds: number|null`을 추가합니다.
횟수 제한은 `public_data_rate_limited`와 예상 대기 정수 1~60초, `Retry-After` 헤더를 반환합니다.
동시 실행 제한은 `public_data_busy`, 예상 초는 null이며 `Retry-After`가 없습니다.
두 오류 모두 `Cache-Control: no-store`이며 근거·브리핑은 반환하지 않습니다.
공급기관 자체의 한도는 기존 `opendart_rate_limited|kosis_rate_limited`로 구분합니다.

실패·시간 초과·취소도 시작 횟수에는 포함하며 동시 실행 자리는 반환합니다. OpenDART
두 번째 호출이 거절되면 부분 결과를 버립니다. 자동 재시도·대기열·자료 대체는 없습니다.
한도는 재시작 시 초기화되고 프로세스 간 공유하지 않습니다.
[전체 계약·검증](../../docs/PUBLIC_DATA_LIMITS.md)을 따릅니다. 기존 성공 응답과 `/analyze`는 유지합니다.

### 가상 계산 계약

청년 고용의 `calculation`은 다음 구조입니다. 기업 실적에서는 `null`입니다.

| 필드 | 의미 |
|---|---|
| `dataset_id`, `data_origin` | `synthetic-employment-v1`, `synthetic` |
| `start_year`, `end_year` | 승인된 시작·종료 연도 |
| `input_unit`, `result_unit` | 입력 `%` 또는 `천 명`, 결과 `%p` / `천 명` / 상대 증감률 `%` |
| `decimal_places`, `ranking_method` | 2자리 표시, 반올림 전 값 내림차순·동률 공동 순위(1, 1, 3) |
| `rows` | 계산 가능 행부터 순위순, 계산 불가 행은 마지막에 지역명순 |
| `warnings` | 계산 불가 지역의 이유와 일부 지역만 순위를 매겼다는 안내 |

각 행은 `region`, `start_value`, `end_value`, `change`, `rank`, `status`, `reason`입니다.
값과 변화값은 십진 문자열이며 누락·계산 불가는 `null`로 유지합니다. `rank`는 정수 또는
`null`입니다. `status`는 `calculated`, `missing_value`, `zero_baseline` 중 하나입니다.
계산 불가 행은 한국어 `reason`을 표시하며 순위를 만들지 않습니다. 0 기준값은 상대
증감률에서만 계산 불가입니다. 변화값은 Decimal로 계산하고 `ROUND_HALF_UP`으로
소수 2자리까지 표시합니다. 표시값이 같아도 반올림 전 값이 다르면 순위는 다릅니다.

‘전국 시·도’는 가상 지역 A~D 전체, ‘수도권 시·도’는 A·B, ‘비수도권 시·도’는 C·D입니다.
`evidence.source_name`과 `table_or_report`에 가상 자료 및 공식 통계 아님을 명시합니다.
승인 연령·지표·대상·기간별로 가상 자료를 선택하며, 질문의 원래 조건으로 되돌리지 않습니다.
중간 연도의 추세는 분석하지 않습니다. [실습 안내](../../fixtures/synthetic/README.md)에
비교 기준에 따라 1위가 달라지는 예와 누락값 예를 정리했습니다.

요청 ID는 요청 식별자입니다. 서버에 계획 세션을 저장하지 않으며, 승인 조건 전체를 매번
전달합니다. 승인 플래그는 참가자 흐름을 위한 계약이며 인증·감사 증명 기능은 아닙니다.
참가자의 검토 체크리스트는 현재 결과 화면에만 유지하는 프론트엔드 상태입니다.
API의 `brief.verification_status=review_required`와 구분하고 이 값을 바꾸지 않습니다.
검토 내용을 서버에 전송·저장하는 API는 없습니다. 전체 체크도 사실 검증 완료나 기사
사용 승인이 아닙니다. [사람 검토 흐름](../../docs/REVIEW_FLOW.md)을 참고하십시오.

### 오류

질문 해석의 형식·자료원 계약을 검증하지 못하면 503 `invalid_planner_output`,
해석기에서 결과를 얻지 못하면 503 `planner_unavailable`을 반환합니다. 아래와 같은
`detail` 구조를 사용하며 한국어 재시도 안내와 `field_errors={}`를 제공합니다.
이때 계획·근거·브리핑은 반환하지 않고 다른 해석기로 자동 대체하지 않습니다.

Gemini 전용 오류도 같은 `detail` 구조와 빈 `field_errors`를 사용합니다.

| HTTP | code | 의미 |
|---|---|---|
| 503 | `planner_disabled` | 서버에서 실제 해석을 활성화하지 않음 |
| 503 | `planner_configuration_error` | 인증 방식·필수 설정·모델명 형식 확인 필요 |
| 503 | `planner_timeout` | HTTP 타임아웃 또는 공급자의 시간 초과 |
| 429 | `planner_rate_limited` | 프로세스의 분당/동시 한도 또는 공급자 429 |

권한·모델 접근·기타 공급자 장애는 안전한 `planner_unavailable`로 반환합니다.
차단·중단·빈 응답·도구 출력은 `invalid_planner_output`입니다. 자동 재시도는 없고
참가자가 직접 재시도해야 합니다. 승인 실패나 질문 변경 때 기존 결과를 다시 표시하지 않습니다.

새 API의 입력 오류는 422와 다음 구조를 반환합니다. 형식 오류는 `invalid_request`,
조건 검증 오류는 `invalid_conditions`입니다. 원래 입력값이나 내부 예외는 반환하지 않습니다.

```json
{
  "detail": {
    "code": "invalid_conditions",
    "message": "조회 전에 확인이 필요한 조건이 있습니다.",
    "field_errors": {"period": "기간을 시작 연도-종료 연도로 입력해 주세요. 예: 2020-2024."}
  }
}
```

질문은 공백 제거 후 3~1,000자입니다. 클라이언트는 실패 시 입력을 유지하고 한국어로 안내합니다.
가상 자료의 단위 불일치·비정상 숫자·중복 지역은 503 `invalid_mock_data`와 한국어
안내를 반환합니다. 같은 오류 구조를 사용하며 `field_errors={}`입니다. 원자료나 내부
예외 내용은 오류 응답에 넣지 않고, 다른 결과로 대체하지 않습니다.

참가자 화면의 [오류·모호성 실습 안내](../../docs/WORKSHOP_SCENARIOS.md)는 이 계약을
그대로 사용합니다. 장면 선택·예시 조건 적용은 요청하지 않고, 분석과 승인은 기존
`/plan`, `/execute`만 호출합니다. 실습 ID·검토 상태·진행 상황을 API에 보내지 않습니다.
2019-2024는 기존 422 기간 검증 대상입니다. 15-34세 취업자 수의 증감률에서 기간을
2020-2024에서 2021-2023으로 바꾸면 기존 가상 자료의 다른 시작·종료 값을 계산합니다.
원래 기간의 누락값과 0 기준값을 수정하거나 대체하지 않습니다.

## 기존 POST /api/v1/analyze 호환성

기존 요청·응답과 동작을 유지하는 이전 통합 실행 API입니다. 승인 없이 기존 모의 결과를
반환하며, 새 참가자 UI는 이 경로를 사용하지 않습니다. 승인 필수 규칙은 새 UI와
`/execute`에 적용됩니다. 기존 live 비활성화 오류도 유지합니다.
`/analyze`에는 `general_response`, `calculation`, `financial_calculation`을 추가하지 않아 기존 응답 필드를 그대로 유지합니다.
기존 소비자·실습 예제를 깨뜨리지 않기 위한 호환 경로이며 새 계산은 `/execute`에만 적용합니다.

## 검증

저장소 루트에서 `make test`, `make test-web`, `make typecheck`, `make check`를 실행합니다.
`tests/conftest.py`는 앱 import 전 테스트 설정을 주입하고 실제 네트워크 연결을 막습니다.

아래 브라우저 동작 확인은 기본 mock 모드 기준입니다.

1. 두 예시 질문 각각에서 해석 직후 자료·브리핑이 없는지 확인합니다.
2. 대상·지표·기간·비교 기준과 추가 조건을 입력합니다. 미해결 안내와 조회 버튼 상태를 확인합니다.
3. 변경된 항목의 ‘수정됨’과 처음 제시된 값을 확인합니다.
4. 조회 버튼을 눌러 승인 조건과 결과의 조회 조건이 같은지 확인합니다.
5. 질문·조건 변경 시 이전 결과가 사라지고 재승인해야 하는지 확인합니다.
6. 자료원이 불명확한 질문, 잘못된 기간, 요청 실패와 재시도를 확인합니다.
7. 응답 지연 중 질문·조건을 변경해 이전 응답이 현재 화면에 반영되지 않는지 확인합니다.
8. 좁은 화면과 키보드 조작으로 조건 입력·승인이 가능한지 확인합니다.
9. 승인 전에는 일반 응답 예시도 보이지 않고, 승인 후 두 응답과 비교표가 표시되는지 확인합니다.
10. 두 예시 질문에서 일반 응답의 내용이 달라지는지, 조건만 바꾸면 일반 예시는 그대로이고
    근거 기반 브리핑의 조건이 바뀌는지 확인합니다.
11. 실제 모델 출력·공식 자료 조회·실제 지역 순위로 오해할 표현이 없는지 확인합니다.
12. 청년 고용 2020-2024, 15-29세, 고용률에서 증감 폭은 B, 증감률은 C가 1위인지 확인합니다.
13. 15-34세 취업자 수의 증감률에서 0 기준값과 누락값이 순위 없이 표시되는지 확인합니다.
14. 지원하지 않는 연도는 승인할 수 없고, OpenDART는 기존 조건 확인용 응답을 유지하는지 확인합니다.
15. 모바일에서 표만 좌우로 이동하며 값·단위·계산 불가 이유를 읽을 수 있는지 확인합니다.
16. 결과 아래의 검토 항목을 체크·해제하면서 진행 상태와 브리핑 상태 링크가 함께 바뀌는지 확인합니다.
17. 질문·조건 변경, 같은 조건 재조회, 요청 실패·재시도 후 검토 상태가 0/4로 시작하는지 확인합니다.
18. 조건을 바꿔 재승인하면 직전 성공 조건과 이번 조건, 각 결과의 단위·순위가 나란히 표시되는지 확인합니다.
19. 같은 조건 재조회에는 비교가 없고, 질문 변경·재분석 후에는 이전 비교 기준이 사라지는지 확인합니다.
20. 세 실습 장면을 선택해 분석·예시 조건 적용만으로는 조회되지 않는지 확인합니다.
21. 기간 오류를 수정하거나 계산 가능 기간으로 바꾼 뒤 직접 재승인해야 결과가 나오는지 확인합니다.
22. 장면 변경은 결과·비교·검토를 초기화하고, 안내만 닫으면 현재 결과·검토가 유지되는지 확인합니다.
23. 질문 해석의 ‘모의 규칙’ 표시와 접을 수 있는 최초 확인 안내를 확인합니다.
24. 지원 범위 밖 기간을 질문에 직접 넣으면 입력란이 비고 최초 안내에 이유가 남는지 확인합니다.
25. 해석 실패는 질문을 보존하며 이전 결과를 숨기고, 재분석 뒤에도 별도 승인이 필요한지 확인합니다.
26. 해석 방식 선택만으로 요청하지 않고 Gemini 선택 시 질문 전송 안내가 표시되는지 확인합니다.
27. Gemini 비활성·오류 시 모의 규칙으로 자동 전환하지 않으며, 방식 변경 시 조건·비교·검토가 초기화되는지 확인합니다.
28. Gemini 성공 화면은 해석 모델과 mock 자료를 구분하며, 승인 전에는 근거·브리핑이 없는지 확인합니다.

실제 화면은 [OpenDART 기록](../../docs/OPENDART_SMOKE_TEST.md)과
[KOSIS 기록](../../docs/KOSIS_SMOKE_TEST.md)을 따릅니다.
자동 테스트에서는 실제 API를 호출하지 않습니다. 자료 모드 변경·late 응답·조회 실패 때
결과와 검토를 숨기고, 재승인 후 항상 검토 0/4로 시작하는지도 검사합니다.
