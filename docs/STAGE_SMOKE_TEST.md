# 개인 임시 stage 배포 확인 기록

- 날짜: 2026-09-17
- 배포 소스: `2bae7cc`
- 범위: [ADR 0015](decisions/0015-temporary-personal-stage.md)의 개인 임시 stage
- 결과: Cloud Build·Cloud Run 배포 및 소규모 mock/snapshot 확인 완료

## 실제 구성

사용자가 지정한 개인 계정으로 기존 프로젝트와 분리된 전용 프로젝트를 만들었습니다.
서울 리전의 단일 Cloud Run에 1 CPU·512 MiB·동시 요청 8·최소 0·리비전 최대 1·요청 기반
과금을 적용했습니다. 준비된 이미지 digest와 Secret 버전 `1`을 고정했습니다.
프로젝트 ID·URL·리비전·이미지·빌드 ID는 Git 제외 파일 `.cache/stage-deployment.json`,
배포 입력은 `infra/stage-config.local.json`에 보관합니다. 기본 CLI 계정·프로젝트는 바꾸지 않았습니다.

런타임 계정은 접근코드 Secret 읽기, 별도 빌드 계정은 이미지 저장소 쓰기·소스 버킷 읽기·
로그 쓰기 권한을 사용합니다. 서비스 계정 키 JSON과 공급자 API 키는 만들거나 복사하지
않았습니다. 접근코드는 Secret Manager에 있고 로컬 사본 `.cache/stage-workshop-code.txt`는
권한 `600`이며 Git과 업로드 대상에서 제외합니다. 코드 값은 문서·로그·명령 인자로 출력하지 않습니다.

이 프로젝트만 대상으로 월 **10,000 KRW** 비용 알림을 생성했습니다. 실제 사용액의
50%·90%·100%에서 기본 결제 IAM 수신자에게 알립니다. 자동 지출 차단이 아닙니다.
Cloud Logging `_Default` 보관 기간은 30일로 확인했습니다. 기관 전환 시 보관·IAM 정책을
다시 결정해야 하며 임시 stage 검증을 행사 운영 정책 승인으로 보지 않습니다.

## 검증

1. `make doctor` 통과. 자동 테스트는 환경 파일·실제 공급자 네트워크 없이 실행했습니다.
2. `UV_OFFLINE=1 make check`: 백엔드 **663개**, 프론트엔드 **167개**, Ruff·TypeScript·
   웹 빌드·Python wheel/sdist 통과. 별도 배포 스크립트 Ruff 검사도 통과했습니다.
   기존 테스트 의존성 deprecation 경고 2건은 남아 있습니다.
3. 배포 준비 테스트 14개: 비밀/캐시/테스트 파일 제외, 소스 symlink 거절, 누락 입력·
   덮어쓰기 거절, 명시적 대상·IAM 비공개 명령·고정 Secret 버전·이미지 digest, live off 확인.
4. 허용 목록 패키징과 실제 gcloud 업로드 목록은 **63개 파일**입니다. `.env`·Git 이력·
   로컬 설정·접근코드·개인 공급자 키를 포함하지 않았습니다. 업로드 대상 실제 비밀정보 검사 0건.
5. 로컬 Docker Desktop에서 Linux AMD64 이미지 빌드와 단일 컨테이너 HTTP **20회** 확인.
   이전 원격 Docker 연결은 사용하지 않았고 검증용 컨테이너는 종료했습니다.
6. Cloud Build 성공 후 고정 digest로 IAM 비공개 배포. Google 인증을 통과해도 앱
   접근코드가 없으면 운영 상태 API가 401로 차단됨을 확인했습니다. Secret 주입과 live off 확인.
7. 사용자 승인에 따라 해당 서비스의 `roles/run.invoker`만 `allUsers`에 부여했습니다.
   공개 URL에서 HTTP **21회**로 아래 동작을 확인했습니다.
8. 브라우저에서 HTTPS·정적 UI·한국어 입장 화면이 정상이며 코드 입력 전 질문 화면이
   숨겨짐을 확인했습니다. 실제 접근코드를 브라우저 자동화 도구에 전달하지 않았습니다.
9. 최종 승인 응답의 요청 ID가 Cloud Logging의 앱 로그와 일치했습니다. 앱이 내보낸
   10개 허용 필드 중 `severity`는 로그 최상위, 나머지 9개는 `jsonPayload`에서 확인했습니다.
   실행 경로·200 상태가 일치하며 조회한 앱 로그에서 접근코드 비노출을 확인했습니다.
10. `git diff --check`와 변경 문서의 로컬 링크 검사를 통과했습니다. Git 추적·추가 대상
    155개 파일의 비밀정보 검사에서 발견 0건이며 `.env`·로컬 배포 설정·접근코드·배포 기록의
    Git 제외 상태를 확인했습니다.

| 확인 대상 | 결과 |
|---|---|
| UI·JS asset·`/health` | 200, stage 환경·live 비활성 |
| 공개 입장 상태 | `required=true`, `available=true` |
| 코드 없는 plan·운영 상태·문서 | 401 |
| 코드로 입장·운영 상태 조회 | 200, 세 공급자 비활성·두 저장 파일 사용 가능 |
| mock + KOSIS/OpenDART | 계획에 근거 없음 → 승인 없는 실행 422 → 승인 후 결과 200 |
| snapshot + KOSIS/OpenDART | 버전 확인 → 승인 없는 실행 422 → 승인 후 공식 저장 결과 200 |
| 승인 결과 | 자료 모드·자료원·요청 ID 일치, `verification_status=review_required` 유지 |

Gemini·OpenDART·KOSIS 실제 호출은 **0회**입니다. 로컬 `.env`와 기존 개발 서버의 live 설정은
변경하지 않았습니다. 새로운 DB·참가자 계정·자동 발행 기능은 없습니다.

## 남은 범위

이번 결과는 소규모 배포 확인이며 30명 부하 시험이나 실제 공급자 클라우드 연결 검증이
아닙니다. 다음 최소 기능은 이 stage의 **30명 동시 사용 시험(mock/저장 자료)**입니다.
실제 공급자 Secret 연결·소규모 live 검증, 장애 리허설, 운영자 가이드와 기관 환경 재배포가
남아 있습니다. 기관 계정을 받으면 [전환 절차](STAGE_DEPLOYMENT.md#기관-계정을-받았을-때)를 따릅니다.
