# 환경과 책임 전환

## Local

목적은 빠른 개발과 소규모 검증입니다.

- 소유자: 개발자 개인
- 기본 모드: `PUBLIC_DATA_MODE=mock`, `LIVE_API_ENABLED=false`
- 비밀정보: 로컬 `.env`
- Gemini: 개인 프로젝트의 인증키로 제한적 시험 가능
- OpenDART/KOSIS: 개인 키로 필요한 최소 호출만 수행
- 과금 경고와 사용량 제한을 개인 프로젝트에서 설정

## 행사용 접근코드

`WORKSHOP_ACCESS_CODE`가 비어 있으면 local/test에서만 제한 없이 사용합니다.
값을 넣으면 모의·실제·저장 자료와 `/analyze`를 포함한 모든 실습 API에 코드를 요구합니다.
영문 대소문자·숫자·`_`·`-` 16~128자의 무작위 코드를 사용하고 API를 재시작합니다.
기존 로컬 `.env`는 이번 구현에서 변경하지 않았습니다.

stage/event는 `APP_ENV`를 명시하고 기관 Secret Manager에서 코드를 주입합니다.
이 환경에서 코드가 없거나 잘못되면 503으로 접근을 막으며 운영자가 설정을 수정해야 합니다.
개인 API 키와 별개인 행사 코드를 프론트엔드 환경변수나 URL에 넣지 않습니다.
참가자 입력은 탭 메모리에만 유지하고 나가기·새로고침 시 초기화합니다.
[API 계약·검증·교체 한계](WORKSHOP_ACCESS.md)를 참고하십시오.

## 요청 ID와 운영 로그

운영 확인에는 [요청 ID·구조화 로그](REQUEST_LOGGING.md)를 사용합니다. API 서버의 stdout에
고정 필드의 JSON이 출력되며 참가자 오류 화면의 문의 번호로 찾습니다. 코드·질문·조건·키·
URL 쿼리는 기록하지 않습니다. 기관 stage/event에서는 플랫폼 로그의 보관·IAM·쿼리 처리도
별도로 확인해야 합니다. 외부 로그 서비스 설정이나 배포는 이번 단위에서 실행하지 않았습니다.

## Gemini 질문 해석 활성화

기본값은 계속 모의 규칙입니다. 실제 연결 코드는 모의 HTTP 전송으로 검증했으며,
2026-09-16 로컬 API 키로 네 질문의 실제 접근·조건 해석을 확인했습니다.
다른 계정·Vertex·추가 표현의 품질은 별도 확인이 필요합니다.
활성화는 운영자가 백엔드 환경에서 설정하고 서버를 다시 시작합니다.
키를 채팅·브라우저·프론트엔드 변수·Git에 넣지 않습니다.

`GEMINI_PLANNER_ENABLED` 항목이 없으면 기본값 `false`입니다. 기존 키를 백엔드가
사용하게 두고 `.env`를 수정하지 않은 채 이번 실행에만 활성화할 수도 있습니다.
저장소 루트에서 다음 명령을 사용합니다. 이미 실행 중인 API 서버는 먼저 종료합니다.

```bash
GEMINI_PLANNER_ENABLED=true LIVE_API_ENABLED=true PUBLIC_DATA_MODE=mock GEMINI_AUTH_MODE=api_key make dev-api
```

이 실행 설정은 `.env`에 저장되지 않습니다. 서버를 종료하고 일반 `make dev-api`로
시작하면 기존 파일 설정이 다시 적용됩니다. `LIVE_API_ENABLED=true`만으로 공공데이터
mock을 해제하는 것은 아닙니다. Gemini 활성화만으로 OpenDART를 호출하지 않습니다. 아래의 별도 자료 설정이 필요합니다.

```text
PUBLIC_DATA_MODE=mock
LIVE_API_ENABLED=true
GEMINI_PLANNER_ENABLED=true
GEMINI_AUTH_MODE=api_key
GEMINI_MODEL=gemini-3.8-flash
GEMINI_TIMEOUT_MS=20000
GEMINI_MAX_OUTPUT_TOKENS=2048
REQUESTS_PER_MINUTE=30
MAX_CONCURRENT_REQUESTS=8
```

