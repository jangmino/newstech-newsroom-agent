# 행사 동시 요청과 대기 처리

[ADR 0022](decisions/0022-workshop-81-capacity.md)의 81명 보강이다. 기존 `/api/v1/event/plan`, `execute`, `general`의
JSON 계약과 legacy API는 유지한다. 행사 화면은 각 경로 뒤에 `/stream`을 붙인 POST로
진행 상태를 받는다. 공유 접근코드 헤더와 승인·조건 검증은 그대로 적용한다.

## 참가자 경험

요청을 접수한 뒤 자료원별 자리가 없으면 순서대로 기다린다. 접수 후 경과 시간,
공급자와 대기 상태를 표시한다. 다시 클릭하거나 재승인할 필요가 없다. 대기는 누적
stage에서240초, 전체 처리는300초가 상한이다. 최대120개 요청을 받아 과도한 접속은 명확히
거절한다. 실제 처리 가능한 한도를 넘는 무거운 조회는 영구 대기시키지 않는다.

취소하면 대기 중인 외부 호출은 시작하지 않는다. 이미 전송한 Gemini 요청의 처리나
과금을 취소한다고 보장하지 않는다. 해당 요청이 끝날 때까지 동시 실행 자리를 보존하고
다음 단계 실행과 늦은 응답 표시를 막는다. 질문·조건 수정은 결과·검토를 초기화한다.

브리핑 생성 실패 시 조회한 근거는 보존한다. 402 결제·401/403 권한·429 한도·타임아웃을
구분해 안내한다. 공식 저장 자료는 참가자가 선택하고 고정 조건을 다시 승인해야 한다.

## 실행과 재시도

- 공급자별 FIFO 입장 대기. 기존 분당·동시 호출 제한의 같은 카운터를 사용한다.
- 기다리는 작업은 비동기로 정지하며 스레드를 점유하지 않는다.
- OpenDART 복수 공시는 개별 HTTP 요청마다 다시 줄에 들어간다.
- 동일한 공공자료 조회는 합치고 원자료 캐시를 유지한다. 마지막 행사 대기자가 떠나면
  불필요해진 공유 조회를 취소한다. 다른 승인 대기자가 있으면 계속 조회한다.
- HTTP 429에 공급자가 명시한 1~30초 Retry-After가 있을 때만 최대 1회 재시도한다.
  이때 같은 공급자의 다른 대기 요청에도 일시 정지를 적용한다.
- 일일 한도 오류, 402, 인증 오류, 형식 오류, 응답 수신 여부가 불명확한 타임아웃은
  자동 재시도하지 않는다. 브라우저 스트림 단절도 자동 재전송하지 않는다.

## 스트림 계약

Content-Type은 `application/x-ndjson`이다. 각 줄은 완전한 JSON이며 `type`과
`request_id`를 포함한다. HTTP 헤더의 X-Request-ID와 같아야 한다.

| type | 필드 | 의미 |
|---|---|---|
| progress | stage, provider, elapsed_seconds, waited_seconds, queue_ahead, wait_limit_seconds, request_limit_seconds | 접수 직후 및 약 1초마다 |
| result | result, metrics | 기존 JSON 응답과 호출 수·경과 시간 |
| error | detail.code, detail.message, detail.field_errors | 한국어 오류와 고정 오류 코드 |

stage는 accepted, waiting, running, source_wait, retry_wait이며 provider는 null 또는
gemini/opendart/kosis이다. 정확한 완료 시각이나 전체 대기 순위를 약속하지 않는다.
진행 상태에는 자료 값이나 모델의 내부 사고를 포함하지 않는다. result 또는 error가
종료 신호다. `queue_ahead`는 같은 공급자에서 먼저 기다리는 요청 수이며 실행 중에는 null이다.
취소로 앞선 요청이 제거되면 다음 진행 알림에 반영한다. 두 시간 상한은 서버 설정값이다.
종료 신호 없이 끊기면 완료 여부 불명으로 안내한다. 스트림 시작 뒤 오류는
HTTP 200에서도 error 이벤트로 전달되므로 HTTP 상태만으로 성공을 집계하면 안 된다.

`GET /api/v1/event/queue`는 동일 접근코드로 보호되며 활성 요청 수·최대 요청 수·시간
상한·프로세스 내 누적 공급자 호출 시작 수·완료/실패 수를 반환한다. 참가자 질문·키·
응답 본문을 포함하지 않는다. 카운터는 해당 프로세스 재시작 때 초기화되며 공급자 청구
내역이나 프로젝트 전체 호출 수가 아니다. 브리핑 실패를 담은 결과는 완료와 별도 집계한다.

