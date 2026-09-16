# OpenDART 연간 연결 매출액 · 승인 후 실제 조회

M2의 첫 공공데이터 조회 흐름입니다. 삼성전자 2022·2024년 연결 매출액을 실제 API와
공시 원문으로 대조했으며, 참가자 승인 후 실제 조회·계산·근거·브리핑·검토까지 연결했습니다.
기본 모드는 mock입니다. [실제 확인 기록](OPENDART_SMOKE_TEST.md)에 값과 범위를 남깁니다.

## 내부 계약

`providers/opendart.py`의 `OpenDartClient.fetch_revenue(start_year, end_year)`는
`RevenuePair(start, end, caveats)`를 반환합니다. `enabled=True`를 명시해야 하며,
기본 비활성화 상태나 빈 키에서는 HTTP 클라이언트를 열지 않습니다.
외부 설정을 스스로 읽지 않으므로 호출자가 승인·모드·활성화 조건을 검사해야 합니다.
서버는 live 설정과 승인 조건을 검증한 뒤에만 이 어댑터를 생성합니다.

| 항목 | 지원 범위 |
|---|---|
| 대상 | 삼성전자, 고유번호 `00126380` 고정 |
| 지표 | 매출액만 지원 |
| 기준 | 연간 사업보고서 `11011`, 연결 `CFS` 고정 |
| 연도 | 정수 두 개, `2015 ≤ 시작 < 종료 < 현재 UTC 연도` |
| 금액 | 해당 연도 보고서의 `thstrm_amount`, KRW 원 단위 정수 |
| 호출 수 | 시작·종료 연도에 각 한 번, 최대 두 번 순차 요청 |

`fnlttSinglAcntAll.json`을 사용합니다. HTTP 200과 업무 상태 `000`을 모두 확인한 뒤
회사·사업연도·보고서 식별자가 요청과 일치하는지 검사합니다. 응답에 연결 구분이
포함되어 있으면 요청과 일치해야 합니다. 표준 매출 계정 ID 두 개만 지원하며 계정 이름을
유사 검색하지 않습니다. 손익/포괄손익계산서에서 후보가 둘이면 금액이 같아도 중단합니다.
지원 ID는 [ADR 0005](decisions/0005-opendart-annual-revenue-adapter.md)에 기록했습니다.

`AnnualRevenue`는 다음 정보를 제공합니다.

- 사업연도, 회사·보고서 코드, 연결 기준, 선택한 재무제표 구분과 계정 ID·이름
- `raw_amount`: 앞뒤 공백을 제거한 금액 원문, `amount`: 쉼표 없는 정확한 정수 문자열
- `currency=KRW`, `unit=원`: 단위 변환이나 백만원 단위 추정을 하지 않음
- 접수번호, 접수번호로 구성한 DART 원문 링크, 시간대가 있는 UTC 조회 시각
- `query_parameters`: 키를 제외한 요청 조건 네 개

전기·전전기·당기누적 값으로 대체하지 않습니다. 쉼표 묶음이 잘못되거나 소수·지수·음수·
비유한 값이면 중단합니다. 빈 값·대시는 결측이며 숫자 0과 구분합니다. float를 사용하지
않아 큰 금액을 반올림하지 않습니다. 과도한 숫자·응답 크기에도 상한을 적용합니다.

각 보고서의 당기값을 사용하므로 최신 보고서에서 재작성한 비교 수치와 다를 수 있습니다.
정정 공시 여부와 원문 대조가 필요하며 계산·조회만으로 기사 사용을 승인하지 않습니다.

## 오류와 전송 경계

`OpenDartError.code`와 고정 한국어 메시지만 호출자에게 전달합니다.

| 코드 | 의미 |
|---|---|
| `disabled`, `configuration`, `invalid_request` | 활성화·키·시간 제한·연도 설정 확인 |
| `authentication` | 키·IP·접근 권한 확인 |
| `rate_limited` | 공급자의 요청 한도 또는 HTTP 429 |
| `no_data` | 자료 없음 또는 빈 행 목록 |
| `missing_account`, `ambiguous_account` | 지원 계정 없음 또는 여러 후보 |
| `missing_value`, `invalid_amount`, `unsupported_currency` | 계산 입력값으로 사용할 수 없음 |
| `invalid_response` | JSON·회사·연도·보고서·접수번호 등 계약 불일치 |
| `timeout`, `unavailable` | 제한 시간 초과 또는 공급자/전송 장애 |

두 번째 연도가 실패해도 첫 번째 값을 부분 성공으로 반환하지 않습니다. 자동 재시도,
다른 계정·별도재무제표·다른 연도로의 대체, snapshot fallback은 없습니다.
기본 제한은 요청별 20초이며 응답 본문 수신까지 포함한 시간 제한을 추가로 적용합니다.
리다이렉트·환경 프록시는 사용하지 않고 응답 본문은 2 MB, 행은 2,000개로 제한합니다.

OpenDART 인증키는 공급자 요구대로 URL 인자에만 사용합니다. 이 요청의 비동기 작업 안에서
HTTPX/httpcore 로그를 억제하고 원래 예외·공급자 메시지·키 포함 URL을 반환하지 않습니다.
다른 동시 요청의 로그 수준은 바꾸지 않으며 성공·실패·취소 후 로그 억제 상태를 복구합니다.
기존 미사용 `company()` 골격도 같은 오류·전송 경계를 사용하며 명시적 활성화가 필요합니다.

## 공개 API와 화면