`GEMINI_API_KEY`는 기존 백엔드 비밀 설정에만 보관합니다. Vertex AI 방식은 기존
`GEMINI_AUTH_MODE=vertex_ai`, `GOOGLE_CLOUD_PROJECT`, `GOOGLE_CLOUD_LOCATION`과
실행 환경의 ADC를 사용합니다. stage/event는 기관 자격증명을 사용하며 이번 단위에서는
실제 Vertex 인증·리전·모델 접근을 검증하지 않았습니다.

화면의 기본값은 여전히 ‘모의 규칙’입니다. 참가자가 ‘Gemini · 실제 모델’을 선택하면
질문의 외부 전송을 안내하고 ‘질문 분석’을 누를 때만 요청합니다. 위 설정에서는 자료가
mock이며 OpenDART·KOSIS는 호출하지 않습니다. 다시 분석할 때마다 모델 요청이 한 번
추가되고, 조건 편집·조회 승인은 Gemini를 호출하지 않습니다. 기본 한도는 프로세스당
분당 30회·동시 8회이며 서버 재시작 시 초기화됩니다. 별도의 인증 요청은 SDK 인증 방식에
따라 발생할 수 있습니다. 브라우저에서 요청을 취소해도 이미 보낸 모델 요청의 비용을
되돌리지 못하며 서버의 HTTP 타임아웃·호출 한도는 계속 적용됩니다.

실제 확인은 공개 예시 두 질문과 명확한 조건을 쓴 변형을 합쳐 최대 4회부터 시작합니다.
질문별 기대 조건과 승인 확인은 [실제 해석 확인 절차](GEMINI_SMOKE_TEST.md)를 따릅니다.
모델이 모호한 기간·연령·지표를 추측하지 않는지, 수정·승인 조건이 최종 결과와 같은지
확인합니다. 오류가 나면 자동 반복하지 않고 설정·접근·응답 형태를 먼저 점검합니다.
이 확인에서도 기사에 사용할 실제 자료는 얻을 수 없습니다.

개발 기본값으로 돌아갈 때는 `GEMINI_PLANNER_ENABLED=false`, `LIVE_API_ENABLED=false`로
바꾸고 서버를 다시 시작합니다. 이 문서의 값은 활성화 안내이며 저장소가 자동 적용하지 않습니다.

## OpenDART 실제 자료 활성화

기본값은 비활성화입니다. 로컬 `.env`에 기존 `OPENDART_API_KEY`를 유지하고 다음
공개 설정을 적용한 뒤 백엔드를 다시 시작합니다. 키를 출력하거나 프론트엔드에 넣지 않습니다.

```text
LIVE_API_ENABLED=true
PUBLIC_DATA_MODE=live
OPENDART_ENABLED=true
```

세 설정을 모두 만족해야 실제 자료 요청을 허용합니다. `PUBLIC_DATA_MODE=live`는
서버의 허용 설정이며 화면의 기본 선택을 바꾸거나 KOSIS를 활성화하지 않습니다.
화면의 ‘조회 자료’에서 ‘공식 실제 자료 · OpenDART / KOSIS’를 선택하고, 삼성전자 2022-2024년
연간 연결 매출액 조건을 분석·승인해야 실제 요청합니다. 질문 해석은 모의 규칙과
Gemini 중 독립적으로 선택합니다. `/health`의 `opendart_enabled`는 설정 허용 여부이며
키 유효성·공급자 가용성 보증이 아닙니다.

캐시가 없거나 만료됐으면 두 연도에 각각 한 번, 최대 두 번 순차 조회합니다. 요청별
20초 제한이며 첫 오류에서 중단합니다. 자동 재시도·mock/snapshot 대체는 없습니다.
동일 자료의 재승인은 기한 내 원자료를 재사용하고 계산합니다. 화면 취소가 이미 보낸 요청을
되돌리지는 않습니다. 공유 행사 접근코드는 위 M3 계약으로 추가했으며,
행사 전체 호출 제한·개인별 인증·외부 배포는 아직 적용하지 않았습니다.