## Cloud Run과 운영

행사 후보 리비전은 HTTP 동시160, 요청 제한330초, 1 CPU/512 MiB/리비전 최대1개다.
Gemini 분당120/동시16, 공공자료 공급자별 분당30/동시2와는 다른 설정이다. 앱은300초 안에
종료를 시도하고 브라우저는 서버 처리 상한+60초(기본360초)에 연결을 정리한다. 대기 중에도 입장·운영 조회는
외부 호출 없이 응답해야 한다.

메모리 대기열은 영속 작업 시스템이 아니다. 서버 재시작·배포 때 진행 중 작업을 복원하지
않는다. 두 리비전의 대기열과 한도는 서로 공유되지 않는다. 후보 검증 중 공개 버전에
동시 부하를 보내지 않고, 전환은 진행 중 요청이 없는 시점에 수행한다. 최대 인스턴스
설정도 일시적 교체 인스턴스까지 엄격히 하나라고 보장하는 기능은 아니다.

평시 최소 인스턴스 0을 유지한다. 리뷰·행사 시작 직전 예시 실행으로 예열하고,
행사 시간의 최소 1 유지가 필요하면 아래 명령을 사용한 뒤 종료 후 반드시 0으로 복귀한다.
PUBLIC_ACCOUNT/PROJECT/REGION/SERVICE는 승인된 개인 stage 공개 식별자로 치환한다.

```bash
gcloud run services update SERVICE --account=PUBLIC_ACCOUNT --project=PROJECT --region=REGION --min=1
gcloud run services update SERVICE --account=PUBLIC_ACCOUNT --project=PROJECT --region=REGION --min=0
```

## 검증

stage 설정은 `EVENT_MAX_REQUESTS=120`, `EVENT_QUEUE_WAIT_SECONDS=240`,
`EVENT_REQUEST_TIMEOUT_SECONDS=300`이다. local 기본40/120/180은 유지한다.
SDK가 반환한 입력/출력 토큰 개수만 `result.metrics` 및 보호된 queue 누적 상태에 기록한다.
생각 토큰·캐시 등 청구 항목 전체 또는 프로젝트 전체 사용량을 뜻하지 않는다.

81명 수동 시험은 `scripts/workshop_capacity_rehearsal.py`로5→20→40→81명 순으로 한다.
마지막 `--users 81 --full-flow --execute-live`는 계획·승인된 공식 원자료·브리핑·일반 응답을
포함한다. 실패하면 확대를 멈추며 재현한 모델 품질 오류와 혼잡 오류를 따로 기록한다.
기존 아래30명 도구·기록은 과거 회귀용이다.

자동 테스트는 외부 네트워크 없이 FIFO·동시 수·분당 한도 해제·대기 상한·취소·공유 조회·
스트림 단절·접근 보호·승인 검사·오류 구분을 확인한다. 실제 호출은 별도 명시적 실행이다.

```bash
apps/api/.venv/bin/python scripts/event_burst_rehearsal.py \
  --origin https://CANDIDATE.run.app --access-code-file .cache/stage-workshop-code.txt \
  --output .cache/burst-NEW.json --users 5 --profile same --execute-live
```

5→15→30명 순서로 확대하고 마지막에는 `--users 30 --profile mixed`도 확인한다.
same은 같은 고용 예시, mixed는 지역·연령·재무 지표/기간·공시 기간이 다른 승인 조건이다.
각 단계의 계획 결과는 운영자가 미리 정한 검증 조건으로 편집·승인한 것으로 모사한다.
실제 참가자 30명의 판단·브라우저·행사장 네트워크를 대체한 검증은 아니다.

각 단계는 계획·조회·일반 응답을 동시에 시작하며 HTTP 200뿐 아니라 종료 이벤트,
조건 일치, 브리핑 상태, 대기 시간과 운영 화면 응답을 기록한다. 실패 시 다음 단계로
확대하지 않는다. 목표는 혼잡으로 인한 즉시 실패 0건과 단계별 p95 120초 이내다.
모델 품질 실패는 혼잡과 분리해서 기록한다. 실제 결과는 EVENT_VALIDATION.md에 추가한다.