`/plan`과 `/execute`는 기본 `mode=mock`, 선택형 `live`를 지원합니다. `/plan`은
`data_mode`와 모드별 선택값을 반환하며 자료를 조회하지 않습니다. live 공개 범위는
**삼성전자·매출액·2022-2024·연결·연간·증감 폭/률**입니다. 내부 어댑터의 넓은 연도
범위와 구분하며, 지원하지 않는 해석값은 비우고 참가자가 수정하도록 안내합니다.

서버는 `LIVE_API_ENABLED=true`, `PUBLIC_DATA_MODE=live`, `OPENDART_ENABLED=true`와
백엔드 키 설정을 확인합니다. 참가자는 조회 자료를 선택하고 조건을 승인해야 합니다.
`/execute`는 질문의 자료원과 승인 조건을 재검증한 후에만 조회합니다. 해석기를 다시
호출하지 않습니다. `/analyze`는 승인 없는 기존 mock 호환 경로이며 live 실행을 추가하지 않습니다.

실행 응답의 `financial_calculation`은 다음 필드를 제공합니다. mock에서는 `null`입니다.

| 필드 | 의미 |
|---|---|
| `data_origin` | `opendart` |
| `start_year`, `end_year` | 승인한 시작·종료 연도 |
| `start_value`, `end_value`, `input_unit` | 정확한 정수 문자열, `원` |
| `change`, `result_unit` | 변화값 문자열 또는 `null`, `원` 또는 `%` |
| `decimal_places` | 원 단위 증감 폭 `0`, 증감률 `2` |
| `status`, `reason` | `calculated` 또는 `zero_baseline`, 계산 불가 시 한국어 설명 |

Decimal로 계산하며 금액·증감 폭은 정확한 정수, 증감률만 `ROUND_HALF_UP`으로 소수
둘째 자리까지 표시합니다. 시작값 0은 증감률 계산 불가이며 0%로 만들지 않습니다.
누락 금액은 어댑터에서 조회 전체를 중단합니다. 프론트엔드는 금액을 Number로 바꾸거나
다시 계산하지 않습니다. 고용 순위용 `calculation` 계약은 유지하며 재무에는 순위를 만들지 않습니다.

`evidence.query_parameters`와 `query_plan`은 승인한 조건 그대로입니다.
`raw_values`의 두 행에는 `year`, `value`, `raw_amount`, `unit`, `currency`,
`account_id`, `account_name`, `statement_type`, `receipt_no`, `source_url`, `retrieved_at`,
공개 인자 `corp_code`, `bsns_year`, `reprt_code`, `fs_div`를 남깁니다.
`evidence.retrieved_at`은 두 번째 조회 완료 시각이며 행별 시각도 화면에 표시합니다.
키와 인증 URL은 포함하지 않습니다. `data_mode=live`는 공식 자료 출처를 뜻하며
기사 검증 완료를 뜻하지 않습니다. 이번 승인에서 새로 조회했는지는 `cache.status`로 구분합니다.
`brief.verification_status=review_required`를 유지합니다.

브리핑은 조회값·코드 계산으로 구성한 고정 형식입니다. 일반 응답은 계속 미리 작성한
mock 예시이며 실제 모델 응답으로 소개하지 않습니다. 자료 모드 변경 시 조건·결과·
비교·검토를 초기화하고, 비교 기준 변경 후 재승인하면 원/% 결과를 각각 표시합니다.

오류는 HTTP 503(요청 한도는 429), `detail.code=opendart_<내부 오류 코드>`, 고정 한국어
`message`, `field_errors={}`를 반환합니다. 조건 오류는 422 `invalid_conditions`입니다.
설정·조건·승인 오류에서는 외부 조회하지 않고, 공급자 실패 시 부분 결과·자동 대체가 없습니다.

후속 M3의 [공공자료 캐시](PUBLIC_DATA_CACHE.md)를 적용했습니다. 두 연도를 모두 조회·
정규화한 한 쌍만 저장하고, 같은 원자료는 기한 내 재사용하거나 진행 중 조회를 공유합니다.
비교 기준은 매번 다시 계산하며 승인 조건·연도별 원래 조회 시각·접수번호를 보존합니다.
한 연도만 성공한 결과와 만료 후 실패는 재사용하지 않습니다.

## 검증과 제외 범위

`test_opendart.py`는 직접 만든 합성 응답으로 전송·정규화 경계를 검사합니다.
`test_live_financials.py`는 원문 대조한 공개 정규화 발췌로 응답 행을 재구성해 승인·모드·
계약·계산·오류·비밀정보 비노출을 검사합니다. 전체 API 응답 기록이라고 표현하지 않습니다.
`LiveFinancials.test.tsx`는 승인 전 숨김·조건 일치·실제/모의 문구·원문 링크·재승인·모드 변경·
검토 초기화·오류·늦은 응답·정수 표시를 검사합니다. 자동 테스트는 실제 네트워크와 `.env`를
읽지 않습니다. 공개 fixture는 오프라인 테스트용이며 앱의 fallback으로 사용하지 않습니다.

영업이익·별도·분기·다른 회사·추가 연도·모델 브리핑은 포함하지 않습니다.
별도 KOSIS 연결과 공공자료 캐시는 후속 단위에서 완료했으며, 공공자료 호출·동시 실행 제한,
인증·기관 비밀키 관리·배포·행사 부하 시험은 남아 있습니다.

공식 계약: [OpenDART 개발가이드](https://opendart.fss.or.kr/guide/detail.do?apiGrpCd=DS003&apiId=2019020).