이번 개발 환경에는 사용자 승인에 따라 위 세 공개 설정을 로컬 `.env`에 적용했습니다.
Gemini 설정과 키는 유지했습니다. 저장소의 기본값과 `.env.example`은 비활성 상태입니다.
`OPENDART_ENABLED=false`로 바꾸면 OpenDART만 차단합니다. `PUBLIC_DATA_MODE=mock`으로
바꾸고 재시작하면 Gemini를 유지하면서 모든 공공자료를 mock으로 제한할 수 있습니다.

## KOSIS 실제 자료 활성화

기존 `KOSIS_API_KEY`는 백엔드 `.env`에만 두고 다음 공개 설정을 적용한 뒤 API 서버를
다시 시작합니다. `KOSIS_ENABLED`가 없으면 기본값은 `false`입니다.

```text
LIVE_API_ENABLED=true
PUBLIC_DATA_MODE=live
KOSIS_ENABLED=true
```

KOSIS 활성화는 OpenDART·Gemini 활성화와 독립적입니다. 화면의 ‘공식 실제 자료 ·
OpenDART / KOSIS’와 ‘모의 규칙’을 선택한 뒤 다음 질문으로 분석·승인할 수 있습니다.

```text
전국 시·도 15-29세 청년 고용률 2020-2024년 연간 증감 폭 비교
```

계획·편집에는 KOSIS 호출이 없고, 승인 후 캐시가 없거나 만료됐으면 최대 85개 셀을
한 번 조회합니다. 비교 기준만 바꾸거나 같은 조건을 승인하면 기한 안의 원자료를 재사용합니다.
HTTP/전체 수신 제한 20초, 응답 크기 상한 2MB이며 자동 재시도·mock/snapshot 대체가 없습니다.
`/health`의 `kosis_enabled`는 설정상 허용 여부이며 키 유효성이나 공급자 상태를 보증하지 않습니다.
15~34세·취업자 수·월/분기·2020~2024년 밖 기간은 지원하지 않습니다.

이번 로컬 환경은 사용자 승인에 따라 `KOSIS_ENABLED=true`를 추가하고 실제 UI 조회를
2회 확인했습니다. 키와 Gemini/OpenDART 설정은 유지했으며 `.env`는 Git에서 제외합니다.
저장소 기본값은 계속 비활성화입니다. `KOSIS_ENABLED=false`로 바꾸고 재시작하면
KOSIS만 비활성화합니다. 자세한 결과는 [확인 기록](KOSIS_SMOKE_TEST.md)을 참고하십시오.

## 공공자료 캐시

```text
PUBLIC_DATA_CACHE_ENABLED=true
CACHE_TTL_SECONDS=3600
CACHE_MAX_ENTRIES=64
```

기본값은 성공한 정규화 자료를 공급자별 최대 64건·1시간 동안 프로세스 메모리에 보관합니다.
live 활성화를 대신하지 않으며 mock·Gemini 질문 분석에는 적용하지 않습니다. 설정을 바꾼
뒤 서버를 재시작해야 합니다. `.env`에 항목이 없으면 위 기본값을 사용합니다.
이번 개발에서는 `.env`나 기존 키를 변경하지 않았습니다.

`PUBLIC_DATA_CACHE_ENABLED=false`로 끄면 이전처럼 매 승인마다 실제 조회합니다.
캐시가 활성화돼 있으면 브라우저 새로고침으로 비워지지 않고 백엔드 재시작으로 비워집니다.
여러 워커·Cloud Run 인스턴스 사이에서는 공유하지 않습니다. 화면에는 재사용 여부·원래
조회 시각·기한을 표시합니다. [자세한 계약](PUBLIC_DATA_CACHE.md)을 참고하십시오.

## 공공자료 호출 제한

```text
PUBLIC_DATA_REQUESTS_PER_MINUTE=30
PUBLIC_DATA_MAX_CONCURRENT_REQUESTS=2
```

항목이 없으면 위 기본값을 사용하며 변경 시 서버 재시작이 필요합니다. 이번 개발에서는
`.env`나 기존 키를 변경하지 않았습니다. OpenDART/KOSIS 각각 독립적으로 최근 60초의
HTTP 시작 30회·동시 2회를 허용합니다. 제공기관의 공식 한도가 아닌 앱의 보호 기본값입니다.
OpenDART는 두 연도를 조회하므로 정상 완료를 위해 분당 한도를 최소 2회 이상으로 설정합니다.
`REQUESTS_PER_MINUTE`·`MAX_CONCURRENT_REQUESTS`는 기존 Gemini 한도로 유지합니다.

캐시 hit/공유 대기자는 추가 횟수를 쓰지 않고, 캐시를 꺼도 실제 요청 제한은 유지됩니다.
초과 시 한국어 429 안내로 중단하며 자동 재시도·자료 대체를 하지 않습니다. 재시작 시
초기화되고 여러 worker/Cloud Run 인스턴스에서 합산하지 않습니다. 행사 전체·일일 할당량은
별도 정책과 부하 검증이 필요합니다. [자세한 계약](PUBLIC_DATA_LIMITS.md)을 참고하십시오.

## 공식 저장 자료

`FALLBACK_SNAPSHOT_ENABLED=true`는 명시적으로 선택한 공식 저장 자료의 계획·실행을
허용합니다. 기본 true이며 live 활성화·개인 키·캐시·외부 호출 한도와 독립적입니다.
`false`로 바꾸고 백엔드를 재시작하면 계획·실행 모두 중단합니다. 자동 fallback 스위치가 아닙니다.
이번 작업에서 `.env`나 키는 변경하지 않았습니다.

화면에서 ‘공식 저장 자료 · 확보 시점 기준’과 ‘모의 규칙’을 선택하면 외부 API 호출 없이
확인할 수 있습니다. 실제 조회 오류 뒤에는 ‘저장 자료로 조건 다시 확인’으로 입력 조건을
유지해 전환하고 안내를 읽은 뒤 다시 승인합니다. 직접 Gemini 분석을 선택하면 질문 해석만
별도 외부 호출합니다. [지원 범위·재승인·검증](SNAPSHOT_FALLBACK.md)을 참고하십시오.

## Stage

목적은 실제 행사와 같은 조건의 리허설과 부하 시험입니다.

- 소유자: 건국대학교 또는 주최 측
- 배포: 기관 GCP 프로젝트의 Cloud Run
- Gemini: 기관 프로젝트의 Gemini API 인증키 또는 Vertex AI
- 공공데이터: 기관·주최 측 담당자 명의 OpenDART/KOSIS 키
- 비밀정보: Secret Manager
- 필수 확인: 결제, 모델 접근, API 활성화, 할당량, 로그 열람, 장애 담당자
- 개인 키를 stage에 복사하지 않음

## Event

목적은 약 30명의 참가자가 동시에 사용하는 워크숍 운영입니다.

- stage에서 검증된 동일 이미지를 사용합니다.
- 행사 직전 기능 추가를 하지 않습니다.
- 요청 속도 제한, 캐시, 모니터링과 snapshot fallback을 켭니다.
- 외부 API 장애 시 진행자가 즉시 fallback으로 전환할 수 있어야 합니다.
- 행사 종료 후 서비스 공개 여부, 로그 보존, 키 폐기 일정을 주최 측이 결정합니다.

## 건국대학교·주최 측 제공 체크리스트

- [ ] 기관 GCP 프로젝트 ID
- [ ] 결제 계정 연결과 예산 경고
- [ ] Cloud Run·Cloud Build·Artifact Registry 사용 승인
- [ ] Vertex AI 또는 Gemini API 사용 방식 확정
- [ ] 개발자에게 필요한 최소 IAM 권한과 만료 시점
- [ ] 런타임 서비스 계정
- [ ] Secret Manager secret 생성 및 접근 권한
- [ ] 기관 소유 OpenDART 인증키
- [ ] 기관 소유 KOSIS 인증키
- [ ] 각 API 할당량 확인 및 상향 담당자
- [ ] 행사 당일 운영·장애 의사결정 담당자
- [ ] 행사 후 서비스·로그·키 처리 방침

## 초기 권한 논의 기준

권한은 기관 정책에 맞춰 최소화합니다. Cloud Run 배포, 빌드, 서비스 계정 사용, 로그 열람, Secret Manager 접근이 필요할 수 있으나 프로젝트 전체 Owner 권한을 기본 요구하지 않습니다. 실제 IAM 역할은 배포 방식이 확정된 뒤 기관 관리자와 검토합니다.
